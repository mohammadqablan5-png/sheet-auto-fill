"""Loads mapping.yaml and exposes the canonical field definitions."""
import yaml

from resources import resource

with open(resource("mapping.yaml"), encoding="utf-8") as f:
    _MAPPING = yaml.safe_load(f)

FIELDS: dict = _MAPPING["fields"]            # field -> definition
FIELD_ORDER: list = list(FIELDS.keys())      # preview / schema order
PHONE_HEADERS: list = [h.lower() for h in _MAPPING.get("phone_headers", [])]

REQUIRED = [f for f, d in FIELDS.items() if d.get("required")]
MONEY_FIELDS = [f for f, d in FIELDS.items() if d.get("money")]
DATE_FIELDS = [f for f, d in FIELDS.items() if d.get("date")]
PHONE_FIELDS = [f for f, d in FIELDS.items() if d.get("phone")]


def labels() -> dict:
    return {f: d.get("label", f) for f, d in FIELDS.items()}


def sheet_synonyms(field: str) -> list:
    return [s.lower() for s in FIELDS[field].get("sheet", [])]


def csv_synonyms(field: str) -> list:
    """All header names accepted for this field when reading a CSV."""
    d = FIELDS[field]
    out = [s.lower() for s in d.get("sheet", [])]
    out += [s.lower() for s in d.get("csv", [])]
    out.append(d.get("label", field).lower())
    out.append(field.replace("_", " "))
    return out
