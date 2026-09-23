"""make_tarball() and verify_archive(): tar.gz creation with a sha256 sidecar."""

from __future__ import annotations

import hashlib
import tarfile
from dataclasses import dataclass
from pathlib import Path


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


def make_tarball(source_dir: Path, archive_path: Path) -> Archive:
    """Compress everything under `source_dir` into `archive_path`, plus a checksum file.

    The checksum sidecar sits next to the archive, named after it with a
    `.sha256` extension in place of `.tar.gz`.
    """
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "w:gz") as tar:
        for item in sorted(source_dir.rglob("*")):
            # recursive=False: `item` is already one entry from our own walk
            # (files and folders both), so letting tar.add() recurse into a
            # folder would add every file inside it a second time.
            tar.add(item, arcname=item.relative_to(source_dir), recursive=False)

    checksum_path = _checksum_path_for(archive_path)
    checksum_path.write_text(_sha256_of(archive_path) + "\n")
    return Archive(path=archive_path, checksum_path=checksum_path)


def verify_archive(archive_path: Path, checksum_path: Path) -> bool:
    """Return whether `archive_path`'s current contents match its recorded checksum."""
    expected = checksum_path.read_text().split()[0]
    return _sha256_of(archive_path) == expected
