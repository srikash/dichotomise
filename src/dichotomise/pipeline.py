"""run_pipeline(): runs every stage in order and returns the finished Run."""

from __future__ import annotations

import shutil
from pathlib import Path

from dichotomise.errors import RelabelError
from dichotomise.pydcm.relabel import (
    generate_default_label,
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


def _resolve_subject_label(
    subject: CapturedSubject, label_mode: str, subject_id: str | None, new_id: str | None
) -> str:
    """Work out the replacement label a sanitised run should use for one subject."""
    if label_mode == "numerical":
        if not subject_id:
            raise RelabelError("Numerical replacement labels need a numerical subject ID")
        return normalise_numeric_label(subject_id)
    if label_mode == "custom":
        if not new_id:
            raise RelabelError("Custom replacement labels need a replacement ID")
        return validate_label(new_id)
    return generate_default_label(subject.patient_name)


def _reports_dir_for(run: Run, subject: CapturedSubject, subject_label: str) -> Path:
    """reports/<subject-label>_<scan-datetime>/, matching the archives/ naming convention."""
    scan_datetime = (
        f"{safe_filename_text(subject.scan_date)}-{safe_filename_text(subject.scan_time)}"
    )
    return run.reports_dir / f"{safe_filename_text(subject_label)}_{scan_datetime}"


def _process_subject(
    subject: CapturedSubject,
    run: Run,
    *,
    sanitise_requested: bool,
    sanitise_level: str,
    label_mode: str,
    subject_id: str | None,
    new_id: str | None,
) -> None:
    # The replacement label depends only on `subject` and the CLI's own
    # inputs, not on anything audit/sift/rectify produce, so it can be
    # resolved upfront and every report written straight to its final
    # location, rather than staged under a temporary name and renamed later.
    subject_label = subject.subject_id
    if sanitise_requested:
        subject_label = _resolve_subject_label(subject, label_mode, subject_id, new_id)
    reports_dir = _reports_dir_for(run, subject, subject_label)

    source_archive(subject, run)

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
    sanitise_level: str = "standard",
    label_mode: str = "default",
    subject_id: str | None = None,
    new_id: str | None = None,
    keep_working_files: bool = False,
) -> Run:
    """Run the full dichotomise pipeline over every subject found under `source_dir`.

    `sanitise_level` chooses how much is removed (default/standard/full, see
    docs/sanitise-policies.md); `label_mode` chooses how the replacement
    subject label is generated (default/numerical/custom). These are
    independent choices: a sanitised run always needs a label_mode, only
    when `sanitise_requested` is set.
    """
    run = start_run(out_dir)
    subjects = capture(source_dir, run)
    for subject in subjects:
        _process_subject(
            subject,
            run,
            sanitise_requested=sanitise_requested,
            sanitise_level=sanitise_level,
            label_mode=label_mode,
            subject_id=subject_id,
            new_id=new_id,
        )
    if not keep_working_files:
        shutil.rmtree(run.working_dir)
    return run
