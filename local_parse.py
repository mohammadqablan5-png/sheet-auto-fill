"""Free, offline extraction of work-order fields from PDF/text.

No API, no network, no cost. Reads the PDF's embedded text with pdfplumber
(falling back to pypdf) and pulls fields out with labelled-value lookups plus
pattern matching tuned to facility-maintenance work orders.

Scanned/photographed PDFs contain no text layer; those are reported clearly
rather than returning empty rows.
"""
import io
import re
import statistics

from fields import FIELD_ORDER

# ------------------------------------------------------------------ PDF text


def _box(run: list, text: str) -> dict:
    return {
        "text": re.sub(r"\s{2,}", " ", text).strip(),
        "x0": min(c["x0"] for c in run),
        "x1": max(c["x1"] for c in run),
        "y0": min(c["top"] for c in run),
        "y1": max(c["bottom"] for c in run),
        "h": max(max(c["bottom"] - c["top"] for c in run), 1.0),
    }


def _chars_to_boxes(chars: list) -> list:
    """Rebuild the phrases a reader sees from individually placed glyphs.

    These PDFs position characters one at a time, so reading them as flat lines
    interleaves neighbouring columns ("W 81 a 9 l 3 gr M ee a n l 's…") and
    scatters spaces through every value. Working from the glyph boxes instead:
    characters are grouped into rows, then split into phrases wherever the gap
    is far wider than the type — which is exactly where a column boundary is —
    and a space is inserted only where the gap is wide enough to be one.
    """
    chars = [c for c in chars if (c.get("text") or "").strip()]
    if not chars:
        return []

    chars.sort(key=lambda c: (round(c["top"], 1), c["x0"]))
    rows, current = [], [chars[0]]
    for c in chars[1:]:
        head = current[0]
        height = max(head["bottom"] - head["top"], 1.0)
        if abs(c["top"] - head["top"]) <= max(1.0, height * 0.6):
            current.append(c)
        else:
            rows.append(current)
            current = [c]
    rows.append(current)

    boxes = []
    for row in rows:
        row.sort(key=lambda c: c["x0"])
        width = statistics.median([c["x1"] - c["x0"] for c in row]) or 1.0
        space_gap = max(width * 0.30, 0.2)     # measured: real spaces ≈ 0.5×width
        break_gap = max(width * 2.2, 2.5)      # column gaps are far wider still

        run, text = [row[0]], row[0]["text"]
        for prev, c in zip(row, row[1:]):
            gap = c["x0"] - prev["x1"]
            if gap > break_gap:
                boxes.append(_box(run, text))
                run, text = [c], c["text"]
                continue
            if gap > space_gap:
                text += " "
            text += c["text"]
            run.append(c)
        boxes.append(_box(run, text))

    return [b for b in boxes if b["text"]]


def pdf_word_boxes(data: bytes) -> list:
    """Pages of positioned text phrases — the text-layer twin of ocr.pdf_boxes()."""
    try:
        import pdfplumber
    except Exception:
        return []
    pages = []
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                pages.append(_chars_to_boxes(page.chars))
    except Exception:
        return []
    return pages


def pdf_text(data: bytes) -> str:
    text = ""
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(data)) as pdf:
            pages = [(p.extract_text() or "") for p in pdf.pages]
        text = "\n".join(pages)
    except Exception:
        pass
    if len(text.strip()) < 40:
        try:
            import pypdf

            reader = pypdf.PdfReader(io.BytesIO(data))
            text = "\n".join((p.extract_text() or "") for p in reader.pages)
        except Exception:
            pass
    return text


# ------------------------------------------------------------------ patterns

JOB_ID_RE = re.compile(
    r"\b((?:JOB|[A-Za-z]{2,4})[-\s]?\d{5,6}[-\s]?\d{3,6}|WO[-#\s]?\d{4,}|W/?O\s*#?\s*\d{4,})\b",
    re.I)
