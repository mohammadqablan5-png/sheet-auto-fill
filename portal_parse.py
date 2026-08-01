"""Reads job details from OCR'd work-order portal pages.

The portal lays fields out as a label with its value directly underneath, so
values are located by position rather than by scraping a flattened text dump.
That survives OCR quirks (missing spaces, multi-column pages) far better.

Pages belonging to the same job are merged; a page carrying a different work
number starts a new job.
"""
import re

from fields import FIELD_ORDER

# ------------------------------------------------------------------ helpers

JOB_ID_RE = re.compile(r"\b(JOB[-\s]?\d{5,6}[-\s]?\d{3,6})\b", re.I)
MONEY_RE = re.compile(r"\$\s?([\d,]+(?:\.\d{2})?)")
PHONE_RE = re.compile(r"(?:\+1\s*)?(\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4})")
DATE_RE = re.compile(
    r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*\d{1,2}\s*,?\s*\d{4})",
    re.I)
CITY_ST_ZIP_RE = re.compile(r"([A-Za-z][A-Za-z .'\-]{2,}),\s*([A-Z]{2})\.?\s+(\d{5})")

STATUSES = ["on hold", "completed", "complete", "secured", "in progress", "scheduled",
            "cancelled", "canceled", "dispatched", "open", "assigned", "pending"]

PLATFORM_PATTERNS = [
    (r"keystone", "keystone"),
    (r"smart\s*ride", "SmartRide"),
    (r"\bapex\b", "apex"),
    (r"\bjous\b", "jous"),
]


def _norm(s: str) -> str:
    """Label key: letters only, with OCR look-alikes folded together.

    OCR routinely confuses I/l/1/| and O/0, so both the label text and the
    lookup keys are folded to the same representative character.
    """
    s = (s or "").lower()
    s = re.sub(r"[l1|!]", "i", s)
    s = s.replace("0", "o")
    return re.sub(r"[^a-z]", "", s)


def _fix_digits(s: str) -> str:
    """Repair letter/digit confusion inside numbers, e.g. '31l Main' -> '311 Main'."""
    s = re.sub(r"(?<=\d)[lI|](?=\d)", "1", s)
    s = re.sub(r"(?<=\d)[lI|](?=\s)", "1", s)
    s = re.sub(r"(?<=\d)[oO](?=\d)", "0", s)
    return s


# label key -> canonical meaning (matched against _norm of the box text)
LABELS = {
    "worknumber": "job_id",
    "jobnumber": "job_id",
    "workordernumber": "job_id",
    "scheduledate": "deadline",
    "scheduledatetime": "deadline",
    "duedate": "deadline",
    "completeby": "deadline",
    "nte": "nte",
    "nteamount": "nte",
    "nottoexceed": "nte",
    "scope": "sow",
    "scopeofwork": "sow",
    "description": "sow",
    "specialinstructions": "special",
    "title": "title",
    "dmgcontact": "assignee",
    "contact": "assignee",
    "sitecontact": "assignee",
    "phonenumber": "assignee_phone",
    "primarytechnician": "primary_tech",
    "regulartechnician": "primary_tech",
    "serviceline": "service_line",
    "servicetype": "service_type",
    "lastupdatedon": "_ignore",
    "createdon": "_ignore",
    "emailaddress": "_ignore",
    "assignedtechnicians": "_ignore",
    "requirements": "_ignore",
    "task": "_ignore",
    "status": "_ignore",
    "priority": "_ignore",
    "finishby": "_ignore",
    "visitnumber": "_ignore",
    "details": "_ignore",
    "timeline": "_ignore",
    "jobprogress": "_ignore",
    "visitsandinvoice": "_ignore",
    "workdetails": "_ignore",
    "attachments": "_ignore",
    "spot": "_ignore",
    "phone": "_ignore",
}

# Both sides of the comparison must go through the same folding, or keys
# containing l/i/1/o never match their OCR'd text.
LABELS = {_norm(k): v for k, v in LABELS.items()}

# label keys that terminate a multi-line paragraph
_STOP_KEYS = set(LABELS.keys())


def _is_label(box) -> bool:
    return _norm(box["text"]) in _STOP_KEYS


def _find_labels(boxes: list) -> list:
    """-> [(box, meaning)] for every box that is a known field label."""
    out = []
    for b in boxes:
        meaning = LABELS.get(_norm(b["text"]))
        if meaning:
            out.append((b, meaning))
    return out


def _value_below(boxes: list, label, max_lines: int = 1):
    """Nearest box(es) directly under a label, left-aligned with it."""
    lh = max(label["h"], 8)
    picks = []
    for b in boxes:
        if b is label or b["y0"] <= label["y0"]:
            continue
        if b["y0"] - label["y1"] > lh * 2.2:
            continue
        # left edges line up, or the boxes overlap horizontally
        aligned = abs(b["x0"] - label["x0"]) <= lh * 1.2
        overlap = min(b["x1"], label["x1"]) - max(b["x0"], label["x0"]) > 0
        if aligned or overlap:
            picks.append(b)
    picks.sort(key=lambda b: (b["y0"], b["x0"]))
    if not picks:
        return ""
    return " ".join(p["text"] for p in picks[:max_lines])


