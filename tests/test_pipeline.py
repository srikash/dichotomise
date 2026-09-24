from __future__ import annotations

import json
import tarfile
from collections.abc import Callable
from pathlib import Path

import pytest

from dichotomise.errors import RelabelError
from dichotomise.pipeline import run_pipeline


def test_run_pipeline_produces_one_archive_per_subject_and_cleans_up_working_files(
    tmp_path: Path, make_dicom_file: Callable[..., Path]
) -> None:
    source = tmp_path / "export"
    make_dicom_file(
        source / "DWI_21_MR" / "1.dcm",
        PatientID="sub-01",
        StudyInstanceUID="study-a",
        SeriesInstanceUID="series-a",
        SeriesNumber=21,
        StudyDate="20260101",
        StudyTime="120000",
    )
    make_dicom_file(
        source / "other" / "1.dcm",
        PatientID="sub-02",
        StudyInstanceUID="study-b",
        SeriesInstanceUID="series-b",
        SeriesNumber=1,
        StudyDate="20260102",
        StudyTime="130000",
    )

    run = run_pipeline(source, tmp_path / "out")

    source_archives = sorted(run.source_archive_dir.glob("*.tar.gz"))
    final_archives = sorted(run.archives_dir.glob("*.tar.gz"))
    assert len(source_archives) == 2
    assert any(path.name.startswith("sub-01_") for path in source_archives)
    assert any(path.name.startswith("sub-02_") for path in source_archives)
    assert len(final_archives) == 2
    assert any("sub-01" in p.name for p in final_archives)
    assert any("sub-02" in p.name for p in final_archives)
    assert not run.working_dir.exists()

    with tarfile.open(final_archives[0], "r:gz") as tar:
        names = tar.getnames()
    assert any(name.endswith(".dcm") for name in names)


def test_run_pipeline_keeps_working_files_when_requested(
    tmp_path: Path, make_dicom_file: Callable[..., Path]
) -> None:
    source = tmp_path / "export"
    make_dicom_file(source / "series" / "1.dcm", PatientID="sub-01", StudyInstanceUID="study-a")

    run = run_pipeline(source, tmp_path / "out", keep_working_files=True)

    assert run.working_dir.exists()


def test_run_pipeline_sanitise_default_label_mode_uses_patient_name(
    tmp_path: Path, make_dicom_file: Callable[..., Path]
) -> None:
    source = tmp_path / "export"
    make_dicom_file(
        source / "series" / "1.dcm",
        PatientID="sub-01",
        PatientName="Doe^Jane^19900101",
        StudyInstanceUID="study-a",
    )

    run = run_pipeline(source, tmp_path / "out", sanitise_requested=True)

    archives = list(run.archives_dir.glob("*.tar.gz"))
    assert len(archives) == 1
    assert "sub-01" not in archives[0].name


def test_run_pipeline_sanitise_numerical_label_mode(
    tmp_path: Path, make_dicom_file: Callable[..., Path]
) -> None:
    source = tmp_path / "export"
    make_dicom_file(source / "series" / "1.dcm", PatientID="sub-01", StudyInstanceUID="study-a")

    run = run_pipeline(
        source,
        tmp_path / "out",
        sanitise_requested=True,
        label_mode="numerical",
        subject_id="7",
    )

    archives = list(run.archives_dir.glob("*.tar.gz"))
    assert "sub-0007" in archives[0].name


def test_run_pipeline_sanitise_numerical_mode_without_subject_id_raises(
    tmp_path: Path, make_dicom_file: Callable[..., Path]
) -> None:
    source = tmp_path / "export"
    make_dicom_file(source / "series" / "1.dcm", PatientID="sub-01", StudyInstanceUID="study-a")

    with pytest.raises(RelabelError):
        run_pipeline(source, tmp_path / "out", sanitise_requested=True, label_mode="numerical")


def test_run_pipeline_writes_the_three_numbered_reports(
    tmp_path: Path, make_dicom_file: Callable[..., Path]
) -> None:
    source = tmp_path / "export"
    make_dicom_file(
        source / "series" / "1.dcm",
        PatientID="sub-01",
        StudyInstanceUID="study-a",
        StudyDate="20260101",
        StudyTime="120000",
    )

    run = run_pipeline(source, tmp_path / "out")

    report_dirs = list(run.reports_dir.iterdir())
    assert len(report_dirs) == 1
    assert report_dirs[0].name == "sub-01_20260101-120000_study-001"

    reports = {p.name for p in report_dirs[0].iterdir()}
    assert reports == {
        "stage-01-audit.csv",
        "stage-01-report.json",
        "stage-02-report.json",
        "stage-03-report.json",
    }

    finalise_report = json.loads((report_dirs[0] / "stage-03-report.json").read_text())
    assert finalise_report["subject_label"] == "sub-01"
    assert finalise_report["sanitised"] is False
    assert finalise_report["file_count"] == 1

    # reports/ survives the default working-file cleanup.
    assert not run.working_dir.exists()


def test_run_pipeline_reports_use_the_replacement_label_when_sanitised(
    tmp_path: Path, make_dicom_file: Callable[..., Path]
) -> None:
    source = tmp_path / "export"
    make_dicom_file(
        source / "series" / "1.dcm",
        PatientID="sub-01",
        StudyInstanceUID="study-a",
        StudyDate="20260101",
        StudyTime="120000",
    )

    run = run_pipeline(
        source, tmp_path / "out", sanitise_requested=True, label_mode="numerical", subject_id="7"
    )

    report_dirs = list(run.reports_dir.iterdir())
    assert report_dirs[0].name == "sub-0007_20260101-120000_study-001"


def test_run_pipeline_sanitised_reports_never_contain_the_real_patient_id(
    tmp_path: Path, make_dicom_file: Callable[..., Path]
) -> None:
    real_patient_id = "2026.09.14-13:38:31-DST-1.3.12.2.1107.5.99.3-VERY-REAL-ID"
    source = tmp_path / "export"
    make_dicom_file(
        source / "series" / "1.dcm",
        PatientID=real_patient_id,
        StudyInstanceUID="study-a",
        StudyDate="20260101",
        StudyTime="120000",
    )

    run = run_pipeline(
        source, tmp_path / "out", sanitise_requested=True, label_mode="numerical", subject_id="1"
    )

    for report_file in run.reports_dir.rglob("*.json"):
        assert real_patient_id not in report_file.read_text()
