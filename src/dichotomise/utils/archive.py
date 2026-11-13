"""make_tarball() and verify_archive(): tar.gz creation with a sha256 sidecar.

The checksum is taken from the compressed bytes as they are written, so an archive is never
read back just to be hashed."""

from __future__ import annotations

import gzip
import hashlib
import shutil
import subprocess
import tarfile
import threading
from collections.abc import Callable, Iterable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from dichotomise.errors import ArchiveCreationError
from dichotomise.utils import fs
from dichotomise.utils.jobs import get_jobs

ProgressCallback = Callable[[int, int], None]


class _HashingReader:
    """Wrap a file so everything read from it is also hashed, for a checksum made in one pass."""

    def __init__(self, source: BinaryIO) -> None:
        self.source = source
        self.hasher = hashlib.sha256()

    def read(self, size: int = -1) -> bytes:
        """Read from the wrapped file and add the bytes to the running hash."""
        data = self.source.read(size)
        self.hasher.update(data)
        return data


class _HashingWriter:
    """Wrap the archive file so everything written to it is also hashed (the archive's checksum).

    A failure to write the archive (a full disk, say) becomes an `ArchiveCreationError` here, at
    the one place archive bytes are written, so it is not mistaken for a source-file error.
    """

    def __init__(self, target: BinaryIO, archive_path: Path) -> None:
        self.target = target
        self.archive_path = archive_path
        self.hasher = hashlib.sha256()

    def write(self, data: bytes) -> int:
        """Write to the wrapped file and add the bytes to the running hash."""
        self.hasher.update(data)
        try:
            return self.target.write(data)
        except OSError as error:
            raise ArchiveCreationError(f"Could not write {self.archive_path}: {error}") from error

    def flush(self) -> None:
        """Flush the wrapped file; a full disk can surface only here."""
        try:
            self.target.flush()
        except OSError as error:
            raise ArchiveCreationError(f"Could not write {self.archive_path}: {error}") from error


# gzip's own default, kept the same whichever compressor ends up writing.
_GZIP_COMPRESSLEVEL = 9


def pigz_path() -> str | None:
    """Return the path to `pigz` if it's on PATH, else None.

    Exposed so a caller (e.g. the CLI) can report once, up front, whether
    the faster, parallel-gzip path will be used for this run's archives.
    """
    return shutil.which("pigz")


@dataclass(frozen=True)
class Archive:
    """An archive file and the checksum sidecar that verifies it."""

    path: Path
    checksum_path: Path


def _checksum_path_for(archive_path: Path) -> Path:
    """The `.sha256` sidecar path that goes with an archive path."""
    name = archive_path.name
    if name.endswith(".tar.gz"):
        name = name[: -len(".tar.gz")]
    return archive_path.with_name(f"{name}.sha256")


def _finish_archive(archive_path: Path, digest: str) -> Archive:
    """Write the checksum sidecar for a finished archive, from the digest taken as it was written.

    No re-read follows: it would cost a full extra read of every archive, and straight after
    writing it is served from memory, so it would prove nothing about the disk.
    `verify_archive` checks an archive later, against its sidecar.
    """
    checksum_path = _checksum_path_for(archive_path)
    checksum_path.write_text(digest + "\n")
    return Archive(path=archive_path, checksum_path=checksum_path)


def make_tarball(
    source_dir: Path, archive_path: Path, *, on_progress: ProgressCallback | None = None
) -> Archive:
    """Compress everything under `source_dir` into `archive_path`, plus a checksum file.

    The checksum sidecar sits next to the archive, named after it with a
    `.sha256` extension in place of `.tar.gz`. `on_progress`, if given, is
    called after each file is added with (bytes added so far, total bytes
    to add). Progress is coarse-grained (per file, not per chunk), since tarfile adds
    a whole file in one call.
    """
    items = sorted(source_dir.rglob("*"))
    return write_tarball(
        ((item, item.relative_to(source_dir)) for item in items), archive_path, on_progress
    )


def _add_entries(
    tar: tarfile.TarFile,
    entries: Sequence[tuple[Path, Path]],
    total_bytes: int,
    on_progress: ProgressCallback | None,
    source_digests: dict[Path, str] | None = None,
) -> None:
    """Add each (path, arcname) entry to an already-open `tar`.

    Entries that are directories count toward neither total nor progress
    bytes (they have no content of their own), so `on_progress` only ever
    reports real file bytes.
    """
    written_bytes = 0
    for path, arcname in entries:
        # recursive=False: each entry already comes from our own walk (files
        # and folders both), so letting tar.add() recurse into a folder
        # would add every file inside it a second time.
        if source_digests is not None and path.is_file():
            before = path.stat()
            info = tar.gettarinfo(str(path), arcname=str(arcname))
            with path.open("rb") as source:
                reader = _HashingReader(source)
                tar.addfile(info, reader)
            after = path.stat()
            if (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            ) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ):
                raise ArchiveCreationError(f"Source changed during archiving: {path}")
            source_digests[path] = reader.hasher.hexdigest()
        else:
            tar.add(path, arcname=arcname, recursive=False)
        if path.is_file():
            written_bytes += path.stat().st_size
            if on_progress is not None:
                on_progress(written_bytes, total_bytes)


