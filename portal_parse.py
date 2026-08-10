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

import jobid
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


def _clean_ws(s: str) -> str:
    return re.sub(r"\s{2,}", " ", (s or "")).strip()


def _money(s: str) -> str:
    """'$38.00 per hour' -> '$38'   ·   '$22.50' -> '$22.50'"""
    m = MONEY_RE.search(s or "")
    if not m:
        return (s or "").strip()
    amount = m.group(1).replace(",", "")
    if amount.endswith(".00"):
        amount = amount[:-3]
    return "$" + amount


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
    "primarytechnician": "primary_tech_label",
    # "Regular Technician" appears twice in the portal: under Assigned Technicians
    # (a person) and under Rate (a dollar amount). It gets its own key so it can
    # never be shadowed by "Primary Technician", and the money check decides
    # which of the two it was.
    "regulartechnician": "regular_tech",
    "helpertechnician": "rate_helper",
    "trip": "rate_trip",
    "rate": "_ignore",
    "phone": "tech_phone_label",
    "serviceline": "service_line",
    "servicetype": "service_type_label",
    "lastupdatedon": "_ignore",
    "createdon": "_ignore",
    "emailaddress": "contact_email_label",
    "assignedtechnicians": "_ignore",
    "requirements": "requirements_label",
    "task": "task_label",
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


def _items_below(boxes: list, label, gap_mult: float = 5.0, limit: int = 12) -> list:
    """List entries stacked under a label (open tasks, requirements…).

    Rows in these lists sit further apart than the lines of a paragraph, so the
    tighter paragraph gap would stop after the first entry.
    """
    lh = max(label["h"], 4)
    below = [b for b in boxes
             if b["y0"] > label["y1"]
             and abs(b["x0"] - label["x0"]) <= lh * 1.5]
    below.sort(key=lambda b: b["y0"])
    items, prev_y = [], label["y1"]
    for b in below:
        if _is_label(b):
            break                       # the next section starts here
        if b["y0"] - prev_y > lh * gap_mult:
            break
        items.append(b["text"].strip())
        prev_y = b["y1"]
        if len(items) >= limit:
            break
    return items


def _value_right(boxes: list, label):
    """Value printed beside a label instead of under it (Assigned Technicians)."""
    picks = []
    for b in boxes:
        if b is label or b["x0"] < label["x1"]:
            continue
        overlap = min(b["y1"], label["y1"]) - max(b["y0"], label["y0"])
        if overlap > 0 and not _is_label(b):
            picks.append(b)
    picks.sort(key=lambda b: b["x0"])
    return picks[0]["text"].strip() if picks else ""


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


# A store line looks like "Walgreen's (13632) - 311 N Main St" or "Target (0366) - …"
STORE_LINE_RE = re.compile(r"^(.{2,60}?)\s*\(\s*[\w-]{2,12}\s*\)\s*(?:[-–—]\s*(.+))?$")


