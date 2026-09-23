"""copy_tree() and related filesystem helpers."""

from __future__ import annotations

import shutil
from pathlib import Path

from dichotomise.errors import DestinationExistsError


def copy_tree(source: Path, destination: Path) -> None:
    """Copy everything under `source` into a new folder at `destination`.

    Refuses to run if `destination` already exists, rather than silently
    overwriting or mixing in with whatever is already there.
    """
    if destination.exists():
        raise DestinationExistsError(f"{destination} already exists; refusing to overwrite it")
    shutil.copytree(source, destination)
