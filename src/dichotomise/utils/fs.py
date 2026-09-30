"""copy_tree() and related filesystem helpers."""

from __future__ import annotations

import shutil
from pathlib import Path

from dichotomise.errors import DestinationExistsError, UnsafeSourceError


def copy_tree(source: Path, destination: Path) -> None:
    """Copy everything under `source` into a new folder at `destination`.

    Refuses to run if `destination` already exists, rather than silently
    overwriting or mixing in with whatever is already there.
    """
    if destination.exists():
        raise DestinationExistsError(f"{destination} already exists; refusing to overwrite it")
    shutil.copytree(source, destination)


def reject_symlinks(source_dir: Path) -> None:
    """Raise UnsafeSourceError when a source tree contains a symbolic link."""
    if source_dir.is_symlink():
        raise UnsafeSourceError(f"{source_dir} is a symlink; refusing to copy it")
    for path in source_dir.rglob("*"):
        if path.is_symlink():
            raise UnsafeSourceError(f"{path} is a symlink; refusing to copy the source directory")
