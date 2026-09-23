"""Writes the three numbered, plain-language JSON reports for one subject.

Named by pipeline order (stage-01/02/03), not by internal stage names, so a
report can be found without knowing what "audit"/"sift" mean. See
docs/sanitise-policies.md and README.md for the reports/ folder layout.
"""

from __future__ import annotations

import json
from pathlib import Path

from dichotomise.stages.audit import AuditResult
from dichotomise.stages.finalise import FinaliseResult
from dichotomise.stages.sift import SiftResult


def _relative(path: Path, base: Path) -> str:
    return str(path.relative_to(base))


def _write(reports_dir: Path, filename: str, data: dict[str, object]) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / filename
    report_path.write_text(json.dumps(data, indent=2) + "\n")
    return report_path


def write_audit_report(audit_result: AuditResult, reports_dir: Path, *, subject_label: str) -> Path:
    """Write stage-01-report.json: what the structural checks found.

    `subject_label` is the run's public label (the real PatientID, or the
    replacement label if --sanitise was used) — never read from
    `audit_result.subject.subject_id` directly, since that is always the raw
    PatientID and this report can sit inside a sanitised run's reports/
    folder.
    """
    base = audit_result.subject.directory
    duplicates = [_relative(f.metadata.path, base) for f in audit_result.files if f.is_duplicate]
    misfiled = [_relative(f.metadata.path, base) for f in audit_result.files if f.is_misfiled]
    data = {
        "stage": "audit",
        "subject_label": subject_label,
        "total_files": len(audit_result.files),
        "duplicate_count": len(duplicates),
        "misfiled_count": len(misfiled),
        "duplicates": duplicates,
        "misfiled": misfiled,
    }
    return _write(reports_dir, "stage-01-report.json", data)


def write_sift_report(sift_result: SiftResult, reports_dir: Path) -> Path:
    """Write stage-02-report.json: what was retained versus sent for review."""
    review = [
        {"file": _relative(item.metadata.path, sift_result.review_dir), "reason": item.reason}
        for item in sift_result.review
    ]
    data = {
        "stage": "sift",
        "retained_count": len(sift_result.retained),
        "review_count": len(sift_result.review),
        "review": review,
    }
    return _write(reports_dir, "stage-02-report.json", data)


def write_finalise_report(
    finalise_result: FinaliseResult,
    reports_dir: Path,
    *,
    file_count: int,
    sanitised: bool,
    sanitise_level: str | None,
) -> Path:
    """Write stage-03-report.json: the archive that was produced and verified."""
    data = {
        "stage": "finalise",
        "subject_label": finalise_result.subject_label,
        "archive": finalise_result.archive.path.name,
        "checksum": finalise_result.archive.checksum_path.read_text().split()[0],
        "file_count": file_count,
        "sanitised": sanitised,
        "sanitise_level": sanitise_level,
    }
    return _write(reports_dir, "stage-03-report.json", data)
