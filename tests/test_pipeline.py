from __future__ import annotations

import json
import re
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

    # Source and dichotomised archives now share one archives/ folder.
    source_archives = sorted(run.archives_dir.glob("*_source-archive_*.tar.gz"))
    final_archives = sorted(run.archives_dir.glob("*_dichotomised-archive_*.tar.gz"))
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


def test_run_pipeline_does_not_cross_contaminate_subjects_sharing_one_source_folder(
    tmp_path: Path, make_dicom_file: Callable[..., Path]
) -> None:
    # Two subjects' files interleaved in the exact same literal folder: since
    # capture() no longer copies each subject into a folder of their own,
    # audit's per-folder majority vote must still only ever see one
    # subject's own files, never the other subject's sharing that folder.
    source = tmp_path / "export"
    make_dicom_file(
        source / "mixed" / "a1.dcm",
        PatientID="sub-01",
        StudyInstanceUID="study-a",
        SeriesInstanceUID="series-a",
        SeriesNumber=1,
        InstanceNumber=1,
    )
    make_dicom_file(
        source / "mixed" / "a2.dcm",
        PatientID="sub-01",
        StudyInstanceUID="study-a",
        SeriesInstanceUID="series-a",
        SeriesNumber=1,
        InstanceNumber=2,
    )
    make_dicom_file(
        source / "mixed" / "b1.dcm",
        PatientID="sub-02",
        StudyInstanceUID="study-b",
        SeriesInstanceUID="series-b",
        SeriesNumber=2,
        InstanceNumber=1,
    )
    make_dicom_file(
        source / "mixed" / "b2.dcm",
        PatientID="sub-02",
        StudyInstanceUID="study-b",
        SeriesInstanceUID="series-b",
        SeriesNumber=2,
        InstanceNumber=2,
    )

    run = run_pipeline(source, tmp_path / "out")

    assert len(list(run.archives_dir.glob("*_dichotomised-archive_*.tar.gz"))) == 2
    for report_dir in run.reports_dir.iterdir():
        audit_report = json.loads((report_dir / "stage-01-report.json").read_text())
        assert audit_report["misfiled_count"] == 0
        assert audit_report["duplicate_count"] == 0


def test_run_pipeline_keeps_working_files_when_requested(
    tmp_path: Path, make_dicom_file: Callable[..., Path]
) -> None:
    source = tmp_path / "export"
    make_dicom_file(source / "series" / "1.dcm", PatientID="sub-01", StudyInstanceUID="study-a")

    run = run_pipeline(source, tmp_path / "out", keep_working_files=True)

    assert run.working_dir.exists()


def test_run_pipeline_keeps_the_final_tree_unzipped_when_requested(
    tmp_path: Path, make_dicom_file: Callable[..., Path]
) -> None:
    source = tmp_path / "export"
    make_dicom_file(
        source / "021-DWI" / "1.dcm",
        PatientID="sub-01",
        StudyInstanceUID="study-a",
        SeriesInstanceUID="series-a",
        SeriesNumber=21,
    )

    run = run_pipeline(source, tmp_path / "out", keep_unzipped=True)

    final_dirs = list(run.final_dir.iterdir())
    assert len(final_dirs) == 1
    unzipped_files = [p for p in final_dirs[0].rglob("*") if p.is_file()]
    assert len(unzipped_files) == 1
    assert unzipped_files[0].suffix == ".dcm"
    # Independent of keep_working_files: the working tree is still cleaned up.
    assert not run.working_dir.exists()


def test_run_pipeline_without_keep_unzipped_creates_no_final_dir(
    tmp_path: Path, make_dicom_file: Callable[..., Path]
) -> None:
    source = tmp_path / "export"
    make_dicom_file(source / "series" / "1.dcm", PatientID="sub-01", StudyInstanceUID="study-a")

    run = run_pipeline(source, tmp_path / "out")

    assert not run.final_dir.exists()


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

    # The source archive always keeps the real PatientID; only the
    # dichotomised archive is sanitised.
    archives = list(run.archives_dir.glob("*_dichotomised-archive_*.tar.gz"))
    assert len(archives) == 1
    assert "sub-01" not in archives[0].name
    source_archives = list(run.archives_dir.glob("*_source-archive_*.tar.gz"))
    assert len(source_archives) == 1
    assert "sub-01" in source_archives[0].name


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

    archives = list(run.archives_dir.glob("*_dichotomised-archive_*.tar.gz"))
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
    assert re.fullmatch(r"sub-01_[0-9a-f]{6}", report_dirs[0].name)

    reports = {p.name for p in report_dirs[0].iterdir()}
    assert reports == {
        "stage-01-audit.csv",
        "stage-01-report.json",
        "stage-02-report.json",
        "stage-03-report.json",
        "source-manifest.csv",
        "retained-manifest.csv",
    }

    finalise_report = json.loads((report_dirs[0] / "stage-03-report.json").read_text())
    assert finalise_report["subject_label"] == "sub-01"
    assert finalise_report["sanitised"] is False
    assert finalise_report["file_count"] == 1

    # reports/ survives the default working-file cleanup.
    assert not run.working_dir.exists()


