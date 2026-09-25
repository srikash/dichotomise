from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from dichotomise.stages.audit import audit, audit_directory
from dichotomise.stages.capture import CapturedSubject


def _subject(directory: Path) -> CapturedSubject:
    return CapturedSubject(
        subject_id="sub-01",
        patient_name="Doe^Jane^19900101",
        study_instance_uid="study-a",
        scan_date="20260101",
        scan_time="120000",
        directory=directory,
    )


def test_audit_flags_duplicate_and_misfiled_files(
    tmp_path: Path, make_dicom_file: Callable[..., Path]
) -> None:
    capture_dir = tmp_path / "capture"

    # 021-DWI: files 1 and 2 share content (a duplicate); file 3 is distinct.
    make_dicom_file(
        capture_dir / "021-DWI" / "1.dcm",
        StudyInstanceUID="study-a",
        SeriesInstanceUID="series-dwi",
        SeriesNumber=21,
        ProtocolName="DWI",
        InstanceNumber=1,
    )
    make_dicom_file(
        capture_dir / "021-DWI" / "2.dcm",
        StudyInstanceUID="study-a",
        SeriesInstanceUID="series-dwi",
        SeriesNumber=21,
        ProtocolName="DWI",
        InstanceNumber=1,
    )
    make_dicom_file(
        capture_dir / "021-DWI" / "3.dcm",
        StudyInstanceUID="study-a",
        SeriesInstanceUID="series-dwi",
        SeriesNumber=21,
        ProtocolName="DWI",
        InstanceNumber=2,
    )

    # 022-fMRI: files 1 and 2 agree on the folder's series; file 3 disagrees (misfiled).
    make_dicom_file(
        capture_dir / "022-fMRI" / "1.dcm",
        SeriesInstanceUID="series-fmri",
        SeriesNumber=22,
        ProtocolName="fMRI",
        InstanceNumber=1,
    )
    make_dicom_file(
        capture_dir / "022-fMRI" / "2.dcm",
        SeriesInstanceUID="series-fmri",
        SeriesNumber=22,
        ProtocolName="fMRI",
        InstanceNumber=2,
    )
    make_dicom_file(
        capture_dir / "022-fMRI" / "3.dcm",
        SeriesInstanceUID="series-other",
        SeriesNumber=99,
        ProtocolName="other",
        InstanceNumber=1,
    )

    result = audit(_subject(capture_dir))

    assert len(result.files) == 6
    flagged_duplicate = {f.metadata.path.name for f in result.files if f.is_duplicate}
    ok_files = [f for f in result.files if not f.is_duplicate and not f.is_misfiled]

    assert flagged_duplicate == {"2.dcm"}
    assert len(ok_files) == 4
    misfiled_paths = {f.metadata.path for f in result.files if f.is_misfiled}
    assert misfiled_paths == {capture_dir / "022-fMRI" / "3.dcm"}


def test_audit_directory_checks_source_files_in_place(
    tmp_path: Path, make_dicom_file: Callable[..., Path]
) -> None:
    source_dir = tmp_path / "source"
    dicom_file = make_dicom_file(source_dir / "series" / "1.dcm", PatientID="scanner-01")

    result = audit_directory(source_dir)

    assert result.subject.directory == source_dir
    assert [file.metadata.path for file in result.files] == [dicom_file]
    assert list(source_dir.rglob("*")) == [source_dir / "series", dicom_file]
