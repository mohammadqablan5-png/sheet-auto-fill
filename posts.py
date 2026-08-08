"""Builds the shareable work-order text (for Discord, WhatsApp, email…).

The layout lives in post_template.txt so it can be edited without touching code.
Any line whose placeholders are all empty is dropped, so a job missing a tech or
a note doesn't produce "Tech: —".
"""
import re

from fields import FIELD_ORDER
from resources import ensure_external_copy

PLACEHOLDER_RE = re.compile(r"\{([a-z_]+)\}")

DEFAULT_TEMPLATE = """Work Number
{job_id}

Schedule Date
{deadline}

{address}

Scope
{sow}

Rate
{rates}

NTE
{nte}
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
    """One job -> work-order text.

    The template is read as blocks separated by blank lines. A whole block is
    dropped when it has placeholders and none of them have a value — that way a
    section heading like "Rate" disappears together with its missing values,
    rather than being left stranded above nothing.
    """
    template = template if template is not None else _template()
    values = {f: _display(f, row.get(f, "")) for f in FIELD_ORDER}

    out_blocks = []
    for block in re.split(r"\n\s*\n", template):
        lines = block.splitlines()
        names = [n for line in lines for n in PLACEHOLDER_RE.findall(line)]
        if names and not any(values.get(n) for n in names):
            continue                                  # nothing to say here at all

        kept = []
        for line in lines:
            on_line = PLACEHOLDER_RE.findall(line)
            if on_line and not any(values.get(n) for n in on_line):
                continue                              # this detail is missing
            filled = PLACEHOLDER_RE.sub(lambda m: values.get(m.group(1), ""), line)
            filled = re.sub(r"\s*[—–-]\s*$", "", filled.rstrip())
            filled = re.sub(r":\s*[—–-]\s*", ": ", filled)
            kept.append(filled)

        if any(line.strip() for line in kept):
            out_blocks.append("\n".join(kept).strip("\n"))

    return "\n\n".join(out_blocks).strip() + "\n"


def render_many(rows: list, template: str = None) -> str:
    template = template if template is not None else _template()
    return "\n\n———\n\n".join(render(r, template) for r in rows)
