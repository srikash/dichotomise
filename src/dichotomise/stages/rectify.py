"""Stage 5: copy retained files into metadata-named, series-ordered folders.

This is the pipeline's first and only copy of each file's bytes: capture()
and sift() work from the original source files in place, so rectify() (and
rectify_review() below) read straight from those original paths.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, replace
from pathlib import Path

from dichotomise.errors import NamingCollisionError
from dichotomise.pydcm.identify import file_digest
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

    A byte-identical file that lands on a name already written is the same
    file again (for example a copy of an export in another folder), so it is
    not written or listed a second time. Two different scan files that would
    land on the exact same rectified name is a real ambiguity about which
    file the name belongs to, so it stops the run rather than silently
    picking one or numbering around it.
    """
    rectified_dir = sift_result.subject.working_dir / "rectify"
    occupied: dict[Path, DicomMetadata] = {}
    files: list[DicomMetadata] = []

    for metadata in sift_result.retained:
        target = rectified_path(rectified_dir, metadata)
        if target in occupied:
            if file_digest(occupied[target].path) != file_digest(metadata.path):
                raise NamingCollisionError(
                    f"Two different scan files would both be named {target.name}: "
                    f"{occupied[target].path} and {metadata.path}"
                )
            continue
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
    merged_identical_count: int = 0


def rectify_review(sift_result: SiftResult) -> RectifyReviewResult:
    """Copy every review file into its rectified name, tolerating collisions.

    Uses the same naming as rectify() so a reviewer can see immediately
    which series/instance a review file's metadata claims to belong to --
    including when that claim is wrong (misfiled) or shared with another
    file (duplicate). A byte-identical file that lands on a name already
    written is the same file again, so it is not written a second time
    (`merged_identical_count` counts them). A name shared by files that
    differ keeps a disambiguated name (`-dup01`, `-dup02`, ...) instead of
    being silently dropped or overwritten.
    """
    review_rectified_dir = sift_result.subject.working_dir / "review-rectify"
    written: dict[Path, list[Path]] = {}
    files: list[DicomMetadata] = []
    collision_count = 0
    merged_identical_count = 0

    for item in sift_result.review:
        target = rectified_path(review_rectified_dir, item.metadata)
        digest = file_digest(item.metadata.path)
        previous = written.setdefault(target, [])
        if any(file_digest(path) == digest for path in previous):
            merged_identical_count += 1
            continue
        occurrence = len(previous)
        previous.append(item.metadata.path)
        if occurrence:
            collision_count += 1
            target = target.with_name(f"{target.stem}-dup{occurrence:02d}{target.suffix}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item.metadata.path, target)
        files.append(replace(item.metadata, path=target))

    return RectifyReviewResult(
        review_rectified_dir=review_rectified_dir,
        files=files,
        collision_count=collision_count,
        merged_identical_count=merged_identical_count,
    )
