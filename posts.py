"""Builds the shareable work-order text (for Discord, WhatsApp, email…).

The layout lives in post_template.txt so it can be edited without touching code.
Any line whose placeholders are all empty is dropped, so a job missing a tech or
a note doesn't produce "Tech: —".
"""
import re

from fields import FIELD_ORDER
from resources import ensure_external_copy

PLACEHOLDER_RE = re.compile(r"\{([a-z_]+)\}")

DEFAULT_TEMPLATE = """**NEW WORK ORDER — {job_id}**

**Location:** {address}
**Complete by:** {deadline}
**NTE:** {nte}
**Pay:** {rates}
**Contact:** {assignee} — {assignee_phone}

**Scope of work**
{sow}
"""


def _template() -> str:
    try:
        with open(ensure_external_copy("post_template.txt"), encoding="utf-8") as fh:
            text = fh.read()
        return text if text.strip() else DEFAULT_TEMPLATE
    except OSError:
        return DEFAULT_TEMPLATE


def _display(field: str, value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if field in ("nte", "cap", "cost", "payout") and not value.startswith("$"):
        try:
            amount = float(value)
            return f"${amount:,.2f}"
        except ValueError:
            return value
    return value


def render(row: dict, template: str = None) -> str:
    """One job -> post text. Lines with no usable values are removed."""
    template = template if template is not None else _template()
    values = {f: _display(f, row.get(f, "")) for f in FIELD_ORDER}

    out_lines = []
    for line in template.splitlines():
        names = PLACEHOLDER_RE.findall(line)
        if names and not any(values.get(n) for n in names):
            continue                      # nothing to say on this line
        filled = PLACEHOLDER_RE.sub(lambda m: values.get(m.group(1), ""), line)
        # tidy separators left dangling by a missing half ("Bob — ")
        filled = re.sub(r"\s*[—–-]\s*$", "", filled.rstrip())
        filled = re.sub(r":\s*[—–-]\s*", ": ", filled)
        out_lines.append(filled)

    text = "\n".join(out_lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def render_many(rows: list, template: str = None) -> str:
    template = template if template is not None else _template()
    return "\n\n———\n\n".join(render(r, template) for r in rows)
