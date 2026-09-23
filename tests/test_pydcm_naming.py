from __future__ import annotations

from pathlib import Path

from dichotomise.pydcm.naming import rectified_path
from dichotomise.pydcm.read import DicomMetadata


def _metadata(**overrides: object) -> DicomMetadata:
    defaults: dict[str, object] = {
        "path": Path("/source/1.dcm"),
        "patient_id": "sub-01",
        "patient_name": "Doe^Jane^19900101",
        "study_instance_uid": "1.2.3",
        "series_instance_uid": "1.2.840.10008.5.1.4.1.1.4.99",
        "sop_instance_uid": "1.2.3.4",
        "series_number": 21,
        "series_description": "diffusion",
        "protocol_name": "DWI 64 dir",
        "instance_number": 5,
        "echo_number": 1,
        "study_date": "20260101",
        "study_time": "120000",
    }
    defaults.update(overrides)
    return DicomMetadata(**defaults)  # type: ignore[arg-type]


def test_rectified_path_matches_the_agreed_naming_scheme() -> None:
    base_dir = Path("/rectified")

    result = rectified_path(base_dir, _metadata())

    assert result == (base_dir / "021-DWI_64_dir" / "021_1.2.840.10008.5.1.4.1.1.4.99_0005_e01.dcm")


def test_rectified_path_pads_series_instance_and_echo_numbers() -> None:
    result = rectified_path(
        Path("/rectified"),
        _metadata(series_number=3, instance_number=42, echo_number=9),
    )

    assert result.parent.name.startswith("003-")
    assert result.name.startswith("003_")
    assert "_0042_e09.dcm" in result.name


def test_rectified_path_falls_back_to_na_for_blank_protocol_name() -> None:
    result = rectified_path(Path("/rectified"), _metadata(protocol_name=""))

    assert result.parent.name == "021-NA"


def test_rectified_path_defaults_missing_echo_number_to_one() -> None:
    result = rectified_path(Path("/rectified"), _metadata(echo_number=None))

    assert "_e01.dcm" in result.name
