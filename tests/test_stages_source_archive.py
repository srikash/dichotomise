from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from dichotomise.run import start_run
from dichotomise.stages.capture import CapturedSubject
from dichotomise.stages.source_archive import source_archive
from dichotomise.utils.archive import verify_archive


def test_source_archive_names_the_archive_from_run_subject_and_scan_datetime(
    tmp_path: Path,
) -> None:
    captured_dir = tmp_path / "captured"
    (captured_dir / "series").mkdir(parents=True)
    (captured_dir / "series" / "1.dcm").write_bytes(b"scan content")

    run = start_run(tmp_path / "out", now=datetime(2026, 9, 22, 14, 30, 12, tzinfo=UTC))
    subject = CapturedSubject(
        subject_id="sub-01",
        patient_name="Doe^Jane^19900101",
        study_instance_uid="study-a",
        scan_date="20260101",
        scan_time="120000",
        directory=captured_dir,
    )

    archive = source_archive(subject, run)

    expected_stem = "20260922T143012Z_sub-01_20260101-120000_source-archive"
    assert archive.path == run.source_archive_dir / f"{expected_stem}.tar.gz"
    assert archive.checksum_path == run.source_archive_dir / f"{expected_stem}.sha256"
    assert archive.path.exists()
    assert verify_archive(archive.path, archive.checksum_path) is True
