"""safe_filename_text() and natural_sort_key(): text helpers for file/folder names."""

from __future__ import annotations

import re

_UNSAFE_CHARACTERS = re.compile(r"[^A-Za-z0-9._-]+")
_DIGIT_RUN = re.compile(r"\d+")


def safe_filename_text(value: str) -> str:
    """Replace anything unsafe for a filename with "_"; "NA" if nothing is left."""
    cleaned = _UNSAFE_CHARACTERS.sub("_", value).strip("_")
    return cleaned or "NA"


def natural_sort_key(value: str) -> str:
    """Return a sort key that orders embedded numbers numerically, not lexically.

    Scanner export folders are usually suffixed with the series number
    (`..._6_MR`, `..._29_MR`), which a plain alphabetical sort gets wrong
    (`_29_MR` before `_6_MR`). Zero-padding every digit run makes a plain
    string sort agree with a numeric one, without assuming any fixed suffix
    shape; a value with no digits at all just sorts alphabetically.
    """
    return _DIGIT_RUN.sub(lambda match: match.group().zfill(10), value)
