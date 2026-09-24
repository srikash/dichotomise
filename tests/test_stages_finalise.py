from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dichotomise.errors import FinaliseVerificationError
from dichotomise.pydcm.read import read_metadata
from dichotomise.run import start_run
from dichotomise.stages.capture import CapturedSubject
from dichotomise.stages.finalise import finalise
from dichotomise.stages.rectify import RectifyResult
from dichotomise.utils.archive import verify_archive


def _subject(directory: Path) -> CapturedSubject:
    return CapturedSubject(
        subject_id="sub-01",
        patient_name="Doe^Jane^19900101",
        study_instance_uid="study-a",
        scan_date="20260101",
        scan_time="120000",
        directory=directory,
    )


def test_finalise_archives_the_rectified_tree_when_not_sanitising(
    tmp_path: Path, make_dicom_file: Callable[..., Path]
) -> None:
    rectified_dir = tmp_path / "rectify"
    file_a = make_dicom_file(rectified_dir / "021-DWI" / "1.dcm")
    subject = _subject(tmp_path / "capture")
    rectify_result = RectifyResult(
        subject=subject, rectified_dir=rectified_dir, files=[read_metadata(file_a)]
    )
    run = start_run(tmp_path / "out", now=datetime(2026, 9, 22, 14, 30, 12, tzinfo=UTC))

    result = finalise(rectify_result, run, subject_label="sub-01")

    expected_name = "20260922T143012Z_sub-01_20260101-120000_study-001_dichotomised-archive"
    assert result.archive.path == run.archives_dir / f"{expected_name}.tar.gz"
    assert verify_archive(result.archive.path, result.archive.checksum_path) is True


def test_finalise_raises_when_the_output_tree_is_missing_an_expected_file(
    tmp_path: Path, make_dicom_file: Callable[..., Path]
) -> None:
    rectified_dir = tmp_path / "rectify"
    file_a = make_dicom_file(rectified_dir / "021-DWI" / "1.dcm")
    metadata_a = read_metadata(file_a)
    subject = _subject(tmp_path / "capture")
    # Claim a second file that was never actually written.
    missing = rectified_dir / "021-DWI" / "2.dcm"
    from dataclasses import replace

    rectify_result = RectifyResult(
        subject=subject,
        rectified_dir=rectified_dir,
        files=[metadata_a, replace(metadata_a, path=missing)],
    )
    run = start_run(tmp_path / "out", now=datetime(2026, 9, 22, 14, 30, 12, tzinfo=UTC))

    with pytest.raises(FinaliseVerificationError):
        finalise(rectify_result, run, subject_label="sub-01")
