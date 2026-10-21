"""Writes the three numbered, plain-language JSON reports for one subject.

Named by pipeline order (stage-01/02/03), not by internal stage names, so a
report can be found without knowing what "audit"/"sift" mean. See
docs/sanitise-policies.md and README.md for the reports/ folder layout.
"""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path

from dichotomise.pydcm.acquisition import infer_ti_index, summarise_acquisition
from dichotomise.pydcm.read import DicomMetadata
from dichotomise.stages.audit import (
    AuditedFile,
    AuditResult,
    describe_findings,
    metadata_inconsistencies,
)
from dichotomise.stages.capture import CapturedSubject
from dichotomise.stages.finalise import FinaliseResult
from dichotomise.stages.rectify import RectifyResult, RectifyReviewResult
from dichotomise.stages.sanitise import SanitiseResult
from dichotomise.stages.sift import SiftResult
from dichotomise.utils.archive import Archive
from dichotomise.utils.text import natural_sort_key


def _relative(path: Path, base: Path) -> str:
    return str(path.relative_to(base))


def _write(reports_dir: Path, filename: str, data: dict[str, object]) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / filename
    report_path.write_text(json.dumps(data, indent=2) + "\n")
    return report_path


def _audit_series_rows(audit_result: AuditResult) -> list[dict[str, object]]:
    """Summarise structural and metadata findings for each physical DICOM folder."""
    files_by_folder: dict[Path, list[AuditedFile]] = {}
    for audited_file in audit_result.files:
        files_by_folder.setdefault(audited_file.metadata.path.parent, []).append(audited_file)

    rows: list[dict[str, object]] = []
    for folder, files in sorted(
        files_by_folder.items(), key=lambda item: (natural_sort_key(item[0].name), item[0])
    ):
        inconsistencies = metadata_inconsistencies(files)
        duplicate_count = sum(file.is_duplicate for file in files)
        misfiled_count = sum(file.is_misfiled for file in files)
        conflict_count = sum(file.is_sop_conflict for file in files)
        low_priority = all(f.metadata.modality in {"PR", "SR"} for f in files)
        rows.append(
            {
                "series_folder": folder.name,
                "dicom_count": len(files),
                "duplicate_count": duplicate_count,
                "misfiled_count": misfiled_count,
                "sop_conflict_count": conflict_count,
                "metadata_inconsistencies": "; ".join(inconsistencies),
                "status": "flagged"
                if duplicate_count or misfiled_count or conflict_count or inconsistencies
                else "pass",
                "notes": describe_findings(files, compact_duplicates=low_priority),
            }
        )
    return rows


