"""Recognising work-order numbers.

Most are "JOB-260729-23617", but dispatchers use their own prefixes too — the
spreadsheet contains "NC-260807-0281". The portal page also prints other IDs of
the same shape that are *not* the work order (a visit is "VST-260729-7250"), so
those prefixes are excluded rather than matched by luck of ordering.
"""
import re

# <letters>-<6 digits>-<digits>, e.g. JOB-260729-23617 / NC-260807-0281
PREFIXED_RE = re.compile(r"\b([A-Za-z]{2,4})-(\d{5,6})-(\d{3,6})\b")
JOB_RE = re.compile(r"\b(JOB[-\s]?\d{5,6}[-\s]?\d{3,6})\b", re.I)
WO_RE = re.compile(r"\b(WO[-#\s]?\d{4,}|W/?O\s*#?\s*\d{4,})\b", re.I)

# Same shape, different meaning — never a work-order number.
NOT_WORK_ORDERS = {"VST", "INV", "PO", "REF", "QTE"}


def normalise(value: str) -> str:
    return re.sub(r"\s+", "-", (value or "").strip()).upper()


def find(text: str) -> str:
    """The work-order number in a blob of text, or ''."""
    if not text:
        return ""

    m = JOB_RE.search(text)                      # the common case wins outright
    if m:
        return normalise(m.group(1))

    for m in PREFIXED_RE.finditer(text):         # other dispatchers' prefixes
        if m.group(1).upper() not in NOT_WORK_ORDERS:
            return normalise(m.group(0))

    m = WO_RE.search(text)
    return normalise(m.group(1)) if m else ""


def looks_like(value: str) -> bool:
    """True for a cell/label that is itself a work-order number."""
    value = (value or "").strip()
    if not value:
        return False
    m = PREFIXED_RE.match(value)
    if m and m.group(1).upper() in NOT_WORK_ORDERS:
        return False
    return bool(m or JOB_RE.match(value) or WO_RE.match(value))
