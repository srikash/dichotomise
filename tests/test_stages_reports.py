from __future__ import annotations

import csv
import json
from dataclasses import replace
from pathlib import Path

from dichotomise.pydcm.read import DicomMetadata
from dichotomise.stages.audit import AuditedFile, AuditResult
from dichotomise.stages.capture import CapturedSubject
from dichotomise.stages.finalise import FinaliseResult
from dichotomise.stages.rectify import RectifyResult
from dichotomise.stages.reports import write_audit_report, write_finalise_report, write_sift_report
from dichotomise.stages.sift import ReviewFile, SiftResult
from dichotomise.utils.archive import Archive


def _subject(directory: Path) -> CapturedSubject:
    return CapturedSubject(
        subject_id="sub-01",
        patient_name="Doe^Jane^19900101",
        study_instance_uid="study-a",
        scan_date="20260101",
        scan_time="120000",
        directory=directory,
    )


def _metadata(path: Path) -> DicomMetadata:
    return DicomMetadata(
        path=path,
        patient_id="sub-01",
        patient_name="Doe^Jane^19900101",
        study_instance_uid="study-a",
        series_instance_uid="series-a",
        sop_instance_uid="sop-1",
        series_number=21,
        series_description="diffusion",
        protocol_name="DWI",
        instance_number=1,
        echo_number=1,
        study_date="20260101",
        study_time="120000",
    )


def test_write_audit_report_records_counts_and_flagged_files(tmp_path: Path) -> None:
    capture_dir = tmp_path / "capture"
    ok_path = capture_dir / "021-DWI" / "1.dcm"
    dup_path = capture_dir / "021-DWI" / "2.dcm"
    subject = _subject(capture_dir)
    audit_result = AuditResult(
        subject=subject,
        files=[
            AuditedFile(_metadata(ok_path), is_duplicate=False, is_misfiled=False),
            AuditedFile(_metadata(dup_path), is_duplicate=True, is_misfiled=False),
        ],
    )
    reports_dir = tmp_path / "reports" / "sub-0005_20260101-120000"

    report_path = write_audit_report(audit_result, reports_dir, subject_label="sub-0005")

    assert report_path == reports_dir / "stage-01-report.json"
    data = json.loads(report_path.read_text())
    assert data["stage"] == "audit"
    # Never the raw PatientID here: this report can sit inside a sanitised
    # run's reports/ folder, and its content must respect that too.
    assert data["subject_label"] == "sub-0005"
    assert "subject_id" not in data
    assert data["total_files"] == 2
    assert data["duplicate_count"] == 1
    assert data["misfiled_count"] == 0
    assert data["duplicates"] == ["021-DWI"]
    assert data["misfiled"] == []
    with (reports_dir / "stage-01-audit.csv").open(newline="") as report_file:
        assert list(csv.DictReader(report_file)) == [
            {
                "series_folder": "021-DWI",
                "dicom_count": "2",
                "duplicate_count": "1",
                "misfiled_count": "0",
                "metadata_inconsistencies": "",
                "status": "flagged",
            }
        ]


def test_write_audit_report_flags_metadata_inconsistencies_within_a_series(
    tmp_path: Path,
) -> None:
    capture_dir = tmp_path / "capture"
    first_file = _metadata(capture_dir / "021-DWI" / "1.dcm")
    second_file = replace(
        first_file,
        path=capture_dir / "021-DWI" / "2.dcm",
        patient_name="Doe^John^19850101",
    )
    audit_result = AuditResult(
        subject=_subject(capture_dir),
        files=[
            AuditedFile(first_file, is_duplicate=False, is_misfiled=False),
            AuditedFile(second_file, is_duplicate=False, is_misfiled=False),
        ],
    )

    report_path = write_audit_report(audit_result, tmp_path / "reports", subject_label="sub-01")

    data = json.loads(report_path.read_text())
    assert data["metadata_inconsistency_count"] == 1
    assert data["series"][0]["metadata_inconsistencies"] == "PatientName"
    with (report_path.parent / "stage-01-audit.csv").open(newline="") as report_file:
        row = next(iter(csv.DictReader(report_file)))
    assert row["metadata_inconsistencies"] == "PatientName"


