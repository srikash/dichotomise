from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from dichotomise.errors import NotDicomError
from dichotomise.pydcm.read import iter_dicom_files, read_metadata


def test_read_metadata_extracts_expected_fields(
    tmp_path: Path, make_dicom_file: Callable[..., Path]
) -> None:
    dicom_path = make_dicom_file(
        tmp_path / "1.dcm",
        PatientID="sub-01",
        SeriesNumber=3,
        SeriesDescription="DWI",
        ProtocolName="DWI_64dir",
        InstanceNumber=7,
        EchoNumbers=2,
    )

    metadata = read_metadata(dicom_path)

    assert metadata.path == dicom_path
    assert metadata.patient_id == "sub-01"
    assert metadata.series_number == 3
    assert metadata.series_description == "DWI"
    assert metadata.protocol_name == "DWI_64dir"
    assert metadata.instance_number == 7
    assert metadata.echo_number == 2
    assert metadata.study_date == "20260101"
    assert metadata.study_time == "120000"


def test_read_metadata_rejects_non_dicom_file(tmp_path: Path) -> None:
    not_dicom = tmp_path / "notes.txt"
    not_dicom.write_text("this is not a DICOM file")

    with pytest.raises(NotDicomError):
        read_metadata(not_dicom)


def test_iter_dicom_files_finds_only_dicom_files_recursively(
    tmp_path: Path, make_dicom_file: Callable[..., Path]
) -> None:
    dicom_a = make_dicom_file(tmp_path / "series-a" / "1.dcm")
    dicom_b = make_dicom_file(tmp_path / "series-b" / "nested" / "2.dcm")
    (tmp_path / "series-a" / "readme.txt").write_text("not a dicom file")

    found = set(iter_dicom_files(tmp_path))

    assert found == {dicom_a, dicom_b}