def _address(boxes: list) -> tuple:
    """Store/site address plus 'City, ST'.

    The portal prints the store name and number on one line ("Target (0366) -
    131 W Reynolds Rd") and the postal address underneath. Both are wanted, so
    the store line is searched for a few lines above the City/ST/ZIP line — with
    a looser tolerance than plain adjacency, because OCR row heights vary and the
    map pin icon can shift the left edge.
    """
    for b in sorted(boxes, key=lambda b: b["y0"]):
        m = CITY_ST_ZIP_RE.search(b["text"])
        if not m:
            continue
        lh = max(b["h"], 8)

        candidates = [a for a in boxes
                      if a is not b
                      and a["y1"] <= b["y0"] + lh * 0.4
                      and b["y0"] - a["y1"] < lh * 3.5
                      and abs(a["x0"] - b["x0"]) <= lh * 6
                      and not _is_label(a)]
        candidates.sort(key=lambda a: a["y0"])

        # prefer the closest line that actually names a store
        head = ""
        for a in reversed(candidates):
            if STORE_LINE_RE.match(a["text"].strip()):
                head = a["text"].strip()
                break
        if not head and candidates:
            nearest = candidates[-1]
            if b["y0"] - nearest["y1"] < lh * 1.8:
                head = nearest["text"].strip()

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
        if meaning in ("task_label", "requirements_label"):
            items = _items_below(boxes, label)
            if items:
                extra.setdefault(meaning, []).append("\n".join(items))
            continue
        if meaning == "tech_phone_label":
            beside = _value_right(boxes, label)
            if beside:
                extra.setdefault(meaning, []).append(beside)
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
            # Keep every occurrence. "Regular Technician" appears twice on the
            # page — once naming a person, once naming a rate — so collapsing to
            # the first match silently loses whichever comes second.
            extra.setdefault(meaning, []).append(value)

    # --- job id: confirm the labelled value, else search the page
    found["job_id"] = jobid.find(found.get("job_id", "")) or jobid.find(all_text)

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

    # --- extra detail kept for the work-order text (never written to the sheet)
    def first(meaning: str) -> str:
        values = extra.get(meaning) or []
        return values[0] if values else ""

    found["title"] = found.get("title") or first("title")
    found["service_type"] = first("service_type_label") or first("service_line")
    found["requirements"] = first("requirements_label")
    found["tasks"] = first("task_label")

    email = first("contact_email_label")
    if "@" in email:
        email = re.sub(r"\s+", "", email)      # the PDF prints it with spaces
    found["contact_email"] = email

    # "Primary Technician" is the person; the same words under Rate are money.
    for meaning in ("primary_tech_label", "regular_tech"):
        if found.get("primary_tech"):
            break
        for value in extra.get(meaning, []):
            if value and not MONEY_RE.search(value):
                found["primary_tech"] = value
                break

    for value in extra.get("tech_phone_label", []):
        if len(re.sub(r"\D", "", value)) >= 10:
            found["primary_tech_phone"] = value
            break

    vm = re.search(r"\bVST-\d{5,6}-\d{3,6}\b", all_text, re.I)
    if vm:
        found["visit"] = vm.group(0).upper()

    jt = re.search(r"((?:Non[- ]?Routine|Routine|Emergency)[^\n]{0,30}Job)", all_text, re.I)
    if jt:
        found["job_type"] = _clean_ws(jt.group(1))

    pn = re.search(r"([^\n]{0,60}(?:checked out|return trip|checked in)[^\n]{0,60})",
                   all_text, re.I)
    if pn:
        found["progress_note"] = _clean_ws(pn.group(1))

    lu = re.search(r"Last Updated On\s*\n?\s*([^\n]{6,60})", all_text, re.I)
    if lu:
        found["last_updated"] = _clean_ws(lu.group(1))

    # Everything the reader saw — so a detail with no field of its own is still
    # available to the work-order text via {page_text}.
    found["page_text"] = all_text.strip()

    # the full check-in window, e.g. "August 07, 2026 from 12:00 AM to 11:30 PM"
    wm = re.search(r"(Check in by [^\n]{6,90})", all_text, re.I)
    if wm:
        found["checkin_window"] = _clean_ws(wm.group(1))

    # --- scope, plus the special instructions appended
    sow = found.get("sow", "")
    if not sow:
        sow = first("title")
    special = first("special")
    if special:
        sow = (sow + "  Special instructions: " + special).strip()
    found["sow"] = re.sub(r"\s{2,}", " ", sow).strip()

    # --- pay rates (Rate section), which the portal lays out in two columns:
    #       Regular Technician    Helper Technician
    #       $35.00 per hour       $18.00 per hour
    #       Trip                  NTE
    #       $22.00                $270.00
    # Each rate is taken from its own label, and only values that are actually
    # money count — "Regular Technician: Omar Ben" is a person, not a rate.
    def money_value(meaning: str) -> str:
        for value in extra.get(meaning, []):
            if MONEY_RE.search(value):
                return value.strip()
        return ""

    # Kept in the portal's own label-above-value shape so the work-order text
    # reads the same way the portal page does.
    lines = []
    for label, meaning in (("Regular Technician", "regular_tech"),
                           ("Helper Technician", "rate_helper"),
                           ("Trip", "rate_trip")):
        value = money_value(meaning)
        if value:
            lines += [label, value]
    if lines:
        found["rates"] = "\n".join(lines)

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
