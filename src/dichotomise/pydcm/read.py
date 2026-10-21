"""Discover DICOM files and read the metadata the pipeline needs."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pydicom
from pydicom.errors import InvalidDicomError
from pydicom.multival import MultiValue

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
    modality: str = ""
    echo_time: float | None = None
    acquisition_number: int | None = None
    acquisition_datetime: str = ""
    number_of_frames: int = 1
    asl_context: str | None = None
    mixed_echoes: bool = False
    inversion_time: float | None = None
    is_asl: bool = False


def _optional_number(value: object, convert: Callable[[Any], int | float]) -> Any:
    """Convert an optional, descriptive header value; None if absent or unusable.

    Used for fields that only feed notes and inference (echo time, acquisition
    number, ...). A malformed one must never stop a run that would otherwise
    have completed.
    """
    if value in (None, ""):
        return None
    try:
        return convert(value)
    except (TypeError, ValueError):
        return None


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


def _per_frame_values(dataset: pydicom.Dataset) -> tuple[set[int], set[float], set[str]]:
    """Collect the echo numbers, echo times and ASL contexts stated frame by frame.

    Enhanced (multi-frame) MR keeps these in the per-frame functional groups
    rather than at the top level of the file.
    """
    echo_numbers: set[int] = set()
    echo_times: set[float] = set()
    asl_contexts: set[str] = set()
    for frame in dataset.get("PerFrameFunctionalGroupsSequence", []):
        for echo in frame.get("MREchoSequence", [])[:1]:
            number = _optional_number(echo.get("EchoNumbers"), int)
            if number is not None:
                echo_numbers.add(number)
            echo_time = _optional_number(echo.get("EffectiveEchoTime"), float)
            if echo_time is not None:
                echo_times.add(echo_time)
        for asl in frame.get("MRArterialSpinLabelingSequence", [])[:1]:
            if asl.get("ASLContext"):
                asl_contexts.add(str(asl.ASLContext))
    return echo_numbers, echo_times, asl_contexts


def _inversion_time(dataset: pydicom.Dataset) -> float | None:
    """Return a stated inversion time (ms): top-level, or from the shared functional groups."""
    value = dataset.get("InversionTime")
    if value in (None, ""):
        for group in dataset.get("SharedFunctionalGroupsSequence", [])[:1]:
            for modifier in group.get("MRModifierSequence", [])[:1]:
                times = modifier.get("InversionTimes")
                # A single time is a bare number; several arrive as a list.
                value = times[0] if isinstance(times, MultiValue) and times else times
    inversion_time: float | None = _optional_number(value, float)
    return inversion_time


def read_metadata(path: Path) -> DicomMetadata:
    """Read the DICOM fields dichotomise needs from `path`.

    Raises NotDicomError if `path` cannot be read as a DICOM file.
    """
    try:
        dataset = pydicom.dcmread(path, stop_before_pixels=True)
    except (InvalidDicomError, OSError) as error:
        raise NotDicomError(f"{path} is not a readable DICOM file") from error

    echo_number = dataset.get("EchoNumbers")
    echo_time = dataset.get("EchoTime")
    frame_echo_numbers, frame_echo_times, frame_asl_contexts = _per_frame_values(dataset)
    mixed_echoes = len(frame_echo_numbers) > 1
    if echo_number is None and len(frame_echo_numbers) == 1:
        echo_number = next(iter(frame_echo_numbers))
    if echo_time is None and len(frame_echo_times) == 1:
        echo_time = next(iter(frame_echo_times))
    acquisition_number = dataset.get("AcquisitionNumber")
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
        modality=str(dataset.get("Modality", "")),
        echo_time=_optional_number(echo_time, float),
        acquisition_number=_optional_number(acquisition_number, int),
        acquisition_datetime=str(dataset.get("AcquisitionDateTime", "")),
        number_of_frames=_optional_number(dataset.get("NumberOfFrames"), int) or 1,
        asl_context="/".join(sorted(frame_asl_contexts)) or None,
        mixed_echoes=mixed_echoes,
        inversion_time=_inversion_time(dataset),
        is_asl="ASL" in [str(part) for part in dataset.get("ImageType", [])]
        or bool(frame_asl_contexts),
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
