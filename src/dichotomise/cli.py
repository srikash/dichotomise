"""The `dichotomise` command: reads the flags, runs the pipeline, and reports the result."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import rich_click as click
import rich_click.rich_click as rich_click_config
from rich.padding import Padding
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich_click.rich_command import RichCommand

from dichotomise.errors import DichotomiseError
from dichotomise.pipeline import run_pipeline
from dichotomise.stages.audit import AuditedFile, AuditResult
from dichotomise.utils.console import console, error, success

rich_click_config.OPTION_GROUPS = {
    "dichotomise": [
        {
            "name": "Required flags",
            "options": ["--source-dir", "--out-dir"],
            "title_style": "bold red",
        },
        {
            "name": "Optional flags",
            "options": [
                "--sanitise",
                "--sanitise-policy",
                "--subject-id",
                "--new-id",
                "--random-name",
                "--mapping",
                "--mapping-file",
                "--keep-working-files",
                "--help",
            ],
            "title_style": "bold",
        },
    ]
}
rich_click_config.OPTIONS_TABLE_COLUMN_TYPES = ["opt_short", "opt_long", "metavar", "help"]
rich_click_config.OPTIONS_TABLE_HELP_SECTIONS = ["help", "deprecated", "envvar", "default"]
rich_click_config.TEXT_MARKUP = "rich"


class DichotomiseCommand(RichCommand):
    """Render the command's usage notes in the same Rich style as its options."""

    def format_epilog(self, context: Any, formatter: Any) -> None:
        if self.epilog is None:
            return
        content = formatter.rich_text(self.epilog, formatter.config.style_epilog_text)
        panel = Panel(
            content,
            title=Text.from_markup("[bold orange1]Usage[/]"),
            title_align="left",
            border_style="orange1",
            padding=(0, 1),
        )
        formatter.write(Padding(panel, formatter.config.padding_epilog))


def _format_elapsed(seconds: float) -> str:
    """Format a stage duration for a concise CLI progress message."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, remaining_seconds = divmod(int(seconds), 60)
    return f"{minutes}m {remaining_seconds}s"


def _log_stage(status: str, description: str, elapsed_seconds: float) -> None:
    """Render the pipeline's timestamped stage progress in the v1 CLI style."""
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if status == "started":
        message = f"Started: {description}"
    elif status == "completed":
        message = f"Completed: {description} in {_format_elapsed(elapsed_seconds)}"
    else:
        message = f"Failed: {description} after {_format_elapsed(elapsed_seconds)}"
    console.print(f"[dim]{timestamp}[/] {message}")


def _audit_reasons(files: list[AuditedFile]) -> list[str]:
    """Return the per-folder data-quality and structural findings."""
    fields: dict[str, set[str | int]] = {
        "SeriesInstanceUID": {file.metadata.series_instance_uid for file in files},
        "SeriesNumber": {file.metadata.series_number for file in files},
        "SeriesDescription": {file.metadata.series_description for file in files},
        "ProtocolName": {file.metadata.protocol_name for file in files},
        "StudyDate": {file.metadata.study_date for file in files},
    }
    reasons = [f"{name} varies" for name, values in fields.items() if len(values) > 1]
    duplicate_count = sum(file.is_duplicate for file in files)
    misfiled_count = sum(file.is_misfiled for file in files)
    if duplicate_count:
        suffix = "file" if duplicate_count == 1 else "files"
        reasons.append(f"{duplicate_count} duplicate {suffix}")
    if misfiled_count:
        suffix = "file" if misfiled_count == 1 else "files"
        reasons.append(f"{misfiled_count} misfiled {suffix}")
    return reasons


def _latest_modified(files: list[AuditedFile]) -> str:
    """Return the most recent filesystem timestamp in a readable UTC form."""
    modified_time = max(file.metadata.path.stat().st_mtime for file in files)
    return datetime.fromtimestamp(modified_time, UTC).strftime("%Y-%m-%d %H:%MZ")


def _print_audit_table(audit_result: AuditResult) -> None:
    """Render every captured series with its structural and metadata findings."""
    files_by_folder: dict[Path, list[AuditedFile]] = defaultdict(list)
    for file in audit_result.files:
        files_by_folder[file.metadata.path.parent].append(file)

    table = Table(title="DICOM inventory", show_lines=False)
    table.add_column("Series folder", overflow="fold")
    table.add_column("DICOMs", justify="right")
    table.add_column("Modified")
    table.add_column("Check")
    table.add_column("Why", overflow="fold")
    for folder, files in sorted(files_by_folder.items()):
        reasons = _audit_reasons(files)
        table.add_row(
            str(folder.relative_to(audit_result.subject.directory)),
            str(len(files)),
            _latest_modified(files),
            "[green]Pass[/]" if not reasons else "[red]Failed[/]",
            "; ".join(reasons) if reasons else "—",
        )
    console.print(table)


