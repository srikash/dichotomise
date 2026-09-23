"""Stage 2: tar.gz + checksum the untouched, captured source (source/)."""

from __future__ import annotations

from dichotomise.run import Run
from dichotomise.stages.capture import CapturedSubject
from dichotomise.utils.archive import Archive, make_tarball
from dichotomise.utils.text import safe_filename_text


def source_archive(subject: CapturedSubject, run: Run) -> Archive:
    """Archive one captured subject's untouched files, with a checksum sidecar.

    Named <run-timestamp>_<PatientID>_<scan-datetime>_source-archive.tar.gz,
    always from the raw PatientID: the source archive preserves the
    original, unsanitised export regardless of whether --sanitise is used.
    """
    scan_datetime = (
        f"{safe_filename_text(subject.scan_date)}-{safe_filename_text(subject.scan_time)}"
    )
    name = (
        f"{run.timestamp}_{safe_filename_text(subject.subject_id)}_{scan_datetime}"
        "_source-archive.tar.gz"
    )
    archive_path = run.source_archive_dir / name
    return make_tarball(subject.directory, archive_path)
