"""Filesystem helpers: file digests and the symlink check."""

from __future__ import annotations

import hashlib
from collections.abc import MutableMapping
from pathlib import Path

from dichotomise.errors import UnsafeSourceError


def file_digest(path: Path, cache: MutableMapping[Path, str] | None = None) -> str:
    """SHA-256 of the file's raw bytes (equal only for byte-for-byte copies), optionally cached."""
    if cache is not None and path in cache:
        return cache[path]
    with path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    if cache is not None:
        cache[path] = digest
    return digest


def reject_symlinks(source_dir: Path) -> None:
    """Raise UnsafeSourceError when a source tree contains a symbolic link."""
    if source_dir.is_symlink():
        raise UnsafeSourceError(f"{source_dir} is a symlink; refusing to copy it")
    for path in source_dir.rglob("*"):
        if path.is_symlink():
            raise UnsafeSourceError(f"{path} is a symlink; refusing to copy the source directory")