def _report_value(report: dict[str, object], key: str) -> str:
    """Return a display value from one of the pipeline's JSON reports."""
    value = report.get(key, "—")
    return str(value)


def _print_run_summary(reports_dir: Path) -> None:
    """Render a compact per-subject audit and archive summary."""
    table = Table(title="Audit and archive summary")
    table.add_column("Subject")
    table.add_column("Files", justify="right")
    table.add_column("Duplicates", justify="right")
    table.add_column("Misfiled", justify="right")
    table.add_column("Retained", justify="right")
    table.add_column("Review", justify="right")
    table.add_column("Archive")

    for report_dir in sorted(path for path in reports_dir.iterdir() if path.is_dir()):
        audit_report = json.loads((report_dir / "stage-01-report.json").read_text())
        sift_report = json.loads((report_dir / "stage-02-report.json").read_text())
        finalise_report = json.loads((report_dir / "stage-03-report.json").read_text())
        table.add_row(
            _report_value(finalise_report, "subject_label"),
            _report_value(audit_report, "total_files"),
            _report_value(audit_report, "duplicate_count"),
            _report_value(audit_report, "misfiled_count"),
            _report_value(sift_report, "retained_count"),
            _report_value(sift_report, "review_count"),
            _report_value(finalise_report, "archive"),
        )

    console.print(Panel(table, title="Dichotomise complete", border_style="green"))


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
    cls=DichotomiseCommand,
    help=(
        "Copy, audit, sift, rectify, and archive a DICOM study. "
        "Use --sanitise to also replace patient identity before final archiving."
    ),
    epilog=(
        "[bold]Basic run[/]: dichotomise --source-dir RAW_DICOMS --out-dir OUTPUTS\n\n"
        "[bold]Relabelled run[/]: dichotomise --source-dir RAW_DICOMS --out-dir OUTPUTS "
        "--sanitise --subject-id 1\n\n"
        "The audit table is shown before rectification. Failed rows are copied to review/ "
        "rather than silently discarded."
    ),
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.option(
    "--source-dir",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
    required=True,
    panel="Required flags",
    help="Raw DICOM directory to process.",
)
@click.option(
    "--out-dir",
    type=click.Path(path_type=Path, file_okay=False),
    required=True,
    panel="Required flags",
    help="Parent directory for the timestamped dichotomise output folder.",
)
@click.option(
    "--sanitise",
    is_flag=True,
    panel="Optional flags",
    help="Replace patient identity before final archiving.",
)
@click.option(
    "--sanitise-policy",
    "--sanitise-level",
    "sanitise_policy",
    default=None,
    panel="Optional flags",
    help=(
        "JSON policy filename without .json: minimal (default), standard, full, retain, or custom."
    ),
)
@click.option(
    "--subject-id", default=None, panel="Optional flags", help="Starting numerical subject ID."
)
@click.option(
    "--new-id",
    default=None,
    panel="Optional flags",
    help="Exact replacement ID for one subject only.",
)
@click.option(
    "--random-name",
    is_flag=True,
    panel="Optional flags",
    help="Generate a random replacement name using the minimal sanitisation policy.",
)
@click.option(
    "--mapping", multiple=True, panel="Optional flags", help="One or more current_id:new_id pairs."
)
@click.option(
    "--mapping-file",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
    default=None,
    panel="Optional flags",
    help="CSV or JSON file mapping source IDs to replacement IDs.",
)
@click.option(
    "--keep-working-files",
    is_flag=True,
    panel="Optional flags",
    help="Keep the copied and processed DICOM files.",
)
def cli(
    source_dir: Path,
    out_dir: Path,
    sanitise: bool,
    sanitise_policy: str | None,
    subject_id: str | None,
    new_id: str | None,
    random_name: bool,
    mapping: tuple[str, ...],
    mapping_file: Path | None,
    keep_working_files: bool,
) -> None:
    """Run the standard, end-to-end dichotomise pipeline."""
    if random_name and sanitise_policy is not None:
        raise click.UsageError("--random-name cannot be combined with --sanitise-policy.")
    sanitise = sanitise or sanitise_policy is not None or random_name
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
    label_mode = "random" if random_name else _infer_label_mode(subject_id, new_id)
    if sanitise and label_sources == 0:
        if effective_sanitise_policy == "minimal":
            label_mode = "random"
        else:
            label_mode = "numerical"
            subject_id = "1"

    console.print(f"[bold]dichotomise[/bold] processing {source_dir}")
    try:
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
            on_audit=_print_audit_table,
            on_stage=_log_stage,
        )
    except DichotomiseError as failure:
        error(str(failure))
        raise SystemExit(1) from failure

    success(f"Finished: {run.root}")
    _print_run_summary(run.reports_dir)
    for archive in sorted(run.archives_dir.glob("*.tar.gz")):
        console.print(f"  [green]✓[/green] {archive.name}")