def _write_audit_csv(reports_dir: Path, rows: list[dict[str, object]]) -> Path:
    """Write the spreadsheet-friendly audit inventory alongside its JSON report."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "stage-01-audit.csv"
    fieldnames = [
        "series_folder",
        "dicom_count",
        "duplicate_count",
        "misfiled_count",
        "sop_conflict_count",
        "metadata_inconsistencies",
        "status",
        "notes",
    ]
    with report_path.open("w", newline="") as report_file:
        writer = csv.DictWriter(report_file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, "notes": " | ".join(row["notes"])})  # type: ignore[arg-type]
    return report_path


def write_audit_report(audit_result: AuditResult, reports_dir: Path, *, subject_label: str) -> Path:
    """Write stage-01-report.json: what the structural checks found.

    `subject_label` is the run's public label (the real PatientID, or the
    replacement label if --sanitise was used). The report never reads
    `audit_result.subject.subject_id` directly, since that is always the raw
    PatientID and this report can sit inside a sanitised run's reports/
    folder.
    """
    series_rows = _audit_series_rows(audit_result)
    duplicates = sorted(
        {file.metadata.path.parent.name for file in audit_result.files if file.is_duplicate},
        key=natural_sort_key,
    )
    misfiled = sorted(
        {file.metadata.path.parent.name for file in audit_result.files if file.is_misfiled},
        key=natural_sort_key,
    )
    data = {
        "stage": "audit",
        "subject_label": subject_label,
        "total_files": len(audit_result.files),
        "duplicate_count": sum(file.is_duplicate for file in audit_result.files),
        "misfiled_count": sum(file.is_misfiled for file in audit_result.files),
        "sop_conflict_count": sum(file.is_sop_conflict for file in audit_result.files),
        "duplicates": duplicates,
        "misfiled": misfiled,
        "metadata_inconsistency_count": sum(
            bool(row["metadata_inconsistencies"]) for row in series_rows
        ),
        "series": series_rows,
    }
    report_path = _write(reports_dir, "stage-01-report.json", data)
    _write_audit_csv(reports_dir, series_rows)
    return report_path


def write_sift_report(
    sift_result: SiftResult,
    reports_dir: Path,
    *,
    rectify_result: RectifyResult | None = None,
    rectify_review_result: RectifyReviewResult | None = None,
    review_archive: Archive | None = None,
    review_sanitised: bool = False,
) -> Path:
    """Write stage-02-report.json: what was retained versus sent for review."""
    review = [
        {
            "file": _relative(item.metadata.path, sift_result.subject.source_root),
            "reason": item.reason,
        }
        for item in sift_result.review
    ]
    data = {
        "stage": "sift",
        "retained_count": len(sift_result.retained),
        "retained_identical_files_not_rewritten": (
            rectify_result.merged_identical_count if rectify_result is not None else 0
        ),
        "review_count": len(sift_result.review),
        "review": review,
        "review_rename_collisions": (
            rectify_review_result.collision_count if rectify_review_result is not None else 0
        ),
        "review_identical_files_not_rewritten": (
            rectify_review_result.merged_identical_count if rectify_review_result is not None else 0
        ),
        "review_archive": review_archive.path.name if review_archive is not None else None,
        "review_archive_checksum": (
            review_archive.checksum_path.read_text().split()[0]
            if review_archive is not None
            else None
        ),
        "review_archive_sanitised": review_sanitised,
    }
    return _write(reports_dir, "stage-02-report.json", data)


def _write_manifest_csv(files: list[Path], root: Path, manifest_path: Path) -> Path:
    """Write a CSV of file/size/modified/created, paths relative to `root`.

    "date_created" uses st_birthtime where the OS provides it (macOS/BSD),
    falling back to st_ctime (metadata-change time, not true creation time)
    on Linux, since Linux exposes no creation time via Python's os.stat.
    """
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["file", "size_bytes", "date_modified", "date_created"]
        )
        writer.writeheader()
        for path in sorted(files):
            stat = path.stat()
            created = getattr(stat, "st_birthtime", stat.st_ctime)
            writer.writerow(
                {
                    "file": _relative(path, root),
                    "size_bytes": stat.st_size,
                    "date_modified": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
                    "date_created": datetime.fromtimestamp(created, tz=UTC).isoformat(),
                }
            )
    return manifest_path


def write_source_manifest(subject: CapturedSubject, reports_dir: Path) -> Path:
    """Write source-manifest.csv: every captured source file, size and timestamps."""
    files = sorted(metadata.path for metadata in subject.files)
    return _write_manifest_csv(files, subject.source_root, reports_dir / "source-manifest.csv")


def write_retained_manifest(sift_result: SiftResult, reports_dir: Path) -> Path:
    """Write retained-manifest.csv: every file that passed sift, size and timestamps."""
    files = [item.path for item in sift_result.retained]
    return _write_manifest_csv(
        files, sift_result.subject.source_root, reports_dir / "retained-manifest.csv"
    )


def write_review_manifest(sift_result: SiftResult, reports_dir: Path) -> Path | None:
    """Write review-manifest.csv, or None if nothing was sent to review."""
    if not sift_result.review:
        return None
    files = [item.metadata.path for item in sift_result.review]
    return _write_manifest_csv(
        files, sift_result.subject.source_root, reports_dir / "review-manifest.csv"
    )


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

    final_path_by_rectified = (
        dict(zip((m.path for m in rectify_result.files), sanitise_result.files, strict=True))
        if sanitise_result is not None
        else {}
    )

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
            after_name = final_path_by_rectified.get(
                first_rectified.path, first_rectified.path
            ).name
        metadata = first_source.metadata
        acquisition = summarise_acquisition(rectified_files)
        entry: dict[str, object] = {
            "series_number": metadata.series_number,
            "series_description": metadata.series_description,
            "series_instance_uid": series_uid,
            "source_file_count": len(source_files),
            "archived_file_count": len(rectified_files),
            "review_file_count": sum(
                item.is_duplicate or item.is_misfiled or item.is_sop_conflict
                for item in source_files
            ),
            "first_dicom_before": metadata.path.name,
            "first_dicom_after": after_name,
        }
        if acquisition.is_multi_echo_or_ti:
            ti_index = infer_ti_index(rectified_files)
            entry["acquisition"] = acquisition.describe()
            entry["files"] = [
                {
                    "file": final_path_by_rectified.get(item.path, item.path).name,
                    "echo_number": item.echo_number,
                    "echo_time_ms": item.echo_time,
                    "asl_context": item.asl_context,
                    "ti_index_inferred": ti_index.get(item.path),
                }
                for item in sorted(rectified_files, key=lambda f: (f.instance_number, f.path.name))
            ]
        inventory.append(((metadata.series_number, metadata.series_description, series_uid), entry))
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
