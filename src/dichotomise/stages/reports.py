"""Writes the three numbered, plain-language JSON reports for one subject.

Named by pipeline order (stage-01/02/03), not by internal stage names, so a
report can be found without knowing what "audit"/"sift" mean. See
docs/sanitise-policies.md and README.md for the reports/ folder layout.
"""

from __future__ import annotations

import json
from pathlib import Path

from dichotomise.pydcm.read import DicomMetadata
from dichotomise.stages.audit import AuditedFile, AuditResult
from dichotomise.stages.finalise import FinaliseResult
from dichotomise.stages.rectify import RectifyResult
from dichotomise.stages.sanitise import SanitiseResult
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


def _series_inventory(
    audit_result: AuditResult,
    rectify_result: RectifyResult,
    sanitise_result: SanitiseResult | None,
) -> list[dict[str, object]]:
    """Return one filename mapping for the first retained DICOM in each series."""
    source_by_series: dict[str, list[AuditedFile]] = {}
    for audited_file in audit_result.files:
        source_by_series.setdefault(audited_file.metadata.series_instance_uid, []).append(
            audited_file
        )

    rectified_by_series: dict[str, list[DicomMetadata]] = {}
    for metadata in rectify_result.files:
        rectified_by_series.setdefault(metadata.series_instance_uid, []).append(metadata)

    inventory: list[tuple[tuple[int, str, str], dict[str, object]]] = []
    for series_uid, source_files in source_by_series.items():
        first_source = min(
            source_files,
            key=lambda item: (item.metadata.instance_number, item.metadata.path.name),
        )
        rectified_files = rectified_by_series.get(series_uid, [])
        first_rectified = (
            min(rectified_files, key=lambda item: (item.instance_number, item.path.name))
            if rectified_files
            else None
        )
        after_name = None
        if first_rectified is not None:
            after_file = first_rectified.path
            if sanitise_result is not None:
                after_file = sanitise_result.sanitised_dir / first_rectified.path.relative_to(
                    rectify_result.rectified_dir
                )
            after_name = after_file.name
        metadata = first_source.metadata
        inventory.append(
            (
                (metadata.series_number, metadata.series_description, series_uid),
                {
                    "series_number": metadata.series_number,
                    "series_description": metadata.series_description,
                    "series_instance_uid": series_uid,
                    "source_file_count": len(source_files),
                    "archived_file_count": len(rectified_files),
                    "review_file_count": sum(
                        item.is_duplicate or item.is_misfiled for item in source_files
                    ),
                    "first_dicom_before": metadata.path.name,
                    "first_dicom_after": after_name,
                },
            )
        )
    return [entry for _, entry in sorted(inventory)]


def write_finalise_report(
    finalise_result: FinaliseResult,
    reports_dir: Path,
    *,
    file_count: int,
    sanitised: bool,
    sanitise_level: str | None,
    audit_result: AuditResult | None = None,
    rectify_result: RectifyResult | None = None,
    sanitise_result: SanitiseResult | None = None,
) -> Path:
    """Write stage-03-report.json: archive details and per-series filename mappings."""
    data = {
        "stage": "finalise",
        "subject_label": finalise_result.subject_label,
        "archive": finalise_result.archive.path.name,
        "checksum": finalise_result.archive.checksum_path.read_text().split()[0],
        "file_count": file_count,
        "sanitised": sanitised,
        "sanitise_level": sanitise_level,
    }
    if audit_result is not None and rectify_result is not None:
        data["series_inventory"] = _series_inventory(audit_result, rectify_result, sanitise_result)
    return _write(reports_dir, "stage-03-report.json", data)
