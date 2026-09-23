"""Stage 5: copy retained files into metadata-named, series-ordered folders."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, replace
from pathlib import Path

from dichotomise.errors import NamingCollisionError
from dichotomise.pydcm.identify import content_hash
from dichotomise.pydcm.naming import rectified_path
from dichotomise.pydcm.read import DicomMetadata
from dichotomise.stages.capture import CapturedSubject
from dichotomise.stages.sift import SiftResult


@dataclass(frozen=True)
class RectifyResult:
    """A subject's retained files, copied into their sorted, clearly named tree."""

    subject: CapturedSubject
    rectified_dir: Path
    files: list[DicomMetadata]


def rectify(sift_result: SiftResult) -> RectifyResult:
    """Copy every retained file into its rectified name and folder.

    Two different scan files that would land on the exact same rectified
    name is a real ambiguity about which file the name belongs to (sift
    already removed genuine duplicates), so it stops the run rather than
    silently picking one or numbering around it.
    """
    rectified_dir = sift_result.subject.directory.parent / "rectify"
    occupied: dict[Path, DicomMetadata] = {}
    files: list[DicomMetadata] = []

    for metadata in sift_result.retained:
        target = rectified_path(rectified_dir, metadata)
        if target in occupied and content_hash(occupied[target].path) != content_hash(
            metadata.path
        ):
            raise NamingCollisionError(
                f"Two different scan files would both be named {target.name}: "
                f"{occupied[target].path} and {metadata.path}"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(metadata.path, target)
        occupied[target] = metadata
        files.append(replace(metadata, path=target))

    return RectifyResult(subject=sift_result.subject, rectified_dir=rectified_dir, files=files)
