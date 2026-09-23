from __future__ import annotations

from pathlib import Path

from dichotomise.stages.audit import AuditedFile, AuditResult
from dichotomise.stages.capture import CapturedSubject
from dichotomise.stages.sift import sift


def _metadata(path: Path, **overrides: object):
    from dichotomise.pydcm.read import DicomMetadata

    defaults: dict[str, object] = {
        "path": path,
        "patient_id": "sub-01",
        "patient_name": "Doe^Jane^19900101",
        "study_instance_uid": "study-a",
        "series_instance_uid": "series-a",
        "sop_instance_uid": "sop-1",
        "series_number": 21,
        "series_description": "diffusion",
        "protocol_name": "DWI",
        "instance_number": 1,
        "echo_number": 1,
        "study_date": "20260101",
        "study_time": "120000",
    }
    defaults.update(overrides)
    return DicomMetadata(**defaults)  # type: ignore[arg-type]


def test_sift_copies_files_into_retained_and_review_folders(tmp_path: Path) -> None:
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
        directory=capture_dir,
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

    assert [m.path.name for m in result.retained] == ["1.dcm"]
    assert (result.retained_dir / "021-DWI" / "1.dcm").read_bytes() == b"ok file"

    review_by_reason = {r.reason: r.metadata.path.name for r in result.review}
    assert review_by_reason == {"duplicate": "2.dcm", "misfiled": "3.dcm"}
    assert (result.review_dir / "021-DWI" / "2.dcm").read_bytes() == b"duplicate file"
    assert (result.review_dir / "021-DWI" / "3.dcm").read_bytes() == b"misfiled file"

    # Retained metadata points at the new, retained-folder location.
    assert result.retained[0].path == result.retained_dir / "021-DWI" / "1.dcm"