def _drain_to_file(
    stream: BinaryIO,
    out_file: _HashingWriter,
    failures: list[ArchiveCreationError],
    process: subprocess.Popen[bytes],
) -> None:
    """Copy `stream` into the hashing writer until it ends; on a write error, stop `pigz`.

    Stopping `pigz` breaks the pipe the main thread is feeding, so the run ends at once instead
    of after the whole subject is compressed. The rest of the output is read and dropped so that
    nothing blocks; the main thread reports the first error.
    """
    while chunk := stream.read(1024 * 1024):
        if not failures:
            try:
                out_file.write(chunk)
            except ArchiveCreationError as error:
                failures.append(error)
                process.terminate()


def _pigz_command(pigz: str) -> list[str]:
    """The `pigz` command line, with `-p N` only when `--jobs` was given."""
    command = [pigz, "-c", f"-{_GZIP_COMPRESSLEVEL}"]
    if (jobs := get_jobs()) is not None:
        command += ["-p", str(jobs)]
    return command


def _write_tarball_with_pigz(
    pigz: str,
    entries: Sequence[tuple[Path, Path]],
    archive_path: Path,
    total_bytes: int,
    on_progress: ProgressCallback | None,
    source_digests: dict[Path, str] | None = None,
) -> str:
    """Pipe an uncompressed tar stream through `pigz` (parallel gzip) to `archive_path`.

    `tarfile` writes the uncompressed tar stream straight into the `pigz`
    subprocess's stdin (mode "w|": no seeking, suitable for a pipe); `pigz`
    does the gzip compression itself, in parallel across CPU cores. A second thread
    copies its output into the archive file and hashes it. Returns the archive's SHA-256.
    """
    with archive_path.open("wb") as raw_file:
        out_file = _HashingWriter(raw_file, archive_path)
        process = subprocess.Popen(
            _pigz_command(pigz), stdin=subprocess.PIPE, stdout=subprocess.PIPE
        )
        stdin, stdout = process.stdin, process.stdout
        assert stdin is not None and stdout is not None  # guaranteed by the pipes above
        failures: list[ArchiveCreationError] = []
        drain = threading.Thread(target=_drain_to_file, args=(stdout, out_file, failures, process))
        drain.start()
        try:
            with tarfile.open(fileobj=stdin, mode="w|") as tar:
                _add_entries(tar, entries, total_bytes, on_progress, source_digests)
        except BaseException as error:  # includes Ctrl-C: never leave pigz running after one
            process.terminate()
            with suppress(OSError):
                stdin.close()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            drain.join()
            stdout.close()
            if failures and isinstance(error, OSError):  # the pipe broke because pigz was stopped
                raise failures[0] from error
            raise
        else:
            stdin.close()
            drain.join()
            stdout.close()
            return_code = process.wait()
        if failures:
            raise failures[0]
        if return_code != 0:
            raise ArchiveCreationError(
                f"pigz exited with status {return_code} while writing {archive_path}"
            )
        out_file.flush()
    return out_file.hasher.hexdigest()


def write_tarball(
    entries: Iterable[tuple[Path, Path]],
    archive_path: Path,
    on_progress: ProgressCallback | None,
    source_digests: dict[Path, str] | None = None,
) -> Archive:
    """Write every (path, arcname) entry into a new tarball at `archive_path`.

    Prefers `pigz` for the gzip compression when it's on PATH. It
    parallelises across CPU cores, where the stdlib `gzip`/`zlib` codec
    `tarfile` otherwise uses is single-threaded. Without `pigz` it falls back to the
    stdlib path. Either way, the result is an ordinary .tar.gz.
    """
    sorted_entries = list(entries)
    total_bytes = sum(path.stat().st_size for path, _ in sorted_entries if path.is_file())
    archive_path.parent.mkdir(parents=True, exist_ok=True)

    pigz = pigz_path()
    if pigz is not None:
        digest = _write_tarball_with_pigz(
            pigz, sorted_entries, archive_path, total_bytes, on_progress, source_digests
        )
    else:
        with archive_path.open("wb") as raw_file:
            out_file = _HashingWriter(raw_file, archive_path)
            gz = gzip.GzipFile(archive_path.name, "wb", _GZIP_COMPRESSLEVEL, out_file)
            with gz, tarfile.open(fileobj=gz, mode="w") as tar:
                _add_entries(tar, sorted_entries, total_bytes, on_progress, source_digests)
            out_file.flush()
        digest = out_file.hasher.hexdigest()

    return _finish_archive(archive_path, digest)


def verify_archive(archive_path: Path, checksum_path: Path) -> bool:
    """Return whether `archive_path`'s current contents match its recorded checksum."""
    expected = checksum_path.read_text().split()[0]
    return fs.file_digest(archive_path) == expected
