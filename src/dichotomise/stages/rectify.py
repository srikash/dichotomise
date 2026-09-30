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


@dataclass(frozen=True)
class RectifyReviewResult:
    """A subject's review files, renamed the same way retained files are."""

    review_rectified_dir: Path
    files: list[DicomMetadata]
    collision_count: int


def rectify_review(sift_result: SiftResult) -> RectifyReviewResult:
    """Copy every review file into its rectified name, tolerating collisions.

    Uses the same naming as rectify() so a reviewer can see immediately
    which series/instance a review file's metadata claims to belong to —
    including when that claim is wrong (misfiled) or shared with another
    file (duplicate). A genuine name collision does not stop the run here:
    the colliding file keeps a disambiguated name (`-dup01`, `-dup02`, ...)
    instead of being silently dropped or overwritten.
    """
    review_rectified_dir = sift_result.subject.directory.parent / "review-rectify"
    occupied: dict[Path, int] = {}
    files: list[DicomMetadata] = []
    collision_count = 0

    for item in sift_result.review:
        target = rectified_path(review_rectified_dir, item.metadata)
        occurrence = occupied.get(target, 0)
        occupied[target] = occurrence + 1
        if occurrence:
            collision_count += 1
            target = target.with_name(f"{target.stem}-dup{occurrence:02d}{target.suffix}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item.metadata.path, target)
        files.append(replace(item.metadata, path=target))

    return RectifyReviewResult(
        review_rectified_dir=review_rectified_dir, files=files, collision_count=collision_count
    )
