"""safe_filename_text(): make arbitrary text safe to use in a file or folder name."""

from __future__ import annotations

import re

_UNSAFE_CHARACTERS = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename_text(value: str) -> str:
    """Replace anything unsafe for a filename with "_"; "NA" if nothing is left."""
    cleaned = _UNSAFE_CHARACTERS.sub("_", value).strip("_")
    return cleaned or "NA"
