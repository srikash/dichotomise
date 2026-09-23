from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from dichotomise.pydcm.read import read_metadata


def test_read_metadata_includes_patient_name(
    tmp_path: Path, make_dicom_file: Callable[..., Path]
) -> None:
    path = make_dicom_file(tmp_path / "1.dcm", PatientName="Doe^Jane^19900101")

    metadata = read_metadata(path)

    assert metadata.patient_name == "Doe^Jane^19900101"
