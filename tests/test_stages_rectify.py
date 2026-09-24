from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from dichotomise.errors import DichotomiseError
from dichotomise.pydcm.read import DicomMetadata
from dichotomise.stages.capture import CapturedSubject
from dichotomise.stages.rectify import rectify
from dichotomise.stages.sift import SiftResult


def _metadata(path: Path, **overrides: object) -> DicomMetadata:
    defaults: dict[str, object] = {
        "path": path,
        "patient_id": "sub-01",
        "patient_name": "Doe^Jane^19900101",
        "study_instance_uid": "study-a",
        "series_instance_uid": "series-dwi",
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


def _subject(directory: Path) -> CapturedSubject:
    return CapturedSubject(
        subject_id="sub-01",
        patient_name="Doe^Jane^19900101",
        study_instance_uid="study-a",
        scan_date="20260101",
        scan_time="120000",
        directory=directory,
    )


def test_rectify_copies_retained_files_into_their_agreed_names(tmp_path: Path) -> None:
    retained_dir = tmp_path / "sift" / "retained"
    path_a = retained_dir / "021-DWI" / "1.dcm"
    path_a.parent.mkdir(parents=True)
    path_a.write_bytes(b"first")
    path_b = retained_dir / "021-DWI" / "2.dcm"
    path_b.write_bytes(b"second")

    subject = _subject(tmp_path / "capture")
    sift_result = SiftResult(
        subject=subject,
        retained=[
            _metadata(path_a, instance_number=1),
            _metadata(path_b, instance_number=2),
        ],
        retained_dir=retained_dir,
        review=[],
        review_dir=tmp_path / "sift" / "review",
    )

    result = rectify(sift_result)

    expected_a = result.rectified_dir / "021-diffusion" / "021_series-dwi_0001_e01.dcm"
    expected_b = result.rectified_dir / "021-diffusion" / "021_series-dwi_0002_e01.dcm"
    assert expected_a.read_bytes() == b"first"
    assert expected_b.read_bytes() == b"second"
    assert {f.path for f in result.files} == {expected_a, expected_b}


def test_rectify_raises_when_two_different_files_would_share_a_name(
    tmp_path: Path, make_dicom_file: Callable[..., Path]
) -> None:
    retained_dir = tmp_path / "sift" / "retained"
    path_a = make_dicom_file(
        retained_dir / "021-DWI" / "1.dcm", SeriesInstanceUID="series-dwi", InstanceNumber=1
    )
    path_b = make_dicom_file(
        retained_dir / "021-DWI" / "2.dcm", SeriesInstanceUID="series-dwi", InstanceNumber=2
    )

    subject = _subject(tmp_path / "capture")
    # Both mapped (deliberately, via the metadata override) to the same
    # rectified name (same series, same instance number) despite genuinely
    # different underlying file content.
    sift_result = SiftResult(
        subject=subject,
        retained=[
            _metadata(path_a, series_instance_uid="series-dwi", instance_number=1),
            _metadata(path_b, series_instance_uid="series-dwi", instance_number=1),
        ],
        retained_dir=retained_dir,
        review=[],
        review_dir=tmp_path / "sift" / "review",
    )

    with pytest.raises(DichotomiseError):
        rectify(sift_result)
