"""Archive creation, checksums, verification and the pigz path."""

from __future__ import annotations

import hashlib
import os
import shutil
import tarfile
from pathlib import Path

import pytest

import dichotomise.utils.archive as archive_module
from dichotomise.errors import ArchiveCreationError
from dichotomise.utils.archive import make_tarball, verify_archive
from dichotomise.utils.jobs import set_jobs


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


def _big_source(tmp_path: Path) -> Path:
    """Two files of incompressible bytes, so the compressed stream is written in several pieces."""
    source = tmp_path / "source"
    (source / "series-a").mkdir(parents=True)
    for name in ("1.dcm", "2.dcm"):
        (source / "series-a" / name).write_bytes(os.urandom(2_000_000))
    return source


def test_a_write_error_part_way_through_the_archive_is_reported(
    codec: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_init = archive_module._HashingWriter.__init__

    class DiskFillsUp:
        """Takes the first write, then reports a full disk, so the failure is mid-stream."""

        def __init__(self, target: object) -> None:
            self.target = target
            self.writes = 0

        def write(self, data: bytes) -> int:
            self.writes += 1
            if self.writes > 1:
                raise OSError(28, "No space left on device")
            return self.target.write(data)  # type: ignore[attr-defined, no-any-return]

        def flush(self) -> None:
            self.target.flush()  # type: ignore[attr-defined]

    def init(self: archive_module._HashingWriter, target: object, archive_path: Path) -> None:
        real_init(self, DiskFillsUp(target), archive_path)  # type: ignore[arg-type]

    monkeypatch.setattr(archive_module._HashingWriter, "__init__", init)

    with pytest.raises(ArchiveCreationError, match="No space left"):
        make_tarball(_big_source(tmp_path), tmp_path / "study_archive.tar.gz")


def test_the_writer_turns_os_errors_into_archive_errors(tmp_path: Path) -> None:
    class FullDisk:
        def write(self, data: bytes) -> int:
            raise OSError(28, "No space left on device")

        def flush(self) -> None:
            raise OSError(28, "No space left on device")

    writer = archive_module._HashingWriter(FullDisk(), tmp_path / "a.tar.gz")  # type: ignore[arg-type]
    with pytest.raises(ArchiveCreationError, match="No space left"):
        writer.write(b"data")
    with pytest.raises(ArchiveCreationError, match="No space left"):
        writer.flush()


def test_a_source_that_vanishes_mid_archive_is_not_reported_as_a_write_error(
    codec: str, tmp_path: Path
) -> None:
    source = _big_source(tmp_path)

    def remove_second(done: int, total: int) -> None:
        (source / "series-a" / "2.dcm").unlink(missing_ok=True)

    with pytest.raises(OSError) as raised:
        make_tarball(source, tmp_path / "study_archive.tar.gz", on_progress=remove_second)
    assert "Could not write" not in str(raised.value)


def test_a_full_disk_stops_the_archive_early(
    codec: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The run stops at the failed write, not after every file is compressed."""
    source = _big_source(tmp_path)
    for name in ("3.dcm", "4.dcm", "5.dcm"):
        (source / "series-a" / name).write_bytes(os.urandom(2_000_000))
    added: list[int] = []

    def full_disk(self: archive_module._HashingWriter, data: bytes) -> int:
        raise ArchiveCreationError("Could not write: No space left on device")

    monkeypatch.setattr(archive_module._HashingWriter, "write", full_disk)

    with pytest.raises(ArchiveCreationError, match="No space left"):
        make_tarball(
            source,
            tmp_path / "study_archive.tar.gz",
            on_progress=lambda done, total: added.append(done),
        )
    assert len(added) < 5


def test_pigz_gets_the_jobs_count_only_when_one_was_given() -> None:
    assert "-p" not in archive_module._pigz_command("pigz")
    set_jobs(3)
    assert archive_module._pigz_command("pigz")[-2:] == ["-p", "3"]
