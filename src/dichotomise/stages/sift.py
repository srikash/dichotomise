"""Stage 4: split audited files into retained vs needs-review."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, replace
from pathlib import Path

from dichotomise.pydcm.read import DicomMetadata
from dichotomise.stages.audit import AuditResult
from dichotomise.stages.capture import CapturedSubject


@dataclass(frozen=True)
class ReviewFile:
    """One file that was not retained, and why."""

    metadata: DicomMetadata
    reason: str  # "duplicate" or "misfiled"


@dataclass(frozen=True)
class SiftResult:
    """Where a subject's files ended up after splitting retained from review."""

    subject: CapturedSubject
    retained: list[DicomMetadata]
    retained_dir: Path
    review: list[ReviewFile]
    review_dir: Path


def _copy_into(metadata: DicomMetadata, capture_dir: Path, destination_root: Path) -> DicomMetadata:
    relative = metadata.path.relative_to(capture_dir)
    target = destination_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(metadata.path, target)
    return replace(metadata, path=target)


def sift(audit_result: AuditResult) -> SiftResult:
    """Copy each audited file into a retained/ or review/ folder, by its findings.

    A file with no findings is retained. A duplicate or misfiled file is
    copied into review/ instead, tagged with the reason, rather than being
    silently dropped.
    """
    capture_dir = audit_result.subject.directory
    sift_dir = capture_dir.parent / "sift"
    retained_dir = sift_dir / "retained"
    review_dir = sift_dir / "review"

    retained: list[DicomMetadata] = []
    review: list[ReviewFile] = []
    for file in audit_result.files:
        if file.is_duplicate:
            review.append(
                ReviewFile(_copy_into(file.metadata, capture_dir, review_dir), "duplicate")
            )
        elif file.is_misfiled:
            review.append(
                ReviewFile(_copy_into(file.metadata, capture_dir, review_dir), "misfiled")
            )
        else:
            retained.append(_copy_into(file.metadata, capture_dir, retained_dir))

    return SiftResult(
        subject=audit_result.subject,
        retained=retained,
        retained_dir=retained_dir,
        review=review,
        review_dir=review_dir,
    )
