"""Stage 2: tar.gz + checksum the untouched, captured source (source/)."""

from __future__ import annotations

from pathlib import Path
from secrets import token_hex

from dichotomise.run import Run
from dichotomise.stages.capture import CapturedSubject
from dichotomise.utils.archive import Archive, make_tarball
from dichotomise.utils.fs import reject_symlinks
from dichotomise.utils.text import safe_filename_text


def _study_archive_path(subject: CapturedSubject, run: Run) -> Path:
    """Return an unused, concise source-archive path for one captured study."""
    prefix = safe_filename_text(subject.subject_id)
    for _ in range(100):
        archive_stem = f"{prefix}_{token_hex(3)}_source-archive_{run.timestamp}"
        archive_path = run.source_archive_dir / f"{archive_stem}.tar.gz"
        checksum_path = run.source_archive_dir / f"{archive_stem}.sha256"
        if not archive_path.exists() and not checksum_path.exists():
            return archive_path
    raise FileExistsError(f"Could not create a unique source archive name for {subject.subject_id}")


def source_archive(source_dir: Path | CapturedSubject, run: Run) -> Archive:
    """Archive a complete export, or one captured study for legacy callers."""
    if isinstance(source_dir, CapturedSubject):
        return make_tarball(source_dir.directory, _study_archive_path(source_dir, run))
    reject_symlinks(source_dir)
    archive_path = run.source_archive_dir / f"{run.timestamp}_source-export.tar.gz"
    return make_tarball(source_dir, archive_path)
