"""Stage 1: group the source directory's DICOMs by subject, without copying them."""

from __future__ import annotations

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
    """One subject's files, found in place under the source directory.

    `files` point at the original, untouched source files; nothing has been
    copied yet. `source_root` is the source directory they were found
    under, used to keep archived/report paths relative to it. `working_dir`
    is this subject's own folder under the run's working/ directory, where
    later stages (rectify, sanitise) write their output -- the one place in
    the pipeline real copies are made.
    """

    subject_id: str
    patient_name: str
    study_instance_uid: str
    scan_date: str
    scan_time: str
    files: list[DicomMetadata]
    source_root: Path
    working_dir: Path
    output_number: int = 1


def _subject_folder_name(metadata: DicomMetadata, used_names: dict[str, int]) -> str:
    base_name = (
        f"{safe_filename_text(metadata.patient_id)}_{safe_filename_text(metadata.study_date)}"
    )
    occurrence = used_names.get(base_name, 0) + 1
    used_names[base_name] = occurrence
    return base_name if occurrence == 1 else f"{base_name}-{occurrence:03d}"


def capture(source_dir: Path, run: Run) -> list[CapturedSubject]:
    """Group every scan file under `source_dir` by subject, without copying any of them.

    Subjects are identified from each file's PatientID and StudyInstanceUID,
    never from folder names, so a messy or misnamed export still ends up
    split correctly. A file that cannot be read as DICOM is left out of
    every subject's file list.
    """
    reject_symlinks(source_dir)

    files_by_subject: dict[tuple[str, str], list[DicomMetadata]] = defaultdict(list)
    for metadata in iter_dicom_metadata(source_dir):
        key = (metadata.patient_id, metadata.study_instance_uid)
        files_by_subject[key].append(metadata)

    if not files_by_subject:
        raise NoDicomFilesFoundError(f"No DICOM files were found under {source_dir}")

    used_names: dict[str, int] = {}
    captured: list[CapturedSubject] = []
    for output_number, key in enumerate(sorted(files_by_subject), start=1):
        files = sorted(files_by_subject[key], key=lambda metadata: metadata.path)
        first = files[0]
        folder_name = _subject_folder_name(first, used_names)
        captured.append(
            CapturedSubject(
                subject_id=first.patient_id,
                patient_name=first.patient_name,
                study_instance_uid=first.study_instance_uid,
                scan_date=first.study_date,
                scan_time=first.study_time,
                files=files,
                source_root=source_dir,
                working_dir=run.working_dir / folder_name,
                output_number=output_number,
            )
        )
    return captured
