"""Stage 4: split audited files into retained vs needs-review (no copying)."""

from __future__ import annotations

from dataclasses import dataclass

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
    """A subject's files, split into retained vs review -- still at their original paths."""

    subject: CapturedSubject
    retained: list[DicomMetadata]
    review: list[ReviewFile]


def sift(audit_result: AuditResult) -> SiftResult:
    """Sort each audited file into retained or review, by its findings.

    This is a logical split only: `retained`/`review` still point at each
    file's original, untouched path. A file with no findings is retained; a
    duplicate or misfiled file is marked for review, tagged with the
    reason, rather than being silently dropped. rectify() is where files
    are actually copied, into their final, agreed-upon layout.
    """
    retained: list[DicomMetadata] = []
    review: list[ReviewFile] = []
    for file in audit_result.files:
        if file.is_duplicate:
            review.append(ReviewFile(file.metadata, "duplicate"))
        elif file.is_misfiled:
            review.append(ReviewFile(file.metadata, "misfiled"))
        else:
            retained.append(file.metadata)

    return SiftResult(subject=audit_result.subject, retained=retained, review=review)
