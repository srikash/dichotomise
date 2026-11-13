"""The sift stage: the split into retained and review files."""

from __future__ import annotations

from pathlib import Path

from helpers import make_metadata as _metadata

from dichotomise.stages.audit import AuditedFile, AuditResult
from dichotomise.stages.capture import CapturedSubject
from dichotomise.stages.sift import sift


def test_sift_splits_files_into_retained_and_review_without_copying(tmp_path: Path) -> None:
    capture_dir = tmp_path / "capture"
    (capture_dir / "021-DWI").mkdir(parents=True)
    ok_path = capture_dir / "021-DWI" / "1.dcm"
    ok_path.write_bytes(b"ok file")
    duplicate_path = capture_dir / "021-DWI" / "2.dcm"
    duplicate_path.write_bytes(b"duplicate file")
    misfiled_path = capture_dir / "021-DWI" / "3.dcm"
    misfiled_path.write_bytes(b"misfiled file")

    subject = CapturedSubject(
        subject_id="sub-01",
        patient_name="Doe^Jane^19900101",
        study_instance_uid="study-a",
        scan_date="20260101",
        scan_time="120000",
        files=[],
        source_root=capture_dir,
        working_dir=tmp_path / "working" / "sub-01",
    )
    audit_result = AuditResult(
        subject=subject,
        files=[
            AuditedFile(
                _metadata(ok_path, instance_number=1), is_duplicate=False, is_misfiled=False
            ),
            AuditedFile(
                _metadata(duplicate_path, instance_number=1), is_duplicate=True, is_misfiled=False
            ),
            AuditedFile(
                _metadata(misfiled_path, instance_number=2), is_duplicate=False, is_misfiled=True
            ),
        ],
    )

    result = sift(audit_result)

    # Retained/review are a logical split: paths are untouched originals.
    assert [m.path for m in result.retained] == [ok_path]
    assert ok_path.read_bytes() == b"ok file"

    review_by_reason = {r.reason: r.metadata.path for r in result.review}
    assert review_by_reason == {"duplicate": duplicate_path, "misfiled": misfiled_path}
    assert duplicate_path.read_bytes() == b"duplicate file"
    assert misfiled_path.read_bytes() == b"misfiled file"
