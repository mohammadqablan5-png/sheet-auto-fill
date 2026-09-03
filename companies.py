"""The dispatch companies the reader recognises, editable by the user.

These used to be two hard-coded lists that disagreed with each other, so a
new company meant a code change and a rebuild. The names now live in a small
file beside the app's other user data, seeded from DEFAULTS the first time.

A name is matched allowing flexible spacing, so "SmartRide", "Smart Ride"
and "SMART  RIDE" all resolve to the one spelling written into the sheet.
"""
import json
import os
import re

from resources import user_file

STORE = "companies.json"

# Seeded on first run; the user's saved list wins from then on.
DEFAULTS = [
    "keystone", "SmartRide", "apex", "Kevon", "TrueCraft", "Onpoint", "jous",
    "servicechannel", "corrigo", "fexa", "ecotrak", "facilitysource",
    "sms assist", "lightning",
]


def _path() -> str:
    return user_file(STORE)


def _clean(names) -> list:
    """Trim, drop blanks, and remove repeats without regard to case."""
    out, seen = [], set()
    for n in names or []:
        n = re.sub(r"\s+", " ", str(n or "")).strip()
        if not n or n.lower() in seen:
            continue
        seen.add(n.lower())
        out.append(n)
    return out


def load() -> list:
    try:
        with open(_path(), encoding="utf-8") as fh:
            saved = _clean(json.load(fh))
        if saved:
            return saved
    except Exception:
        pass                      # missing or damaged file falls back to defaults
    return list(DEFAULTS)


def save(names) -> list:
    names = _clean(names)
    with open(_path(), "w", encoding="utf-8") as fh:
        json.dump(names, fh, indent=2)
    return names


def add(name: str) -> list:
    return save(load() + [name])


def remove(name: str) -> list:
    low = re.sub(r"\s+", " ", str(name or "")).strip().lower()
    return save([n for n in load() if n.lower() != low])


def _pattern(name: str) -> str:
    """Match a name however it is spaced or split in the document.

    "SmartRide" is written as one word in some portals and two in others, so
    the word boundary inside the name is treated as optional whitespace.
    """
    parts = []
    for word in str(name).split():
        # split runs like "SmartRide" into "Smart" + "Ride"
        parts += re.findall(r"[A-Z]+(?![a-z])|[A-Z][a-z]*|[a-z]+|\d+", word) or [word]
    if not parts:
        return ""
    body = r"\s*".join(re.escape(p.lower()) for p in parts)
    return rf"(?<![a-z]){body}(?![a-z])"


def patterns() -> list:
    """(compiled pattern, canonical name), longest name first.

    Longest first so a name that contains another - "apex facilities" over
    "apex" - is not shadowed by the shorter one.
    """
    out = []
    for name in sorted(load(), key=lambda n: -len(n)):
        p = _pattern(name)
        if p:
            out.append((re.compile(p, re.I), name))
    return out


def match(text: str):
    """The company named in this text, or None."""
    for pattern, name in patterns():
        if pattern.search(text or ""):
            return name
    return None
