"""run_pipeline(): runs every stage in order and returns the finished Run."""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from pathlib import Path

from dichotomise.errors import RelabelError
from dichotomise.pydcm.names import generate_name
from dichotomise.pydcm.relabel import (
    load_policy,
    normalise_numeric_label,
    validate_label,
)
from dichotomise.run import Run, start_run
from dichotomise.stages.audit import audit
from dichotomise.stages.capture import CapturedSubject, capture
from dichotomise.stages.finalise import finalise
from dichotomise.stages.rectify import rectify
from dichotomise.stages.reports import write_audit_report, write_finalise_report, write_sift_report
from dichotomise.stages.sanitise import sanitise
from dichotomise.stages.sift import sift
from dichotomise.stages.source_archive import source_archive
from dichotomise.utils.text import safe_filename_text


def _random_subject_label(used_labels: set[str]) -> str:
    """Generate a unique, filesystem-safe pseudonym for one subject in this run."""
    while len(used_labels) < 100_000:
        given_name, _, surname = generate_name().rpartition("_")
        label = f"{surname}_{given_name}"
        if label not in used_labels:
            used_labels.add(label)
            return label
    raise RelabelError("Could not generate a unique pseudonym for every subject in this run")


def _resolve_subject_label(
    subject: CapturedSubject,
    label_mode: str,
    subject_id: str | None,
    new_id: str | None,
    subject_mappings: Mapping[str, str] | None,
    used_labels: set[str],
) -> str:
    """Work out the replacement label a sanitised run should use for one subject."""
    if subject_mappings is not None:
        try:
            return validate_label(subject_mappings[subject.subject_id])
        except KeyError as error:
            raise RelabelError(
                f"No replacement ID was supplied for source subject {subject.subject_id!r}"
            ) from error
    if label_mode == "numerical":
        if not subject_id:
            raise RelabelError("Numerical replacement labels need a numerical subject ID")
        start_number = int(normalise_numeric_label(subject_id).removeprefix("sub-"))
        return normalise_numeric_label(str(start_number + subject.output_number - 1))
    if label_mode == "custom":
        if not new_id:
            raise RelabelError("Custom replacement labels need a replacement ID")
        return validate_label(new_id)
    if label_mode == "random":
        return _random_subject_label(used_labels)
    raise RelabelError(f"Unsupported replacement-label mode: {label_mode}")


def _reports_dir_for(run: Run, subject: CapturedSubject, subject_label: str) -> Path:
    """Return this study's collision-safe directory under reports/."""
    scan_datetime = (
        f"{safe_filename_text(subject.scan_date)}-{safe_filename_text(subject.scan_time)}"
    )
    return run.reports_dir / (
        f"{safe_filename_text(subject_label)}_{scan_datetime}_study-{subject.output_number:03d}"
    )


def _process_subject(
    subject: CapturedSubject,
    run: Run,
    *,
    sanitise_requested: bool,
    sanitise_level: str,
    label_mode: str,
    subject_id: str | None,
    new_id: str | None,
    subject_mappings: Mapping[str, str] | None,
    used_labels: set[str],
) -> None:
    # The replacement label depends only on `subject` and the CLI's own
    # inputs, not on anything audit/sift/rectify produce, so it can be
    # resolved upfront and every report written straight to its final
    # location, rather than staged under a temporary name and renamed later.
    subject_label = subject.subject_id
    if sanitise_requested:
        subject_label = _resolve_subject_label(
            subject, label_mode, subject_id, new_id, subject_mappings, used_labels
        )
    reports_dir = _reports_dir_for(run, subject, subject_label)

    audit_result = audit(subject)
    write_audit_report(audit_result, reports_dir, subject_label=subject_label)

    sift_result = sift(audit_result)
    write_sift_report(sift_result, reports_dir)

    rectify_result = rectify(sift_result)

    sanitise_result = None
    if sanitise_requested:
        policy = load_policy(sanitise_level)
        sanitise_result = sanitise(rectify_result, policy=policy, subject_label=subject_label)

    finalise_result = finalise(
        rectify_result, run, subject_label=subject_label, sanitise_result=sanitise_result
    )
    file_count = len(sanitise_result.files) if sanitise_result else len(rectify_result.files)
    write_finalise_report(
        finalise_result,
        reports_dir,
        file_count=file_count,
        sanitised=sanitise_requested,
        sanitise_level=sanitise_level if sanitise_requested else None,
    )


def run_pipeline(
    source_dir: Path,
    out_dir: Path,
    *,
    sanitise_requested: bool = False,
    sanitise_level: str = "minimal",
    label_mode: str = "random",
    subject_id: str | None = None,
    new_id: str | None = None,
    subject_mappings: Mapping[str, str] | None = None,
    keep_working_files: bool = False,
) -> Run:
    """Run the full dichotomise pipeline over every subject found under `source_dir`.

    `sanitise_level` selects a policy filename (see docs/sanitise-policies.md).
    The command line chooses the internal label mode from the selected policy
    and any numerical, exact, or mapped replacement ID supplied.
    """
    run = start_run(out_dir)
    try:
        source_archive(source_dir, run)
        subjects = capture(source_dir, run)
        if new_id is not None and len(subjects) != 1:
            raise RelabelError("--new-id may only be used when the source contains one subject.")
        if subject_mappings is not None:
            source_ids = {subject.subject_id for subject in subjects}
            unknown_ids = set(subject_mappings) - source_ids
            if unknown_ids:
                raise RelabelError(
                    "Mappings were supplied for source IDs not found in this export: "
                    + ", ".join(sorted(unknown_ids))
                )
        used_labels: set[str] = set()
        for subject in subjects:
            _process_subject(
                subject,
                run,
                sanitise_requested=sanitise_requested,
                sanitise_level=sanitise_level,
                label_mode=label_mode,
                subject_id=subject_id,
                new_id=new_id,
                subject_mappings=subject_mappings,
                used_labels=used_labels,
            )
        if not keep_working_files:
            shutil.rmtree(run.working_dir)
    except BaseException:
        run.set_status("failed")
        raise
    run.set_status("complete")
    return run
