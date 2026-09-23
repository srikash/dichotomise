"""Stage 7: independently re-verify the output tree, then tar.gz + checksum it (archives/)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dichotomise.errors import FinaliseVerificationError, NotDicomError
from dichotomise.pydcm.read import read_metadata
from dichotomise.run import Run
from dichotomise.stages.capture import CapturedSubject
from dichotomise.stages.rectify import RectifyResult
from dichotomise.stages.sanitise import SanitiseResult
from dichotomise.utils.archive import Archive, make_tarball
from dichotomise.utils.text import safe_filename_text


@dataclass(frozen=True)
class FinaliseResult:
    """The verified, archived, final output for one subject."""

    subject: CapturedSubject
    subject_label: str
    archive: Archive


def _verify_output_tree(expected_file_count: int, output_dir: Path) -> None:
    """Independently re-check the finished output tree before it is archived.

    This deliberately re-reads the output tree from disk rather than trusting
    the file list the earlier stages produced, so that corruption introduced
    by a copy or rename step (a truncated file, a file that silently failed
    to write) is caught here rather than archived as if it were correct.
    """
    found_files = sorted(p for p in output_dir.rglob("*") if p.is_file())
    if len(found_files) != expected_file_count:
        raise FinaliseVerificationError(
            f"Expected {expected_file_count} file(s) in the finished output, "
            f"but found {len(found_files)} in {output_dir}"
        )
    for path in found_files:
        try:
            read_metadata(path)
        except NotDicomError as error:
            raise FinaliseVerificationError(
                f"{path} could not be read back after processing; the finished output "
                "may be corrupt"
            ) from error


def finalise(
    rectify_result: RectifyResult,
    run: Run,
    *,
    subject_label: str,
    sanitise_result: SanitiseResult | None = None,
) -> FinaliseResult:
    """Verify the finished output tree, then archive it into `run.archives_dir`.

    Archives the sanitised tree if `--sanitise` was used, otherwise the
    rectified tree. Named with the run's timestamp, `subject_label` (the
    real PatientID, or the replacement label if sanitised), and the scan
    date/time, so the archive is self-describing even if separated from its
    run folder.
    """
    source_dir = sanitise_result.sanitised_dir if sanitise_result else rectify_result.rectified_dir
    expected_count = len(sanitise_result.files) if sanitise_result else len(rectify_result.files)
    _verify_output_tree(expected_count, source_dir)

    subject = rectify_result.subject
    scan_datetime = (
        f"{safe_filename_text(subject.scan_date)}-{safe_filename_text(subject.scan_time)}"
    )
    name = (
        f"{run.timestamp}_{safe_filename_text(subject_label)}_{scan_datetime}"
        "_dichotomised-archive.tar.gz"
    )
    archive_path = run.archives_dir / name
    archive = make_tarball(source_dir, archive_path)

    return FinaliseResult(subject=subject, subject_label=subject_label, archive=archive)
