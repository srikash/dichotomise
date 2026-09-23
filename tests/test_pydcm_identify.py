from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

from dichotomise.pydcm.identify import content_hash, find_duplicate_files, find_misfiled_files
from dichotomise.pydcm.read import DicomMetadata, iter_dicom_files, read_metadata

DATA_DIR = Path(__file__).parent / "data"


def _metadata(path: Path, **overrides: object) -> DicomMetadata:
    defaults: dict[str, object] = {
        "path": path,
        "patient_id": "sub-01",
        "patient_name": "Doe^Jane^19900101",
        "study_instance_uid": "1.2.3",
        "series_instance_uid": "1.2.840.10008.5.1.4.1.1.4.99",
        "sop_instance_uid": "1.2.3.4",
        "series_number": 21,
        "series_description": "diffusion",
        "protocol_name": "DWI_64dir",
        "instance_number": 1,
        "echo_number": 1,
        "study_date": "20260101",
        "study_time": "120000",
    }
    defaults.update(overrides)
    return DicomMetadata(**defaults)  # type: ignore[arg-type]


def test_content_hash_matches_for_the_same_scan_content_with_a_different_unique_id(
    tmp_path: Path, make_dicom_file: Callable[..., Path]
) -> None:
    # A real duplicate is the same scan (same study/series) re-saved with a
    # new per-file ID, not a file from an unrelated series.
    shared_series_uid = "1.2.840.10008.5.1.4.1.1.4.99"
    shared_study_uid = "1.2.3"
    first = make_dicom_file(
        tmp_path / "1.dcm",
        StudyInstanceUID=shared_study_uid,
        SeriesInstanceUID=shared_series_uid,
        SeriesNumber=21,
        InstanceNumber=1,
    )
    second = make_dicom_file(
        tmp_path / "2.dcm",
        StudyInstanceUID=shared_study_uid,
        SeriesInstanceUID=shared_series_uid,
        SeriesNumber=21,
        InstanceNumber=1,
    )

    assert content_hash(first) == content_hash(second)


def test_content_hash_differs_for_genuinely_different_scan_content(
    tmp_path: Path, make_dicom_file: Callable[..., Path]
) -> None:
    first = make_dicom_file(tmp_path / "1.dcm", InstanceNumber=1)
    second = make_dicom_file(tmp_path / "2.dcm", InstanceNumber=2)

    assert content_hash(first) != content_hash(second)


def test_find_duplicate_files_flags_the_later_copy_of_repeated_content(
    tmp_path: Path, make_dicom_file: Callable[..., Path]
) -> None:
    shared_series_uid = "1.2.840.10008.5.1.4.1.1.4.99"
    shared_study_uid = "1.2.3"
    original = make_dicom_file(
        tmp_path / "1.dcm",
        StudyInstanceUID=shared_study_uid,
        SeriesInstanceUID=shared_series_uid,
        InstanceNumber=1,
    )
    repeat = make_dicom_file(
        tmp_path / "2.dcm",
        StudyInstanceUID=shared_study_uid,
        SeriesInstanceUID=shared_series_uid,
        InstanceNumber=1,
    )
    different = make_dicom_file(tmp_path / "3.dcm", InstanceNumber=2)

    duplicates = find_duplicate_files([original, repeat, different])

    assert duplicates == {repeat}


def test_find_misfiled_files_flags_a_file_that_disagrees_with_its_folder() -> None:
    belongs = _metadata(Path("021-DWI/1.dcm"), series_instance_uid="series-a")
    also_belongs = _metadata(Path("021-DWI/2.dcm"), series_instance_uid="series-a")
    misfiled = _metadata(Path("021-DWI/3.dcm"), series_instance_uid="series-b")

    result = find_misfiled_files({"021-DWI": [belongs, also_belongs, misfiled]})

    assert result == {misfiled.path}


def test_find_misfiled_files_flags_nothing_when_a_folder_agrees_with_itself() -> None:
    belongs = _metadata(Path("021-DWI/1.dcm"))
    also_belongs = _metadata(Path("021-DWI/2.dcm"))

    result = find_misfiled_files({"021-DWI": [belongs, also_belongs]})

    assert result == set()


def test_real_example_export_has_no_duplicates_or_misfiled_files() -> None:
    files_by_folder: dict[str, list[DicomMetadata]] = defaultdict(list)
    for path in iter_dicom_files(DATA_DIR):
        metadata = read_metadata(path)
        files_by_folder[str(path.parent)].append(metadata)

    assert files_by_folder, "expected at least one DICOM file under tests/data"

    for folder, items in files_by_folder.items():
        duplicates = find_duplicate_files([item.path for item in items])
        assert duplicates == set(), f"unexpected duplicate(s) in {folder}"

    assert find_misfiled_files(files_by_folder) == set()
