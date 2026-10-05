"""Stage 2: tar.gz + checksum the untouched, original source files (archives/).

Archives each subject's files straight from the source directory, before
anything else is read from or written to them -- so a copy made by a later
stage can never silently diverge from what this archive preserves.
"""

from __future__ import annotations

from pathlib import Path
from secrets import token_hex

from dichotomise.run import Run
from dichotomise.stages.capture import CapturedSubject
from dichotomise.utils.archive import Archive, make_tarball_from_files
from dichotomise.utils.text import safe_filename_text


def _study_archive_path(subject: CapturedSubject, run: Run) -> Path:
    """Return an unused, concise source-archive path for one captured study."""
    prefix = safe_filename_text(subject.subject_id)
    for _ in range(100):
        archive_stem = f"{prefix}_{token_hex(3)}_source-archive_{run.timestamp}"
        archive_path = run.archives_dir / f"{archive_stem}.tar.gz"
        checksum_path = run.archives_dir / f"{archive_stem}.sha256"
        if not archive_path.exists() and not checksum_path.exists():
            return archive_path
    raise FileExistsError(f"Could not create a unique source archive name for {subject.subject_id}")


def source_archive(subject: CapturedSubject, run: Run) -> Archive:
    """Archive one subject's original source files, by their path under `source_root`."""
    paths = [metadata.path for metadata in subject.files]
    return make_tarball_from_files(paths, subject.source_root, _study_archive_path(subject, run))