def test_write_sift_report_records_retained_and_review_counts(tmp_path: Path) -> None:
    capture_dir = tmp_path / "capture"
    subject = _subject(capture_dir)
    retained_dir = tmp_path / "sift" / "retained"
    review_dir = tmp_path / "sift" / "review"
    review_path = review_dir / "021-DWI" / "2.dcm"
    sift_result = SiftResult(
        subject=subject,
        retained=[_metadata(retained_dir / "021-DWI" / "1.dcm")],
        retained_dir=retained_dir,
        review=[ReviewFile(_metadata(review_path), "duplicate")],
        review_dir=review_dir,
    )
    reports_dir = tmp_path / "reports" / "sub-01_20260101-120000"

    report_path = write_sift_report(sift_result, reports_dir)

    assert report_path == reports_dir / "stage-02-report.json"
    data = json.loads(report_path.read_text())
    assert data["stage"] == "sift"
    assert data["retained_count"] == 1
    assert data["review_count"] == 1
    assert data["review"] == [{"file": "021-DWI/2.dcm", "reason": "duplicate"}]


def test_write_finalise_report_records_the_archive_and_sanitise_state(tmp_path: Path) -> None:
    capture_dir = tmp_path / "capture"
    subject = _subject(capture_dir)
    archive_path = tmp_path / "archives" / "run_sub-0005_archive.tar.gz"
    checksum_path = tmp_path / "archives" / "run_sub-0005_archive.sha256"
    archive_path.parent.mkdir(parents=True)
    archive_path.write_bytes(b"fake archive")
    checksum_path.write_text("abc123\n")
    finalise_result = FinaliseResult(
        subject=subject,
        subject_label="sub-0005",
        archive=Archive(path=archive_path, checksum_path=checksum_path),
    )
    reports_dir = tmp_path / "reports" / "sub-0005_20260101-120000"

    report_path = write_finalise_report(
        finalise_result, reports_dir, file_count=3, sanitised=True, sanitise_level="standard"
    )

    assert report_path == reports_dir / "stage-03-report.json"
    data = json.loads(report_path.read_text())
    assert data["stage"] == "finalise"
    assert data["subject_label"] == "sub-0005"
    assert data["archive"] == archive_path.name
    assert data["checksum"] == "abc123"
    assert data["file_count"] == 3
    assert data["sanitised"] is True
    assert data["sanitise_level"] == "standard"


def test_write_finalise_report_includes_first_dicom_names_for_each_series(tmp_path: Path) -> None:
    capture_dir = tmp_path / "capture"
    subject = _subject(capture_dir)
    original_file = _metadata(capture_dir / "raw-series" / "IM-0001-0001.dcm")
    rectified_dir = tmp_path / "rectify"
    rectified_file = replace(
        original_file,
        path=rectified_dir / "021_diffusion" / "021_series-a_0001_e01.dcm",
    )
    audit_result = AuditResult(
        subject=subject,
        files=[AuditedFile(original_file, is_duplicate=False, is_misfiled=False)],
    )
    rectify_result = RectifyResult(
        subject=subject,
        rectified_dir=rectified_dir,
        files=[rectified_file],
    )
    archive_path = tmp_path / "archives" / "run_sub-01_archive.tar.gz"
    checksum_path = tmp_path / "archives" / "run_sub-01_archive.sha256"
    archive_path.parent.mkdir(parents=True)
    archive_path.write_bytes(b"fake archive")
    checksum_path.write_text("abc123\n")
    finalise_result = FinaliseResult(
        subject=subject,
        subject_label="sub-01",
        archive=Archive(path=archive_path, checksum_path=checksum_path),
    )

    report_path = write_finalise_report(
        finalise_result,
        tmp_path / "reports",
        file_count=1,
        sanitised=False,
        sanitise_level=None,
        audit_result=audit_result,
        rectify_result=rectify_result,
    )

    data = json.loads(report_path.read_text())
    assert data["series_inventory"] == [
        {
            "series_number": 21,
            "series_description": "diffusion",
            "series_instance_uid": "series-a",
            "source_file_count": 1,
            "archived_file_count": 1,
            "review_file_count": 0,
            "first_dicom_before": "IM-0001-0001.dcm",
            "first_dicom_after": "021_series-a_0001_e01.dcm",
        }
    ]
