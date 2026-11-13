"""The rectify stage: target names, collisions and byte-identical repeats."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from functools import partial
from pathlib import Path

import pytest
from helpers import make_metadata, make_subject

from dichotomise.errors import DichotomiseError, FinaliseVerificationError
from dichotomise.stages.rectify import rectify, rectify_review
from dichotomise.stages.sift import ReviewFile, SiftResult

_metadata = partial(make_metadata, series_instance_uid="series-dwi")


def test_rectify_copies_retained_files_into_their_agreed_names(tmp_path: Path) -> None:
    source_dir = tmp_path / "export"
    path_a = source_dir / "021-DWI" / "1.dcm"
    path_a.parent.mkdir(parents=True)
    path_a.write_bytes(b"first")
    path_b = source_dir / "021-DWI" / "2.dcm"
    path_b.write_bytes(b"second")

    subject = make_subject(tmp_path / "working" / "sub-01", source_dir)
    sift_result = SiftResult(
        subject=subject,
        retained=[
            _metadata(path_a, instance_number=1),
            _metadata(path_b, instance_number=2),
        ],
        review=[],
    )

    result = rectify(sift_result, {})

    expected_a = result.rectified_dir / "021-diffusion" / "021_0001_sop-1_e01.dcm"
    expected_b = result.rectified_dir / "021-diffusion" / "021_0002_sop-1_e01.dcm"
    assert expected_a.read_bytes() == b"first"
    assert expected_b.read_bytes() == b"second"
    assert {f.path for f in result.files} == {expected_a, expected_b}
    # The originals are untouched copies, not moved or linked away.
    assert path_a.read_bytes() == b"first"
    assert path_b.read_bytes() == b"second"


def test_rectify_writes_a_byte_identical_repeat_in_another_folder_only_once(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "export"
    path_a = source_dir / "exportA" / "021-DWI" / "1.dcm"
    path_b = source_dir / "exportB" / "021-DWI" / "1.dcm"
    for path in (path_a, path_b):
        path.parent.mkdir(parents=True)
        path.write_bytes(b"same bytes")

    subject = make_subject(tmp_path / "working" / "sub-01", source_dir)
    sift_result = SiftResult(
        subject=subject,
        retained=[_metadata(path_a), _metadata(path_b)],
        review=[],
    )

    result = rectify(sift_result, {})

    expected = result.rectified_dir / "021-diffusion" / "021_0001_sop-1_e01.dcm"
    assert [f.path for f in result.files] == [expected]
    assert expected.read_bytes() == b"same bytes"
    assert result.merged_identical_count == 1


def test_rectify_raises_when_two_different_files_would_share_a_name(
    tmp_path: Path, make_dicom_file: Callable[..., Path]
) -> None:
    source_dir = tmp_path / "export"
    path_a = make_dicom_file(
        source_dir / "021-DWI" / "1.dcm", SeriesInstanceUID="series-dwi", InstanceNumber=1
    )
    path_b = make_dicom_file(
        source_dir / "021-DWI" / "2.dcm", SeriesInstanceUID="series-dwi", InstanceNumber=2
    )

    subject = make_subject(tmp_path / "working" / "sub-01", source_dir)
    # Both mapped (deliberately, via the metadata override) to the same
    # rectified name (same series, same instance number) despite genuinely
    # different underlying file content.
    sift_result = SiftResult(
        subject=subject,
        retained=[
            _metadata(path_a, series_instance_uid="series-dwi", instance_number=1),
            _metadata(path_b, series_instance_uid="series-dwi", instance_number=1),
        ],
        review=[],
    )

    with pytest.raises(DichotomiseError):
        rectify(sift_result, {})


def test_rectify_review_renames_files_using_the_same_naming_scheme(tmp_path: Path) -> None:
    source_dir = tmp_path / "export"
    path_a = source_dir / "021-DWI" / "1.dcm"
    path_a.parent.mkdir(parents=True)
    path_a.write_bytes(b"duplicate content")

    subject = make_subject(tmp_path / "working" / "sub-01", source_dir)
    sift_result = SiftResult(
        subject=subject,
        retained=[],
        review=[ReviewFile(_metadata(path_a, instance_number=1), "duplicate")],
    )

    result = rectify_review(sift_result, {})

    expected = result.review_rectified_dir / "021-diffusion" / "021_0001_sop-1_e01.dcm"
    assert expected.read_bytes() == b"duplicate content"
    assert [f.path for f in result.files] == [expected]
    assert result.collision_count == 0


def test_rectify_review_disambiguates_colliding_names_instead_of_raising(tmp_path: Path) -> None:
    source_dir = tmp_path / "export"
    path_a = source_dir / "021-DWI" / "1.dcm"
    path_a.parent.mkdir(parents=True)
    path_a.write_bytes(b"first")
    path_b = source_dir / "021-DWI" / "2.dcm"
    path_b.write_bytes(b"second")

    subject = make_subject(tmp_path / "working" / "sub-01", source_dir)
    # Both misfiled/duplicate files claim the exact same series+instance,
    # which is expected to happen in review -- it must not stop the run.
    sift_result = SiftResult(
        subject=subject,
        retained=[],
        review=[
            ReviewFile(_metadata(path_a, instance_number=1), "misfiled"),
            ReviewFile(_metadata(path_b, instance_number=1), "misfiled"),
        ],
    )

    result = rectify_review(sift_result, {})

    folder = result.review_rectified_dir / "021-diffusion"
    assert (folder / "021_0001_sop-1_e01.dcm").read_bytes() == b"first"
    assert (folder / "021_0001_sop-1_e01-dup01.dcm").read_bytes() == b"second"
    assert result.collision_count == 1


def test_rectify_review_writes_a_byte_identical_repeat_only_once(tmp_path: Path) -> None:
    source_dir = tmp_path / "export"
    path_a = source_dir / "021-DWI" / "2.dcm"
    path_a.parent.mkdir(parents=True)
    path_a.write_bytes(b"same bytes")
    path_b = source_dir / "021-DWI" / "3.dcm"
    path_b.write_bytes(b"same bytes")

    subject = make_subject(tmp_path / "working" / "sub-01", source_dir)
    sift_result = SiftResult(
        subject=subject,
        retained=[],
        review=[
            ReviewFile(_metadata(path_a), "duplicate"),
            ReviewFile(_metadata(path_b), "duplicate"),
        ],
    )

    result = rectify_review(sift_result, {})

    folder = result.review_rectified_dir / "021-diffusion"
    assert sorted(p.name for p in folder.iterdir()) == ["021_0001_sop-1_e01.dcm"]
    assert len(result.files) == 1
    assert result.collision_count == 0
    assert result.merged_identical_count == 1


def _one_file_sift(tmp_path: Path) -> SiftResult:
    source = tmp_path / "src" / "021-DWI" / "1.dcm"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"first")
    subject = make_subject(tmp_path / "working" / "sub-01", tmp_path / "src")
    return SiftResult(subject=subject, retained=[_metadata(source, instance_number=1)], review=[])


def _corrupting_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the copy step write bytes that differ from the source."""

    def corrupt(source: Path, target: Path) -> None:
        target.write_bytes(b"corrupt")

    monkeypatch.setattr("dichotomise.stages.rectify.shutil.copy2", corrupt)


def test_rectify_checks_each_copy_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _corrupting_copy(monkeypatch)
    with pytest.raises(FinaliseVerificationError, match="Copied file differs"):
        rectify(_one_file_sift(tmp_path), {})


def test_rectify_can_leave_the_copy_check_to_finalise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _corrupting_copy(monkeypatch)
    digests: dict[Path, str] = {}
    result = rectify(_one_file_sift(tmp_path), digests, check_copies=False)
    (copy,) = result.target_by_source.values()
    # The copy's digest is recorded as the source's, so finalise's later read catches the mismatch.
    assert digests[copy] != hashlib.sha256(copy.read_bytes()).hexdigest()
