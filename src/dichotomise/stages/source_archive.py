"""Stage 2: tar.gz + checksum the untouched, captured source (source/)."""

from __future__ import annotations

from pathlib import Path

from dichotomise.run import Run
from dichotomise.utils.archive import Archive, make_tarball
from dichotomise.utils.fs import reject_symlinks


def source_archive(source_dir: Path, run: Run) -> Archive:
    """Archive the complete scanner export before any processing occurs."""
    reject_symlinks(source_dir)
    archive_path = run.source_archive_dir / f"{run.timestamp}_source-export.tar.gz"
    return make_tarball(source_dir, archive_path)
