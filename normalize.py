"""Cleans up extracted values and reports validation warnings per row."""
import re
from datetime import datetime

from fields import FIELD_ORDER, REQUIRED, MONEY_FIELDS, DATE_FIELDS, PHONE_FIELDS, labels

_LABELS = labels()

_DATE_FORMATS = [
    "%b %d, %Y", "%B %d, %Y", "%b %d %Y", "%B %d %Y",
    "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y",
    "%Y-%m-%d", "%d %b %Y", "%d %B %Y", "%b %d", "%B %d",
]


def _norm_money(value: str):
    s = value.replace("$", "").replace(",", "").strip()
    if not s:
        return "", None
    try:
        n = float(s)
        return (f"{n:.2f}".rstrip("0").rstrip(".") if n != int(n) else str(int(n))), None
    except ValueError:
        return value, "not a number"


def _norm_date(value: str):
    s = value.strip().rstrip(",")
    for fmt in _DATE_FORMATS:
        try:
            d = datetime.strptime(s, fmt)
            if d.year == 1900:  # format without a year
                d = d.replace(year=datetime.now().year)
            return f"{d:%b} {d.day}, {d.year}", None
        except ValueError:
            continue
    return value, "unrecognized date"


def _norm_phone(value: str):
    digits = re.sub(r"\D", "", value)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}", None
    return value, None  # leave N/A etc. untouched


def normalize_row(raw: dict) -> dict:
    """Returns {fields..., _warnings: [..]} with cleaned values."""
    row, warnings = {}, []
    for field in FIELD_ORDER:
        value = raw.get(field)
        value = "" if value is None else str(value).strip()
        if value:
            if field in MONEY_FIELDS:
                value, w = _norm_money(value)
            elif field in DATE_FIELDS:
                value, w = _norm_date(value)
            elif field in PHONE_FIELDS:
                value, w = _norm_phone(value)
            else:
                w = None
            if w:
                warnings.append(f"{_LABELS[field]}: {w}")
        row[field] = value
    for field in REQUIRED:
        if not row.get(field):
            warnings.append(f"{_LABELS[field]} is missing")
    jid = row.get("job_id", "")
    if jid and not re.match(r"^[A-Za-z]{2,4}-?\w", jid):
        warnings.append("Job ID looks unusual")
    row["_warnings"] = warnings
    return row
