from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from dichotomise.errors import DichotomiseError
from dichotomise.pydcm.read import DicomMetadata
from dichotomise.stages.capture import CapturedSubject
from dichotomise.stages.rectify import rectify, rectify_review
from dichotomise.stages.sift import ReviewFile, SiftResult


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


def test_rectify_review_renames_files_using_the_same_naming_scheme(tmp_path: Path) -> None:
    review_dir = tmp_path / "sift" / "review"
    path_a = review_dir / "021-DWI" / "1.dcm"
    path_a.parent.mkdir(parents=True)
    path_a.write_bytes(b"duplicate content")

    subject = _subject(tmp_path / "capture")
    sift_result = SiftResult(
        subject=subject,
        retained=[],
        retained_dir=tmp_path / "sift" / "retained",
        review=[ReviewFile(_metadata(path_a, instance_number=1), "duplicate")],
        review_dir=review_dir,
    )

    result = rectify_review(sift_result)

    expected = result.review_rectified_dir / "021-diffusion" / "021_series-dwi_0001_e01.dcm"
    assert expected.read_bytes() == b"duplicate content"
    assert [f.path for f in result.files] == [expected]
    assert result.collision_count == 0


def test_rectify_review_disambiguates_colliding_names_instead_of_raising(tmp_path: Path) -> None:
    review_dir = tmp_path / "sift" / "review"
    path_a = review_dir / "021-DWI" / "1.dcm"
    path_a.parent.mkdir(parents=True)
    path_a.write_bytes(b"first")
    path_b = review_dir / "021-DWI" / "2.dcm"
    path_b.write_bytes(b"second")

    subject = _subject(tmp_path / "capture")
    # Both misfiled/duplicate files claim the exact same series+instance,
    # which is expected to happen in review -- it must not stop the run.
    sift_result = SiftResult(
        subject=subject,
        retained=[],
        retained_dir=tmp_path / "sift" / "retained",
        review=[
            ReviewFile(_metadata(path_a, instance_number=1), "misfiled"),
            ReviewFile(_metadata(path_b, instance_number=1), "misfiled"),
        ],
        review_dir=review_dir,
    )

    result = rectify_review(sift_result)

    folder = result.review_rectified_dir / "021-diffusion"
    assert (folder / "021_series-dwi_0001_e01.dcm").read_bytes() == b"first"
    assert (folder / "021_series-dwi_0001_e01-dup01.dcm").read_bytes() == b"second"
    assert result.collision_count == 1