MONEY_RE = re.compile(r"\$\s?([\d,]+(?:\.\d{2})?)")
PHONE_RE = re.compile(r"(\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4})")
ZIP_LINE_RE = re.compile(r"^(.*?[A-Za-z].*?),\s*([A-Z]{2})\.?\s+(\d{5})(?:-\d{4})?\s*$")
CITY_ST_RE = re.compile(r"([A-Za-z][A-Za-z .'\-]+),\s*([A-Z]{2})\s+\d{5}")
DATE_RE = re.compile(
    r"\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{2,4}"
    r"|\d{1,2}/\d{1,2}/\d{2,4}"
    r"|\d{4}-\d{2}-\d{2})\b", re.I)

PLATFORMS = ["apex", "keystone", "smartride", "jous", "servicechannel", "corrigo",
             "fexa", "ecotrak", "facilitysource", "sms assist", "lightning"]

# label -> canonical field. Longest labels first so "nte date" beats "nte".
LABELS = [
    (["work order number", "work order #", "work order no", "work order",
      "job number", "job id", "job #", "wo number", "wo #", "ticket number",
      "ticket #", "service request", "sr #", "call #"], "job_id"),
    (["not to exceed amount", "not to exceed", "nte amount", "nte $", "nte"], "nte"),
    (["scope of work", "work description", "description of work", "problem description",
      "problem", "description", "issue", "reason for call", "work requested",
      "service description", "notes to technician"], "sow"),
    (["site address", "store address", "service address", "job address", "location address",
      "property address", "address", "location", "site", "store"], "address"),
    (["complete by", "completion date", "due date", "date due", "required by",
      "expiration date", "expires", "eta", "scheduled date", "target date", "deadline",
      "nte date", "priority date"], "deadline"),
    (["technician", "assigned tech", "tech name", "vendor tech", "handyman"], "handyman"),
    (["requested by", "contact name", "site contact", "store contact", "assignee",
      "contact"], "assignee"),
    (["client", "customer", "platform", "network", "dispatched by", "company"], "company"),
    (["trade", "category", "priority", "status"], "job_status"),
]

STOP_LABELS = {lbl for group, _ in LABELS for lbl in group}
_LABEL_LOOKUP = [(lbl, field) for group, field in LABELS for lbl in group]
_LABEL_LOOKUP.sort(key=lambda x: -len(x[0]))


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip(" \t:;-–—")


def _looks_like_label(line: str) -> bool:
    head = _clean(line).lower().rstrip(":").strip()
    return head in STOP_LABELS


# ------------------------------------------------------------------ fields


def _labelled_values(lines: list) -> dict:
    """Collect 'Label: value' pairs, including value-on-next-line layouts."""
    found = {}
    for i, raw in enumerate(lines):
        line = raw.strip()
        if not line:
            continue
        low = line.lower()
        for label, field in _LABEL_LOOKUP:
            # label must start the line, followed by : - or end of line
            m = re.match(rf"{re.escape(label)}\s*[:#\-–]?\s*(.*)$", low)
            if not m:
                continue
            value = line[m.start(1):].strip() if m.group(1) else ""
            if not value:
                # value sits on following line(s)
                parts = []
                for nxt in lines[i + 1:i + 4]:
                    if not nxt.strip() or _looks_like_label(nxt):
                        break
                    parts.append(nxt.strip())
                    if field != "sow":
                        break
                value = " ".join(parts)
            value = _clean(value)
            if value and field not in found:
                found[field] = value
            break
    return found


def _address_block(lines: list) -> tuple:
    """Best-effort full address + 'City, ST' from a street/city-state-zip pair."""
    for i, raw in enumerate(lines):
        line = raw.strip()
        m = ZIP_LINE_RE.match(line)
        if not m:
            continue
        city, state = _clean(m.group(2) and m.group(1)), m.group(2)
        # walk back to pick up the street line (and a brand/store line before it)
        parts = []
        for back in range(max(0, i - 2), i):
            prev = lines[back].strip()
            if prev and not _looks_like_label(prev) and len(prev) < 90:
                parts.append(prev)
        full = _clean(" ".join(parts + [line]))
        cs = re.search(r"([A-Za-z][A-Za-z .'\-]+),\s*([A-Z]{2})", line)
        return full, (f"{_clean(cs.group(1))}, {cs.group(2)}" if cs else "")
    return "", ""


