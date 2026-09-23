"""The `dichotomise` command: reads the flags, runs the pipeline, and reports the result."""

from __future__ import annotations

import csv
import json
from collections.abc import Mapping
from pathlib import Path

import click

from dichotomise.errors import DichotomiseError
from dichotomise.pipeline import run_pipeline
from dichotomise.utils.console import console, error, status, success


def _infer_label_mode(subject_id: str | None, new_id: str | None) -> str:
    """Work out the replacement-label mode from the selected label source."""
    if new_id:
        return "custom"
    if subject_id:
        return "numerical"
    return "default"


def _add_mapping(mapping: dict[str, str], source_id: str, replacement_id: str) -> None:
    if not source_id or not replacement_id:
        raise click.UsageError("Each mapping must contain both a source ID and a replacement ID.")
    if source_id in mapping:
        raise click.UsageError(f"A replacement ID was supplied more than once for {source_id!r}.")
    mapping[source_id] = replacement_id


def _parse_inline_mappings(entries: tuple[str, ...]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for entry in entries:
        for pair in entry.split(","):
            source_id, separator, replacement_id = pair.partition(":")
            if not separator:
                raise click.UsageError("Each --mapping value must be written as current_id:new_id.")
            _add_mapping(mapping, source_id, replacement_id)
    return mapping


def _load_mapping_file(path: Path) -> dict[str, str]:
    if path.suffix.lower() == ".json":
        try:
            contents = json.loads(path.read_text())
        except json.JSONDecodeError as error:
            raise click.UsageError(f"{path} is not valid JSON.") from error
        if not isinstance(contents, Mapping):
            raise click.UsageError(
                "A JSON mapping file must be an object of source IDs to new IDs."
            )
        loaded_mapping: dict[str, str] = {}
        for source_id, replacement_id in contents.items():
            if not isinstance(source_id, str) or not isinstance(replacement_id, str):
                raise click.UsageError("A JSON mapping file must contain string IDs only.")
            _add_mapping(loaded_mapping, source_id, replacement_id)
        return loaded_mapping
    if path.suffix.lower() != ".csv":
        raise click.UsageError("A mapping file must be CSV or JSON.")
    with path.open(newline="") as mapping_file:
        rows = csv.DictReader(mapping_file)
        if rows.fieldnames != ["source_id", "new_id"]:
            raise click.UsageError("A CSV mapping file needs source_id,new_id column headings.")
        loaded_mapping = {}
        for row in rows:
            _add_mapping(loaded_mapping, row.get("source_id", ""), row.get("new_id", ""))
    return loaded_mapping


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
    "--sanitise-policy",
    default=None,
    help=(
        "JSON policy filename without .json: minimal (default), standard, full, retain, or custom."
    ),
)
@click.option("--subject-id", default=None, help="Starting numerical subject ID.")
@click.option("--new-id", default=None, help="Exact replacement ID for one subject only.")
@click.option("--mapping", multiple=True, help="One or more current_id:new_id pairs.")
@click.option(
    "--mapping-file",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
    default=None,
    help="CSV or JSON file mapping source IDs to replacement IDs.",
)
@click.option(
    "--keep-working-files", is_flag=True, help="Keep the copied and processed DICOM files."
)
def cli(
    source_dir: Path,
    out_dir: Path,
    sanitise: bool,
    sanitise_policy: str | None,
    subject_id: str | None,
    new_id: str | None,
    mapping: tuple[str, ...],
    mapping_file: Path | None,
    keep_working_files: bool,
) -> None:
    """Run the standard, end-to-end dichotomise pipeline."""
    sanitise = sanitise or sanitise_policy is not None
    label_sources = sum(
        (subject_id is not None, new_id is not None, bool(mapping), mapping_file is not None)
    )
    if label_sources > 1:
        raise click.UsageError(
            "Choose only one of --subject-id, --new-id, --mapping, or --mapping-file."
        )
    if not sanitise and label_sources:
        raise click.UsageError("Replacement-label options require --sanitise or --sanitise-policy.")

    effective_sanitise_policy = sanitise_policy or "minimal"
    subject_mappings = _parse_inline_mappings(mapping) if mapping else None
    if mapping_file is not None:
        subject_mappings = _load_mapping_file(mapping_file)
    label_mode = _infer_label_mode(subject_id, new_id)
    if sanitise and label_sources == 0:
        if effective_sanitise_policy == "minimal":
            label_mode = "random"
        else:
            label_mode = "numerical"
            subject_id = "1"

    console.print(f"[bold]dichotomise[/bold] processing {source_dir}")
    try:
        with status("Processing..."):
            run = run_pipeline(
                source_dir,
                out_dir,
                sanitise_requested=sanitise,
                sanitise_level=effective_sanitise_policy,
                label_mode=label_mode,
                subject_id=subject_id,
                new_id=new_id,
                subject_mappings=subject_mappings,
                keep_working_files=keep_working_files,
            )
    except DichotomiseError as failure:
        error(str(failure))
        raise SystemExit(1) from failure

    success(f"Finished: {run.root}")
    for archive in sorted(run.archives_dir.glob("*.tar.gz")):
        console.print(f"  [green]✓[/green] {archive.name}")
