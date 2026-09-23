"""Stage 6 (optional, --sanitise): replace PatientName/PatientID in a copy of the rectified tree."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dichotomise.pydcm.relabel import Policy, sanitise_file
from dichotomise.stages.capture import CapturedSubject
from dichotomise.stages.rectify import RectifyResult


@dataclass(frozen=True)
class SanitiseResult:
    """A subject's rectified files, copied into a new tree with the policy applied."""

    subject: CapturedSubject
    subject_label: str
    sanitised_dir: Path
    files: list[Path]


def sanitise(
    rectify_result: RectifyResult, *, policy: Policy, subject_label: str
) -> SanitiseResult:
    """Write a sanitised copy of every rectified file, next to (not over) the original.

    The same replacement identifiers are used for every file (`replacement_cache` is
    shared across the whole subject), so a UID that appears in more than one
    file regenerates to the same new value everywhere.
    """
    sanitised_dir = rectify_result.subject.directory.parent / "sanitise"
    replacement_cache: dict[str, str] = {}
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
