"""The two structural checks dichotomise was built for: duplicate and misfiled scan files."""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import TypeVar

import pydicom

from dichotomise.pydcm.read import DicomMetadata

# Fields expected to differ between an original file and a copy of the same
# scan content: excluding them from the hash lets duplicate detection catch
# copies even when the scanner (or a copy process) assigned the copy a new
# unique ID.
_IGNORED_FOR_CONTENT_HASH = {
    "SOPInstanceUID",
    "MediaStorageSOPInstanceUID",
    "InstanceCreationDate",
    "InstanceCreationTime",
}


def content_hash(path: Path) -> str:
    """A fingerprint that is identical for two files holding the same scan content.

    Deliberately ignores each file's own unique ID and creation time, so a
    file that was copied and re-saved with a new ID is still recognised as
    the same underlying scan.
    """
    dataset = pydicom.dcmread(path, force=False)
    parts: list[str] = []
    for element in dataset:
        if element.tag.group == 0x0002 or element.keyword in _IGNORED_FOR_CONTENT_HASH:
            continue
        if element.keyword == "PixelData":
            continue
        value = str(element.value)
        parts.append(f"{element.tag}|{element.keyword}|{value}")
    parts.sort()

    hasher = hashlib.sha256()
    for part in parts:
        hasher.update(part.encode("utf-8", "replace"))
    pixel_data = getattr(dataset, "PixelData", None)
    if pixel_data is not None:
        hasher.update(hashlib.sha256(pixel_data).digest())
    return hasher.hexdigest()


def find_duplicate_files(paths: Sequence[Path]) -> set[Path]:
    """Given files known to sit in the same folder, return the ones that repeat earlier content.

    The first file (by filename) in a matching group is treated as the
    original; every later file with the same content is a duplicate.
    """
    seen_hashes: set[str] = set()
    duplicates: set[Path] = set()
    for path in sorted(paths, key=lambda item: item.name):
        digest = content_hash(path)
        if digest in seen_hashes:
            duplicates.add(path)
        else:
            seen_hashes.add(digest)
    return duplicates


_T = TypeVar("_T")


def _majority(values: Iterable[_T]) -> _T | None:
    """Return the only most common value, or None when there is no majority."""
    counts = Counter(values)
    if not counts:
        return None
    top_count = counts.most_common(1)[0][1]
    tied = [value for value, count in counts.items() if count == top_count]
    return tied[0] if len(tied) == 1 else None


def find_misfiled_files(files_by_folder: Mapping[str, Sequence[DicomMetadata]]) -> set[Path]:
    """Return files whose own series details disagree with their folder's majority.

    For each folder, the series identifier, series number, and scan protocol
    name that most files there agree on is treated as what the folder is
    supposed to contain. A file whose own details disagree with that
    majority is flagged. A scan that is legitimately split across more than
    one folder is not penalised by this check.
    """
    misfiled: set[Path] = set()
    for items in files_by_folder.values():
        if not items:
            continue
        dominant_uid = _majority(item.series_instance_uid for item in items)
        dominant_number = _majority(item.series_number for item in items)
        dominant_protocol = _majority(item.protocol_name for item in items)
        for item in items:
            if (
                item.series_instance_uid != dominant_uid
                or item.series_number != dominant_number
                or item.protocol_name != dominant_protocol
            ):
                misfiled.add(item.path)
    return misfiled
