"""Discover DICOM files and read the metadata the pipeline needs."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pydicom
from pydicom.errors import InvalidDicomError

from dichotomise.errors import InvalidDicomMetadataError, NotDicomError


@dataclass(frozen=True)
class DicomMetadata:
    """The DICOM fields the pipeline needs, read from one file."""

    path: Path
    patient_id: str
    patient_name: str
    study_instance_uid: str
    series_instance_uid: str
    sop_instance_uid: str
    series_number: int
    series_description: str
    protocol_name: str
    instance_number: int
    echo_number: int | None
    study_date: str
    study_time: str


def _number_or_zero(value: object, field: str) -> int:
    """Return a DICOM number, using zero when an optional field is blank."""
    if value in (None, ""):
        return 0
    try:
        return int(str(value))
    except (TypeError, ValueError) as error:
        raise InvalidDicomMetadataError(
            f"{field} is not a usable whole number: {value!r}"
        ) from error


def read_metadata(path: Path) -> DicomMetadata:
    """Read the DICOM fields dichotomise needs from `path`.

    Raises NotDicomError if `path` cannot be read as a DICOM file.
    """
    try:
        dataset = pydicom.dcmread(path, stop_before_pixels=True)
    except (InvalidDicomError, OSError) as error:
        raise NotDicomError(f"{path} is not a readable DICOM file") from error

    echo_number = dataset.get("EchoNumbers")
    return DicomMetadata(
        path=path,
        patient_id=str(dataset.get("PatientID", "")),
        patient_name=str(dataset.get("PatientName", "")),
        study_instance_uid=str(dataset.get("StudyInstanceUID", "")),
        series_instance_uid=str(dataset.get("SeriesInstanceUID", "")),
        sop_instance_uid=str(dataset.get("SOPInstanceUID", "")),
        series_number=_number_or_zero(dataset.get("SeriesNumber"), "SeriesNumber"),
        series_description=str(dataset.get("SeriesDescription", "")),
        protocol_name=str(dataset.get("ProtocolName", "")),
        instance_number=_number_or_zero(dataset.get("InstanceNumber"), "InstanceNumber"),
        echo_number=_number_or_zero(echo_number, "EchoNumbers")
        if echo_number is not None
        else None,
        study_date=str(dataset.get("StudyDate", "")),
        study_time=str(dataset.get("StudyTime", "")),
    )


def iter_dicom_metadata(root: Path) -> Iterator[DicomMetadata]:
    """Recursively yield metadata for every readable DICOM file under `root`.

    Non-DICOM files (stray text files, checksums, thumbnails, ...) are
    silently skipped rather than raised on, since an export directory
    commonly contains a mix.
    """
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        try:
            yield read_metadata(path)
        except NotDicomError:
            continue


def iter_dicom_files(root: Path) -> Iterator[Path]:
    """Recursively yield every readable DICOM path under `root`."""
    yield from (metadata.path for metadata in iter_dicom_metadata(root))
