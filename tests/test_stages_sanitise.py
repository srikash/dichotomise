from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pydicom

from dichotomise.pydcm.relabel import load_policy
from dichotomise.stages.capture import CapturedSubject
from dichotomise.stages.rectify import RectifyResult
from dichotomise.stages.sanitise import sanitise


def _subject(directory: Path) -> CapturedSubject:
    return CapturedSubject(
        subject_id="sub-01",
        patient_name="Doe^Jane^19900101",
        study_instance_uid="study-a",
        scan_date="20260101",
        scan_time="120000",
        directory=directory,
    )


def test_sanitise_applies_the_policy_and_writes_a_new_tree(
    tmp_path: Path, make_dicom_file: Callable[..., Path]
) -> None:
    rectified_dir = tmp_path / "rectify"
    file_a = make_dicom_file(
        rectified_dir / "021-DWI" / "021_series-dwi_0001_e01.dcm",
        PatientID="12345",
        PatientName="Doe^Jane^19900101",
        StudyInstanceUID="study-a",
        InstitutionName="Sunnybrook",
    )

    subject = _subject(tmp_path / "capture")
    from dichotomise.pydcm.read import read_metadata

    rectify_result = RectifyResult(
        subject=subject, rectified_dir=rectified_dir, files=[read_metadata(file_a)]
    )

    result = sanitise(rectify_result, policy=load_policy("standard"), subject_label="sub-0005")

    assert len(result.files) == 1
    sanitised_path = result.files[0]
    assert sanitised_path != file_a
    written = pydicom.dcmread(sanitised_path, force=True)
    assert written.PatientID == "sub-0005"
    assert written.PatientName == "sub-0005"
    assert not hasattr(written, "InstitutionName")
    # The original rectified file is untouched.
    original = pydicom.dcmread(file_a, force=True)
    assert original.PatientID == "12345"


def test_sanitise_regenerates_uids_consistently_across_files(
    tmp_path: Path, make_dicom_file: Callable[..., Path]
) -> None:
    rectified_dir = tmp_path / "rectify"
    file_a = make_dicom_file(
        rectified_dir / "021-DWI" / "1.dcm", StudyInstanceUID="study-a", InstanceNumber=1
    )
    file_b = make_dicom_file(
        rectified_dir / "021-DWI" / "2.dcm", StudyInstanceUID="study-a", InstanceNumber=2
    )

    subject = _subject(tmp_path / "capture")
    from dichotomise.pydcm.read import read_metadata

    rectify_result = RectifyResult(
        subject=subject,
        rectified_dir=rectified_dir,
        files=[read_metadata(file_a), read_metadata(file_b)],
    )

    result = sanitise(rectify_result, policy=load_policy("standard"), subject_label="sub-0005")

    written_a = pydicom.dcmread(result.files[0], force=True)
    written_b = pydicom.dcmread(result.files[1], force=True)
    assert written_a.StudyInstanceUID == written_b.StudyInstanceUID
    assert written_a.StudyInstanceUID != "study-a"