def _first_money_after(text: str, keyword_pat: str):
    m = re.search(keyword_pat + r"[^\n$]{0,60}\$\s?([\d,]+(?:\.\d{2})?)", text, re.I)
    return m.group(1).replace(",", "") if m else ""


def _parse_one(segment: str) -> dict:
    lines = [l.rstrip() for l in segment.splitlines()]
    text = "\n".join(lines)
    job = {f: "" for f in FIELD_ORDER}

    labelled = _labelled_values(lines)
    for field, value in labelled.items():
        job[field] = value

    # job id — labelled value may include noise, so prefer a hard pattern match
    import jobid

    job["job_id"] = jobid.find(labelled.get("job_id", "")) or jobid.find(text)

    # money
    nte = _first_money_after(text, r"not\s*to\s*exceed|\bNTE\b")
    if not nte:
        nte = re.sub(r"[^\d.]", "", MONEY_RE.search(labelled.get("nte", "")).group(1)) \
            if MONEY_RE.search(labelled.get("nte", "")) else ""
    if not nte:
        amounts = [float(a.replace(",", "")) for a in MONEY_RE.findall(text)]
        if amounts:
            nte = f"{max(amounts):.2f}"
    job["nte"] = nte

    # address / city
    addr, city = _address_block(lines)
    if addr and (len(addr) > len(job.get("address", ""))):
        job["address"] = addr
    if not job.get("city"):
        job["city"] = city or ""
    if not job.get("city") and job.get("address"):
        cs = CITY_ST_RE.search(job["address"])
        if cs:
            job["city"] = f"{_clean(cs.group(1))}, {cs.group(2)}"

    # deadline — prefer a labelled due date, else first date near a due-ish word
    if job.get("deadline"):
        d = DATE_RE.search(job["deadline"])
        job["deadline"] = d.group(1) if d else job["deadline"]
    else:
        m = re.search(r"(?:due|complete\s*by|expires?|expiration|required\s*by|eta)"
                      r"[^\n]{0,40}?" + DATE_RE.pattern, text, re.I)
        if m:
            job["deadline"] = m.group(1)

    # phones — first two in the document, in order
    phones = PHONE_RE.findall(text)
    if phones:
        job["handyman_phone"] = phones[0]
    if len(phones) > 1:
        job["assignee_phone"] = phones[1]

    # dispatch platform
    low = text.lower()
    if not job.get("company"):
        for p in PLATFORMS:
            if p in low:
                job["company"] = p
                break

    # scope of work — trim to something readable
    if job.get("sow"):
        job["sow"] = _clean(job["sow"])[:1200]

    return job


def parse_jobs(text: str) -> list:
    """Split multi-job documents on job-number anchors, then parse each part."""
    if not text or len(text.strip()) < 20:
        return []
    anchors = [m.start() for m in JOB_ID_RE.finditer(text)]
    # de-duplicate anchors that belong to the same job (same id repeated in a header)
    segments = []
    if len(anchors) <= 1:
        segments = [text]
    else:
        ids_seen, cuts = set(), []
        for pos in anchors:
            jid = JOB_ID_RE.search(text[pos:pos + 40]).group(1).upper().replace(" ", "-")
            if jid not in ids_seen:
                ids_seen.add(jid)
                cuts.append(pos)
        if len(cuts) <= 1:
            segments = [text]
        else:
            starts = [max(0, cuts[0] - 400)] + cuts[1:]
            for i, s in enumerate(starts):
                e = starts[i + 1] if i + 1 < len(starts) else len(text)
                segments.append(text[s:e])

    jobs = []
    for seg in segments:
        job = _parse_one(seg)
        if any(job.get(f) for f in ("job_id", "sow", "address", "nte")):
            jobs.append(job)
    return jobs


def parse_pdf(data: bytes) -> list:
    return parse_jobs(pdf_text(data))
