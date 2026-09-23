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
    "--sanitise-mode",
    type=click.Choice(["default", "numerical", "custom"]),
    default=None,
    help="How the replacement label is generated; inferred from --subject-id/--new-id "
    "if not given.",
)
@click.option(
    "--sanitise-level",
    default="standard",
    show_default=True,
    help="How much is removed: standard keeps scan descriptions (preferred), full also "
    "removes them; custom is a template for your own. See docs/sanitise-policies.md.",
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
    sanitise_mode: str | None,
    sanitise_level: str,
    subject_id: str | None,
    new_id: str | None,
    keep_working_files: bool,
) -> None:
    """Run the standard, end-to-end dichotomise pipeline."""
    if not sanitise and any((sanitise_mode, subject_id, new_id)):
        raise click.UsageError("Replacement-label options require --sanitise.")

    label_mode = _infer_label_mode(sanitise_mode, subject_id, new_id)

    console.print(f"[bold]dichotomise[/bold] processing {source_dir}")
    try:
        with status("Processing..."):
            run = run_pipeline(
                source_dir,
                out_dir,
                sanitise_requested=sanitise,
                sanitise_level=sanitise_level,
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
