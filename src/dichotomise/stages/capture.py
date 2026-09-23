"""Stage 1: copy the raw source directory into the run's working/ folder."""

from __future__ import annotations

import shutil
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from dichotomise.errors import NoDicomFilesFoundError
from dichotomise.pydcm.read import DicomMetadata, iter_dicom_metadata
from dichotomise.run import Run
from dichotomise.utils.fs import reject_symlinks
from dichotomise.utils.text import safe_filename_text


@dataclass(frozen=True)
class CapturedSubject:
    """One subject's files, copied into the run's working folder."""

    subject_id: str
    patient_name: str
    study_instance_uid: str
    scan_date: str
    scan_time: str
    directory: Path
    output_number: int = 1


def _subject_folder_name(metadata: DicomMetadata, used_names: dict[str, int]) -> str:
    base_name = (
        f"{safe_filename_text(metadata.patient_id)}_{safe_filename_text(metadata.study_date)}"
    )
    occurrence = used_names.get(base_name, 0) + 1
    used_names[base_name] = occurrence
    return base_name if occurrence == 1 else f"{base_name}-{occurrence:03d}"


def capture(source_dir: Path, run: Run) -> list[CapturedSubject]:
    """Copy every scan file under `source_dir` into the run's working folder, by subject.

    Subjects are identified from each file's PatientID and StudyInstanceUID,
    never from folder names, so a messy or misnamed export still ends up
    split correctly. A file that cannot be read as DICOM is left behind
    rather than copied.
    """
    reject_symlinks(source_dir)

    files_by_subject: dict[tuple[str, str], list[Path]] = defaultdict(list)
    metadata_by_subject: dict[tuple[str, str], DicomMetadata] = {}
    for metadata in iter_dicom_metadata(source_dir):
        key = (metadata.patient_id, metadata.study_instance_uid)
        files_by_subject[key].append(metadata.path)
        metadata_by_subject.setdefault(key, metadata)

    if not files_by_subject:
        raise NoDicomFilesFoundError(f"No DICOM files were found under {source_dir}")

    used_names: dict[str, int] = {}
    captured: list[CapturedSubject] = []
    for output_number, key in enumerate(sorted(files_by_subject), start=1):
        metadata = metadata_by_subject[key]
        folder_name = _subject_folder_name(metadata, used_names)
        destination = run.working_dir / folder_name / "capture"
        for path in files_by_subject[key]:
            target = destination / path.relative_to(source_dir)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        captured.append(
            CapturedSubject(
                subject_id=metadata.patient_id,
                patient_name=metadata.patient_name,
                study_instance_uid=metadata.study_instance_uid,
                scan_date=metadata.study_date,
                scan_time=metadata.study_time,
                directory=destination,
                output_number=output_number,
            )
        )
    return captured