def _paragraph_below(boxes: list, label) -> str:
    """Multi-line block under a label, stopping at the next label or a gap."""
    lh = max(label["h"], 8)
    below = [b for b in boxes
             if b["y0"] > label["y0"]
             and abs(b["x0"] - label["x0"]) <= lh * 3
             and b["x1"] > label["x0"]]
    below.sort(key=lambda b: b["y0"])
    parts, prev = [], label
    for b in below:
        if b["y0"] - prev["y1"] > lh * 2.4:
            break
        if _is_label(b) and b is not label:
            break
        parts.append(b["text"])
        prev = b
    return " ".join(parts).strip()


def _address(boxes: list) -> tuple:
    """Store/site address: the line carrying 'City, ST ZIP', plus the line above."""
    for b in sorted(boxes, key=lambda b: b["y0"]):
        m = CITY_ST_ZIP_RE.search(b["text"])
        if not m:
            continue
        lh = max(b["h"], 8)
        above = [a for a in boxes
                 if a["y1"] <= b["y0"] and b["y0"] - a["y1"] < lh * 1.8
                 and abs(a["x0"] - b["x0"]) <= lh * 3]
        above.sort(key=lambda a: a["y0"])
        head = above[-1]["text"] if above and not _is_label(above[-1]) else ""
        full = f"{head} {b['text']}".strip() if head else b["text"]
        city = f"{m.group(1).strip()}, {m.group(2)}"
        return re.sub(r"\s{2,}", " ", full), city
    return "", ""


# ------------------------------------------------------------------ per page


def parse_page(boxes: list) -> dict:
    found = {f: "" for f in FIELD_ORDER}
    extra = {}
    if not boxes:
        return found

    all_text = "\n".join(b["text"] for b in boxes)

    for label, meaning in _find_labels(boxes):
        if meaning == "_ignore":
            continue
        if meaning in ("sow", "special"):
            value = _paragraph_below(boxes, label)
        else:
            value = _value_below(boxes, label)
        if not value:
            continue
        if meaning in FIELD_ORDER:
            if not found[meaning]:
                found[meaning] = value
        else:
            extra.setdefault(meaning, value)

    # --- job id: always confirm with the hard pattern (breadcrumb or label)
    m = JOB_ID_RE.search(found.get("job_id", "")) or JOB_ID_RE.search(all_text)
    found["job_id"] = re.sub(r"\s+", "-", m.group(1)).upper() if m else ""

    # --- money
    if found.get("nte"):
        mm = MONEY_RE.search(found["nte"])
        found["nte"] = mm.group(1).replace(",", "") if mm else ""
    if not found.get("nte"):
        mm = re.search(r"nte\b[^$\n]{0,40}\$\s?([\d,]+(?:\.\d{2})?)", all_text, re.I)
        if mm:
            found["nte"] = mm.group(1).replace(",", "")

    # --- deadline: keep the date, drop the time/zone
    if found.get("deadline"):
        dm = DATE_RE.search(found["deadline"])
        if dm:
            found["deadline"] = re.sub(r"\s*,\s*", " ", dm.group(1)).strip()
            found["deadline"] = re.sub(r"^([A-Za-z]+)\s+(\d{1,2})\s+(\d{4})$",
                                       r"\1 \2, \3", found["deadline"])

    # --- assignee phone
    if found.get("assignee_phone"):
        pm = PHONE_RE.search(found["assignee_phone"])
        found["assignee_phone"] = pm.group(1) if pm else ""

    # --- address / city
    addr, city = _address(boxes)
    if addr:
        found["address"] = _fix_digits(addr)
    if city:
        found["city"] = city

    # --- scope, plus the special instructions appended
    sow = found.get("sow", "")
    if not sow and extra.get("title"):
        sow = extra["title"]
    if extra.get("special"):
        sow = (sow + "  Special instructions: " + extra["special"]).strip()
    found["sow"] = re.sub(r"\s{2,}", " ", sow).strip()

    # --- status
    low = all_text.lower()
    for s in STATUSES:
        if re.search(rf"(?<![a-z]){re.escape(s)}(?![a-z])", low):
            found["job_status"] = s.upper() if s == "on hold" else s.title()
            break

    # --- dispatch platform (appears in the timeline, e.g. "KEYSTONE ... awarded")
    for pat, name in PLATFORM_PATTERNS:
        if re.search(pat, low):
            found["company"] = name
            break

    # --- open task becomes an update note (e.g. "Technician Requested - NTE Increase")
    tm = re.search(r"(technician requested[^\n]{0,40}|nte\s*increase)", all_text, re.I)
    if tm:
        found["updates"] = re.sub(r"\s{2,}", " ", tm.group(1)).strip()

    return found


# ------------------------------------------------------------------ document


def _merge(base: dict, new: dict) -> dict:
    for f in FIELD_ORDER:
        if not base.get(f) and new.get(f):
            base[f] = new[f]
        elif f == "sow" and new.get(f) and len(new[f]) > len(base.get(f, "")):
            base[f] = new[f]
    return base


def parse_pages(pages: list) -> list:
    """Merge pages of the same job; a new work number starts a new job."""
    jobs, current, current_id = [], None, None
    for boxes in pages:
        page = parse_page(boxes)
        pid = page.get("job_id") or ""
        if current is None:
            current, current_id = page, pid
        elif pid and current_id and pid != current_id:
            jobs.append(current)
            current, current_id = page, pid
        else:
            current = _merge(current, page)
            current_id = current_id or pid
    if current:
        jobs.append(current)
    return [j for j in jobs if any(j.get(f) for f in ("job_id", "sow", "address", "nte"))]
