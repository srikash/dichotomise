"""Stage 3: structural QA over captured DICOM files (duplicates, misfiled series)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from dichotomise.errors import NoDicomFilesFoundError
from dichotomise.pydcm.identify import find_duplicate_files, find_misfiled_files
from dichotomise.pydcm.read import DicomMetadata, iter_dicom_metadata
from dichotomise.stages.capture import CapturedSubject

_CONSISTENCY_FIELDS: tuple[tuple[str, str], ...] = (
    ("PatientID", "patient_id"),
    ("PatientName", "patient_name"),
    ("StudyInstanceUID", "study_instance_uid"),
    ("StudyDate", "study_date"),
    ("StudyTime", "study_time"),
    ("SeriesInstanceUID", "series_instance_uid"),
    ("SeriesNumber", "series_number"),
    ("SeriesDescription", "series_description"),
    ("ProtocolName", "protocol_name"),
)


@dataclass(frozen=True)
class AuditedFile:
    """One file's scan metadata, plus the two structural checks run against it."""

    metadata: DicomMetadata
    is_duplicate: bool
    is_misfiled: bool


@dataclass(frozen=True)
class AuditResult:
    """The structural findings for every file captured for one subject."""

    subject: CapturedSubject
    files: list[AuditedFile]


def metadata_inconsistencies(files: Sequence[AuditedFile]) -> list[str]:
    """Return identity and series fields whose values differ within one folder."""
    return [
        label
        for label, attribute in _CONSISTENCY_FIELDS
        if len({getattr(file.metadata, attribute) for file in files}) > 1
    ]


def audit(subject: CapturedSubject) -> AuditResult:
    """Check a captured subject's files for duplicates and files in the wrong folder.

    Both checks are computed per physical folder: a folder's own files
    decide, by majority, what series that folder is supposed to contain
    (see pydcm.identify.find_misfiled_files), and duplicate content is only
    compared between files that already sit in the same folder.
    """
    return _audit_directory(subject.directory, subject)


def audit_directory(directory: Path) -> AuditResult:
    """Audit DICOMs in place without creating a pipeline run or copying files."""
    subject = CapturedSubject(
        subject_id="QC",
        patient_name="",
        study_instance_uid="",
        scan_date="",
        scan_time="",
        directory=directory,
    )
    return _audit_directory(directory, subject)


def _audit_directory(directory: Path, subject: CapturedSubject) -> AuditResult:
    """Compute audit findings for DICOMs under one directory."""
    files_by_folder: dict[Path, list[Path]] = defaultdict(list)
    metadata_by_folder: dict[str, list[DicomMetadata]] = defaultdict(list)
    metadata_by_path: dict[Path, DicomMetadata] = {}

    for metadata in iter_dicom_metadata(directory):
        path = metadata.path
        metadata_by_path[path] = metadata
        files_by_folder[path.parent].append(path)
        metadata_by_folder[str(path.parent)].append(metadata)

    if not metadata_by_path:
        raise NoDicomFilesFoundError(f"No DICOM files were found under {directory}")

    duplicates: set[Path] = set()
    for paths in files_by_folder.values():
        duplicates |= find_duplicate_files(paths)

    misfiled = find_misfiled_files(metadata_by_folder)

    files = [
        AuditedFile(
            metadata=metadata,
            is_duplicate=path in duplicates,
            is_misfiled=path in misfiled,
        )
        for path, metadata in sorted(metadata_by_path.items())
    ]
    return AuditResult(subject=subject, files=files)
