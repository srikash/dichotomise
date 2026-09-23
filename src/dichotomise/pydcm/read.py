"""iter_dicom_files() and read_metadata(): pull the DICOM fields the pipeline needs."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pydicom
from pydicom.errors import InvalidDicomError

from dichotomise.errors import NotDicomError


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
        series_number=int(dataset.get("SeriesNumber", 0)),
        series_description=str(dataset.get("SeriesDescription", "")),
        protocol_name=str(dataset.get("ProtocolName", "")),
        instance_number=int(dataset.get("InstanceNumber", 0)),
        echo_number=int(echo_number) if echo_number is not None else None,
        study_date=str(dataset.get("StudyDate", "")),
        study_time=str(dataset.get("StudyTime", "")),
    )


def iter_dicom_files(root: Path) -> Iterator[Path]:
    """Recursively yield every file under `root` that is a valid DICOM file.

    Non-DICOM files (stray text files, checksums, thumbnails, ...) are
    silently skipped rather than raised on, since an export directory
    commonly contains a mix.
    """
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        try:
            pydicom.dcmread(path, stop_before_pixels=True)
        except (InvalidDicomError, OSError):
            continue
        yield path
