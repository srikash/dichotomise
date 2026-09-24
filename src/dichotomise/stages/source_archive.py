"""Stage 2: tar.gz + checksum the untouched, captured source (source/)."""

from __future__ import annotations

from pathlib import Path

from dichotomise.run import Run
from dichotomise.stages.capture import CapturedSubject
from dichotomise.utils.archive import Archive, make_tarball
from dichotomise.utils.fs import reject_symlinks
from dichotomise.utils.text import safe_filename_text


def source_archive(source_dir: Path | CapturedSubject, run: Run) -> Archive:
    """Archive a complete export, or one captured study for legacy callers."""
    if isinstance(source_dir, CapturedSubject):
        archive_stem = (
            f"{safe_filename_text(source_dir.scan_date)}-"
            f"{safe_filename_text(source_dir.scan_time)}_"
            f"{safe_filename_text(source_dir.patient_name)}_"
            f"{safe_filename_text(source_dir.subject_id)}_source-archive_{run.timestamp}"
        )
        archive_path = run.source_archive_dir / f"{archive_stem}.tar.gz"
        return make_tarball(source_dir.directory, archive_path)
    reject_symlinks(source_dir)
    archive_path = run.source_archive_dir / f"{run.timestamp}_source-export.tar.gz"
    return make_tarball(source_dir, archive_path)
