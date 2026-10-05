from __future__ import annotations

import tarfile
from pathlib import Path

from dichotomise.utils.archive import make_tarball, make_tarball_from_files, verify_archive


def _make_source(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    (source / "series-a").mkdir(parents=True)
    (source / "series-a" / "1.dcm").write_bytes(b"scan content")
    return source


def test_make_tarball_reports_progress_once_per_file_up_to_the_total(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "series-a").mkdir(parents=True)
    (source / "series-a" / "1.dcm").write_bytes(b"12345")
    (source / "series-a" / "2.dcm").write_bytes(b"1234567890")
    archive_path = tmp_path / "out" / "study_archive.tar.gz"
    updates: list[tuple[int, int]] = []

    def record(done: int, total: int) -> None:
        updates.append((done, total))

    make_tarball(source, archive_path, on_progress=record)

    assert updates == [(5, 15), (15, 15)]


def test_make_tarball_from_files_reports_progress(tmp_path: Path) -> None:
    source = tmp_path / "export"
    file_a = source / "a.dcm"
    file_a.parent.mkdir(parents=True)
    file_a.write_bytes(b"1234567890")
    archive_path = tmp_path / "study_archive.tar.gz"
    updates: list[tuple[int, int]] = []

    def record(done: int, total: int) -> None:
        updates.append((done, total))

    make_tarball_from_files([file_a], source, archive_path, on_progress=record)

    assert updates == [(10, 10)]


def test_make_tarball_creates_an_archive_containing_the_original_files(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    archive_path = tmp_path / "out" / "study_archive.tar.gz"

    archive = make_tarball(source, archive_path)

    assert archive.path == archive_path
    assert archive.path.exists()
    with tarfile.open(archive.path, "r:gz") as tar:
        names = tar.getnames()
    assert "series-a/1.dcm" in names


def test_make_tarball_does_not_duplicate_files_nested_inside_folders(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    archive_path = tmp_path / "study_archive.tar.gz"

    archive = make_tarball(source, archive_path)

    with tarfile.open(archive.path, "r:gz") as tar:
        file_names = [member.name for member in tar.getmembers() if member.isfile()]

    assert file_names.count("series-a/1.dcm") == 1


def test_make_tarball_writes_a_checksum_sidecar_next_to_the_archive(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    archive_path = tmp_path / "study_archive.tar.gz"

    archive = make_tarball(source, archive_path)

    assert archive.checksum_path == tmp_path / "study_archive.sha256"
    assert archive.checksum_path.exists()
    assert len(archive.checksum_path.read_text().strip()) == 64  # a sha256 hex digest


def test_verify_archive_accepts_an_untampered_archive(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    archive = make_tarball(source, tmp_path / "study_archive.tar.gz")

    assert verify_archive(archive.path, archive.checksum_path) is True


def test_verify_archive_rejects_a_tampered_archive(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    archive = make_tarball(source, tmp_path / "study_archive.tar.gz")

    with archive.path.open("ab") as handle:
        handle.write(b"unexpected extra bytes")

    assert verify_archive(archive.path, archive.checksum_path) is False
