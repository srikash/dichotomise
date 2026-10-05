"""make_tarball() and verify_archive(): tar.gz creation with a sha256 sidecar."""

from __future__ import annotations

import hashlib
import tarfile
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from dichotomise.errors import ArchiveVerificationError

ProgressCallback = Callable[[int, int], None]


@dataclass(frozen=True)
class Archive:
    """An archive file and the checksum sidecar that verifies it."""

    path: Path
    checksum_path: Path


def _checksum_path_for(archive_path: Path) -> Path:
    name = archive_path.name
    if name.endswith(".tar.gz"):
        name = name[: -len(".tar.gz")]
    return archive_path.with_name(f"{name}.sha256")


def _sha256_of(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _finish_archive(archive_path: Path) -> Archive:
    """Write the checksum sidecar and verify the archive before returning it."""
    checksum_path = _checksum_path_for(archive_path)
    checksum_path.write_text(_sha256_of(archive_path) + "\n")
    archive = Archive(path=archive_path, checksum_path=checksum_path)
    if not verify_archive(archive.path, archive.checksum_path):
        raise ArchiveVerificationError(f"Archive verification failed: {archive.path}")
    return archive


def make_tarball(
    source_dir: Path, archive_path: Path, *, on_progress: ProgressCallback | None = None
) -> Archive:
    """Compress everything under `source_dir` into `archive_path`, plus a checksum file.

    The checksum sidecar sits next to the archive, named after it with a
    `.sha256` extension in place of `.tar.gz`. `on_progress`, if given, is
    called after each file is added with (bytes added so far, total bytes
    to add) -- coarse-grained (per file, not per chunk), since tarfile adds
    a whole file in one call.
    """
    items = sorted(source_dir.rglob("*"))
    return _write_tarball(
        ((item, item.relative_to(source_dir)) for item in items), archive_path, on_progress
    )


def make_tarball_from_files(
    files: Sequence[Path],
    root: Path,
    archive_path: Path,
    *,
    on_progress: ProgressCallback | None = None,
) -> Archive:
    """Compress a scattered set of files, kept relative to `root`, into `archive_path`.

    Unlike `make_tarball()`, `files` need not fill all of `root` or even sit
    under one common folder beneath it; each is added individually, by its
    path relative to `root`, with no separate directory entries (a plain
    extract still recreates the needed folders). This lets one subject's
    files be archived straight from a shared, multi-subject source
    directory, without first copying that subject's files into a folder of
    their own.
    """
    sorted_files = sorted(files)
    return _write_tarball(
        ((path, path.relative_to(root)) for path in sorted_files), archive_path, on_progress
    )


def _write_tarball(
    entries: Iterable[tuple[Path, Path]],
    archive_path: Path,
    on_progress: ProgressCallback | None,
) -> Archive:
    """Add each (path, arcname) entry to a new tarball at `archive_path`.

    Entries that are directories count toward neither total nor progress
    bytes (they have no content of their own), so `on_progress` only ever
    reports real file bytes.
    """
    entries = list(entries)
    total_bytes = sum(path.stat().st_size for path, _ in entries if path.is_file())
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    written_bytes = 0
    with tarfile.open(archive_path, "w:gz") as tar:
        for path, arcname in entries:
            # recursive=False: each entry already comes from our own walk
            # (files and folders both), so letting tar.add() recurse into a
            # folder would add every file inside it a second time.
            tar.add(path, arcname=arcname, recursive=False)
            if path.is_file():
                written_bytes += path.stat().st_size
                if on_progress is not None:
                    on_progress(written_bytes, total_bytes)

    return _finish_archive(archive_path)


def verify_archive(archive_path: Path, checksum_path: Path) -> bool:
    """Return whether `archive_path`'s current contents match its recorded checksum."""
    expected = checksum_path.read_text().split()[0]
    return _sha256_of(archive_path) == expected