def test_run_pipeline_archives_review_files_renamed_but_unsanitised(
    tmp_path: Path, make_dicom_file: Callable[..., Path]
) -> None:
    source = tmp_path / "export"
    make_dicom_file(
        source / "021-DWI" / "1.dcm",
        PatientID="sub-01",
        StudyInstanceUID="study-a",
        SeriesInstanceUID="series-a",
        SeriesNumber=21,
        InstanceNumber=1,
    )
    make_dicom_file(
        source / "021-DWI" / "2.dcm",
        PatientID="sub-01",
        StudyInstanceUID="study-a",
        SeriesInstanceUID="series-a",
        SeriesNumber=21,
        InstanceNumber=1,
    )

    run = run_pipeline(source, tmp_path / "out")

    review_archives = list(run.archives_dir.glob("*_review-archive_*.tar.gz"))
    assert len(review_archives) == 1
    with tarfile.open(review_archives[0], "r:gz") as tar:
        names = [m.name for m in tar.getmembers() if m.isfile()]
    assert any(name.endswith(".dcm") for name in names)

    reports_dir = next(run.reports_dir.iterdir())
    sift_report = json.loads((reports_dir / "stage-02-report.json").read_text())
    assert sift_report["review_archive"] is not None
    assert sift_report["review_archive_sanitised"] is False
    assert not run.working_dir.exists()


def test_run_pipeline_sanitised_run_deidentifies_review_archive(
    tmp_path: Path, make_dicom_file: Callable[..., Path]
) -> None:
    real_patient_id = "VERY-REAL-PATIENT-ID"
    source = tmp_path / "export"
    make_dicom_file(
        source / "021-DWI" / "1.dcm",
        PatientID=real_patient_id,
        PatientName="Doe^Jane",
        StudyInstanceUID="study-a",
        SeriesInstanceUID="series-a",
        SeriesNumber=21,
        InstanceNumber=1,
    )
    make_dicom_file(
        source / "021-DWI" / "2.dcm",
        PatientID=real_patient_id,
        PatientName="Doe^Jane",
        StudyInstanceUID="study-a",
        SeriesInstanceUID="series-a",
        SeriesNumber=21,
        InstanceNumber=1,
    )

    run = run_pipeline(
        source,
        tmp_path / "out",
        sanitise_requested=True,
        label_mode="numerical",
        subject_id="7",
    )

    review_archives = list(run.archives_dir.glob("*_review-archive_*.tar.gz"))
    assert len(review_archives) == 1
    with tarfile.open(review_archives[0], "r:gz") as tar:
        member = next(m for m in tar.getmembers() if m.isfile())
        extracted = tar.extractfile(member)
        assert extracted is not None
        content = extracted.read()
    assert real_patient_id.encode() not in content

    reports_dir = next(run.reports_dir.iterdir())
    sift_report = json.loads((reports_dir / "stage-02-report.json").read_text())
    assert sift_report["review_archive_sanitised"] is True


def test_run_pipeline_creates_no_review_archive_without_review_files(
    tmp_path: Path, make_dicom_file: Callable[..., Path]
) -> None:
    source = tmp_path / "export"
    make_dicom_file(source / "series" / "1.dcm", PatientID="sub-01", StudyInstanceUID="study-a")

    run = run_pipeline(source, tmp_path / "out")

    assert list(run.archives_dir.glob("*_review-archive_*")) == []


def test_run_pipeline_writes_manifests_for_retained_and_review_files(
    tmp_path: Path, make_dicom_file: Callable[..., Path]
) -> None:
    source = tmp_path / "export"
    make_dicom_file(
        source / "021-DWI" / "1.dcm",
        PatientID="sub-01",
        StudyInstanceUID="study-a",
        SeriesInstanceUID="series-a",
        SeriesNumber=21,
        InstanceNumber=1,
    )
    make_dicom_file(
        source / "021-DWI" / "2.dcm",
        PatientID="sub-01",
        StudyInstanceUID="study-a",
        SeriesInstanceUID="series-a",
        SeriesNumber=21,
        InstanceNumber=1,
    )

    run = run_pipeline(source, tmp_path / "out")

    reports_dir = next(run.reports_dir.iterdir())
    assert (reports_dir / "source-manifest.csv").exists()
    assert (reports_dir / "retained-manifest.csv").exists()
    assert (reports_dir / "review-manifest.csv").exists()


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
    assert re.fullmatch(r"sub-0007_[0-9a-f]{6}", report_dirs[0].name)


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
