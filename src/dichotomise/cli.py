"""The `dichotomise` command: reads the flags, runs the pipeline, and reports the result."""

from __future__ import annotations

from pathlib import Path

import click

from dichotomise.errors import DichotomiseError
from dichotomise.pipeline import run_pipeline
from dichotomise.utils.console import console, error, status, success


def _infer_label_mode(sanitise_mode: str | None, subject_id: str | None, new_id: str | None) -> str:
    """Work out the replacement-label mode when --sanitise-mode was not given explicitly."""
    if sanitise_mode:
        return sanitise_mode
    if new_id:
        return "custom"
    if subject_id:
        return "numerical"
    return "default"


@click.command(
    help=(
        "Copy, audit, sift, rectify, and archive a DICOM study. "
        "Use --sanitise to also replace patient identity before final archiving."
    )
)
@click.option(
    "--source-dir",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
    required=True,
    help="Raw DICOM directory to process.",
)
@click.option(
    "--out-dir",
    type=click.Path(path_type=Path, file_okay=False),
    required=True,
    help="Parent directory for the timestamped dichotomise output folder.",
)
@click.option("--sanitise", is_flag=True, help="Replace patient identity before final archiving.")
@click.option(
    "--random-name",
    is_flag=True,
    help="Shortcut for --sanitise --sanitise-level minimal: replace the patient name with a "
    "random, readable placeholder (e.g. Abrahall^Gracious) rather than the plain subject "
    "label. Implies --sanitise.",
)
@click.option(
    "--sanitise-mode",
    type=click.Choice(["default", "numerical", "custom"]),
    default=None,
    help="How the replacement label is generated; inferred from --subject-id/--new-id "
    "if not given.",
)
@click.option(
    "--sanitise-level",
    default=None,
    help="How much is removed: standard (default) keeps scan descriptions (preferred), full "
    "also removes them; custom is a template for your own. See docs/sanitise-policies.md.",
)
@click.option("--subject-id", default=None, help="Numerical subject ID for numerical labels.")
@click.option("--new-id", default=None, help="Exact replacement ID for custom labels.")
@click.option(
    "--keep-working-files", is_flag=True, help="Keep the copied and processed DICOM files."
)
def cli(
    source_dir: Path,
    out_dir: Path,
    sanitise: bool,
    random_name: bool,
    sanitise_mode: str | None,
    sanitise_level: str | None,
    subject_id: str | None,
    new_id: str | None,
    keep_working_files: bool,
) -> None:
    """Run the standard, end-to-end dichotomise pipeline."""
    if random_name and sanitise_level not in (None, "minimal"):
        raise click.UsageError(
            "--random-name implies --sanitise-level minimal; do not combine it with a "
            "different --sanitise-level."
        )
    sanitise = sanitise or random_name
    if not sanitise and any((sanitise_mode, subject_id, new_id)):
        raise click.UsageError("Replacement-label options require --sanitise.")

    effective_sanitise_level = sanitise_level or ("minimal" if random_name else "standard")
    label_mode = _infer_label_mode(sanitise_mode, subject_id, new_id)

    console.print(f"[bold]dichotomise[/bold] processing {source_dir}")
    try:
        with status("Processing..."):
            run = run_pipeline(
                source_dir,
                out_dir,
                sanitise_requested=sanitise,
                sanitise_level=effective_sanitise_level,
                label_mode=label_mode,
                subject_id=subject_id,
                new_id=new_id,
                keep_working_files=keep_working_files,
            )
    except DichotomiseError as failure:
        error(str(failure))
        raise SystemExit(1) from failure

    success(f"Finished: {run.root}")
    for archive in sorted(run.archives_dir.glob("*.tar.gz")):
        console.print(f"  [green]✓[/green] {archive.name}")
