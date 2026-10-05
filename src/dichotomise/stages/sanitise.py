"""Stage 6 (optional, --sanitise): replace PatientName/PatientID in a copy of the rectified tree."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dichotomise.pydcm.relabel import Policy, sanitise_file
from dichotomise.stages.capture import CapturedSubject
from dichotomise.stages.rectify import RectifyResult, RectifyReviewResult


@dataclass(frozen=True)
class SanitiseResult:
    """A subject's rectified files, copied into a new tree with the policy applied."""

    subject: CapturedSubject
    subject_label: str
    sanitised_dir: Path
    files: list[Path]


def sanitise(
    rectify_result: RectifyResult,
    *,
    policy: Policy,
    subject_label: str,
    replacement_cache: dict[str, str] | None = None,
) -> SanitiseResult:
    """Write a sanitised copy of every rectified file, next to (not over) the original.

    The same replacement identifiers are used for every file (`replacement_cache` is
    shared across the whole subject), so a UID that appears in more than one
    file regenerates to the same new value everywhere. Pass an external
    `replacement_cache` to also share it with `sanitise_review()`, so a UID
    common to a retained and a review file still gets the same replacement.
    """
    sanitised_dir = rectify_result.subject.working_dir / "sanitise"
    replacement_cache = {} if replacement_cache is None else replacement_cache
    files: list[Path] = []

    for metadata in rectify_result.files:
        target = sanitised_dir / metadata.path.relative_to(rectify_result.rectified_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        sanitise_file(
            metadata.path,
            target,
            policy,
            subject_label=subject_label,
            scan_date=rectify_result.subject.scan_date,
            replacement_cache=replacement_cache,
        )
        files.append(target)

    return SanitiseResult(
        subject=rectify_result.subject,
        subject_label=subject_label,
        sanitised_dir=sanitised_dir,
        files=files,
    )


@dataclass(frozen=True)
class SanitiseReviewResult:
    """A subject's rectified review files, copied into a new tree with the policy applied."""

    sanitised_review_dir: Path
    files: list[Path]


def sanitise_review(
    rectify_review_result: RectifyReviewResult,
    *,
    policy: Policy,
    subject_label: str,
    scan_date: str,
    replacement_cache: dict[str, str],
) -> SanitiseReviewResult | None:
    """Write a sanitised copy of every rectified review file, or None if there are none.

    Filenames/paths are preserved as rectify_review() produced them; only
    DICOM tag content is scrubbed. Shares `replacement_cache` with the
    retained-files sanitise() call so a UID appearing in both a retained and
    a review file regenerates to the same new value.
    """
    if not rectify_review_result.files:
        return None
    sanitised_review_dir = rectify_review_result.review_rectified_dir.parent / "sanitise-review"
    files: list[Path] = []
    for metadata in rectify_review_result.files:
        target = sanitised_review_dir / metadata.path.relative_to(
            rectify_review_result.review_rectified_dir
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        sanitise_file(
            metadata.path,
            target,
            policy,
            subject_label=subject_label,
            scan_date=scan_date,
            replacement_cache=replacement_cache,
        )
        files.append(target)
    return SanitiseReviewResult(sanitised_review_dir=sanitised_review_dir, files=files)
