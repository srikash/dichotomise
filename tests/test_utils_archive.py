"""Archive creation, checksums, verification and the pigz path."""

from __future__ import annotations

import hashlib
import shutil
import tarfile
from pathlib import Path

import pytest

import dichotomise.utils.archive as archive_module
from dichotomise.errors import ArchiveCreationError
from dichotomise.utils.archive import make_tarball, verify_archive


def _make_source(tmp_path: Path) -> Path:
    """A small source folder holding one file, for the archive tests."""
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


def test_source_digests_match_archived_file_contents(tmp_path: Path) -> None:
    source = _make_source(tmp_path) / "series-a" / "1.dcm"
    digests: dict[Path, str] = {}
    archive = archive_module.write_tarball(
        [(source, Path("1.dcm"))], tmp_path / "archive.tar.gz", None, digests
    )
    with tarfile.open(archive.path) as tar:
        member = tar.extractfile("1.dcm")
        assert member is not None
        assert digests[source] == hashlib.sha256(member.read()).hexdigest()


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


def test_make_tarball_falls_back_to_the_stdlib_codec_without_pigz(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(archive_module, "pigz_path", lambda: None)
    source = _make_source(tmp_path)

    archive = make_tarball(source, tmp_path / "study_archive.tar.gz")

    with tarfile.open(archive.path, "r:gz") as tar:
        assert "series-a/1.dcm" in tar.getnames()
    assert verify_archive(archive.path, archive.checksum_path) is True


def test_interrupted_pigz_archive_stops_the_compressor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    compressor = tmp_path / "pigz"
    compressor.write_text("#!/bin/sh\nexec sleep 30\n")
    compressor.chmod(0o755)
    monkeypatch.setattr(archive_module, "pigz_path", lambda: str(compressor))

    def interrupt(done: int, total: int) -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        make_tarball(_make_source(tmp_path), tmp_path / "archive.tar.gz", on_progress=interrupt)


@pytest.mark.skipif(shutil.which("pigz") is None, reason="pigz is not installed")
def test_make_tarball_uses_pigz_when_available(tmp_path: Path) -> None:
    source = _make_source(tmp_path)

    archive = make_tarball(source, tmp_path / "study_archive.tar.gz")

    with tarfile.open(archive.path, "r:gz") as tar:
        assert "series-a/1.dcm" in tar.getnames()
    assert verify_archive(archive.path, archive.checksum_path) is True


def test_make_tarball_raises_when_pigz_exits_with_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A fake "pigz" that reads its input (so tarfile never sees a broken
    # pipe) and then fails, to check the failure is surfaced rather than
    # silently producing a truncated or empty archive.
    fake_pigz = tmp_path / "fake-pigz"
    fake_pigz.write_text("#!/bin/sh\ncat >/dev/null\nexit 7\n")
    fake_pigz.chmod(0o755)
    monkeypatch.setattr(archive_module, "pigz_path", lambda: str(fake_pigz))
    source = _make_source(tmp_path)

    with pytest.raises(ArchiveCreationError, match="status 7"):
        make_tarball(source, tmp_path / "study_archive.tar.gz")


@pytest.fixture(params=["stdlib", "pigz"])
def codec(request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Run a test once with the stdlib codec and once with a stand-in `pigz` (plain `gzip -c`)."""
    if request.param == "stdlib":
        monkeypatch.setattr(archive_module, "pigz_path", lambda: None)
    else:
        fake = tmp_path / "gzip-as-pigz"
        fake.write_text("#!/bin/sh\nexec gzip -c -9\n")
        fake.chmod(0o755)
        monkeypatch.setattr(archive_module, "pigz_path", lambda: str(fake))
    return str(request.param)


def test_checksum_is_taken_while_writing_and_the_archive_is_not_read_back(
    codec: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: object, **kwargs: object) -> str:
        raise AssertionError("the archive was read back to be hashed")

    monkeypatch.setattr(archive_module.fs, "file_digest", forbidden)

    archive = make_tarball(_make_source(tmp_path), tmp_path / "study_archive.tar.gz")

    recorded = archive.checksum_path.read_text().split()[0]
    assert recorded == hashlib.sha256(archive.path.read_bytes()).hexdigest()
    with tarfile.open(archive.path, "r:gz") as tar:
        assert "series-a/1.dcm" in tar.getnames()


def test_a_write_error_while_compressing_is_reported(
    codec: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def disk_full(self: object, data: bytes) -> int:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(archive_module._HashingWriter, "write", disk_full)

    with pytest.raises(ArchiveCreationError, match="No space left"):
        make_tarball(_make_source(tmp_path), tmp_path / "study_archive.tar.gz")
