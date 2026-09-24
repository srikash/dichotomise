"""The `dichotomise` command: reads the flags, runs the pipeline, and reports the result."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import rich_click as click
import rich_click.rich_click as rich_click_config
from rich.console import Group
from rich.padding import Padding
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich_click.rich_command import RichCommand

from dichotomise.errors import DichotomiseError
from dichotomise.pipeline import run_pipeline
from dichotomise.stages.audit import AuditedFile, AuditResult, metadata_inconsistencies
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
                "--subj-id",
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

_EXAMPLE_COMMAND = (
    "[bold white]dichotomise[/] "
    "[bold cyan]--source-dir[/] [green]/path/to/scanner_export[/] "
    "[bold cyan]--out-dir[/] [green]/path/to/fixed_export[/]"
)


class DichotomiseCommand(RichCommand):
    """Render the command's usage notes in the same Rich style as its options."""

    def format_epilog(self, context: Any, formatter: Any) -> None:
        if self.epilog is None:
            return
        single_subject = Panel(
            Text.from_markup(
                f"[bold cyan]Numerical:[/] {_EXAMPLE_COMMAND} "
                "[bold cyan]--sanitise[/] [bold cyan]--subj-id[/] [magenta]6[/]\n"
                "           Creates [green]sub-0006[/].\n\n"
                f"[bold cyan]Random:[/] {_EXAMPLE_COMMAND} [bold cyan]--random-name[/]\n\n"
                f"[bold cyan]Exact:[/] {_EXAMPLE_COMMAND} "
                "[bold cyan]--sanitise[/] [bold cyan]--new-id[/] [magenta]ADNC0751[/]\n"
                "       Creates [green]sub-ADNC0751[/]."
            ),
            title=Text.from_markup("[bold yellow]Single-Subject mode[/]"),
            title_align="left",
            border_style="yellow",
            padding=(0, 1),
        )
        multi_subject = Panel(
            Text.from_markup(
                f"[bold cyan]Numerical:[/] {_EXAMPLE_COMMAND} "
                "[bold cyan]--sanitise[/] [bold cyan]--subj-id[/] [magenta]6[/]\n"
                "           Creates [green]sub-0006[/], [green]sub-0007[/], [green]sub-0008[/], …\n"
                "           [yellow]Warning:[/] enumeration is enabled automatically.\n\n"
                f"[bold cyan]Random:[/] {_EXAMPLE_COMMAND} [bold cyan]--random-name[/]\n\n"
                f"[bold cyan]Mapped:[/] {_EXAMPLE_COMMAND} "
                "[bold cyan]--sanitise[/] [bold cyan]--mapping-file[/] "
                "[green]/path/to/mapping_file.json[/]"
            ),
            title=Text.from_markup("[bold yellow]Multi-Subject mode[/]"),
            title_align="left",
            border_style="yellow",
            padding=(0, 1),
        )
        content = Group(
            Text.from_markup("[bold orange1]Usage Guide:[/]"),
            Padding(single_subject, (1, 0, 0, 0)),
            Padding(multi_subject, (1, 0, 0, 0)),
        )
        formatter.write(Padding(content, formatter.config.padding_epilog))


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


def _log_warning(message: str) -> None:
    """Render a timestamped warning alongside verbose pipeline progress."""
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    console.print(f"[dim]{timestamp}[/] [yellow]Warning:[/] {message}")


def _audit_reasons(files: list[AuditedFile]) -> list[str]:
    """Return the per-folder data-quality and structural findings."""
    reasons = [f"{field} varies" for field in metadata_inconsistencies(files)]
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
            folder.name,
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
                raise click.UsageError(
                    "Each --mapping value must be written as patient_id:replacement_id."
                )
            _add_mapping(mapping, source_id, replacement_id)
    return mapping


def _load_mapping_file(path: Path) -> dict[str, str]:
    resolved_path = path if path.is_file() else path.with_suffix(".json")
    if not resolved_path.is_file():
        raise click.UsageError(f"No JSON mapping file found at {path} or {resolved_path}.")
    try:
        contents = json.loads(resolved_path.read_text())
    except json.JSONDecodeError as error:
        raise click.UsageError(f"{resolved_path} is not valid JSON.") from error
    if not isinstance(contents, Mapping):
        raise click.UsageError(
            "A JSON mapping file must be an object of PatientID to replacement ID."
        )
    loaded_mapping: dict[str, str] = {}
    for source_id, replacement_id in contents.items():
        if source_id == "instructions":
            if not isinstance(replacement_id, list) or not all(
                isinstance(instruction, str) for instruction in replacement_id
            ):
                raise click.UsageError(
                    'The optional "instructions" entry must be a list of strings.'
                )
            continue
        if not isinstance(source_id, str) or not isinstance(replacement_id, str):
            raise click.UsageError("A JSON mapping file must contain string IDs only.")
        _add_mapping(loaded_mapping, source_id, replacement_id)
    return loaded_mapping


@click.command(
    cls=DichotomiseCommand,
    help=(
        "A command-line tool for auditing, fixing, and archiving DICOM exports from Siemens "
        "XA60+ systems."
    ),
    epilog=(
        "[bold]Basic run[/]: dichotomise --source-dir /path/to/scanner_export "
        "--out-dir /path/to/fixed_export\n\n"
        "[bold]Relabelled run[/]: dichotomise --source-dir /path/to/scanner_export "
        "--out-dir /path/to/fixed_export "
        "--sanitise --subj-id 1\n\n"
        "The audit table is shown before fixing and classification. Failed series are copied to "
        "review/ rather than be quietly discarded."
    ),
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.option(
    "--source-dir",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
    required=True,
    panel="Required flags",
    help="Input directory to be processed. Can be single- or multi-subject directory.",
)
@click.option(
    "--out-dir",
    type=click.Path(path_type=Path, file_okay=False),
    required=True,
    panel="Required flags",
    help="Output directory for dichotomised results.",
)
@click.option(
    "--sanitise",
    is_flag=True,
    panel="Optional flags",
    help="Do some anonymisation before final archiving.",
)
@click.option(
    "--sanitise-policy",
    "sanitise_policy",
    default=None,
    panel="Optional flags",
    help=(
        "Use JSON policy presets: minimal (default), standard, full, retain.\n\n"
        "Custom policy names may be given with or without .json."
    ),
)
@click.option(
    "--subj-id",
    "subject_id",
    default=None,
    panel="Optional flags",
    help="Numerical replacement ID; 6 produces sub-0006.",
)
@click.option(
    "--new-id",
    default=None,
    panel="Optional flags",
    help="Replacement ID for one study; ADNC0751 becomes sub-ADNC0751.",
)
@click.option(
    "--random-name",
    is_flag=True,
    panel="Optional flags",
    help="Generate a random replacement name using the minimal sanitisation policy.",
)
@click.option(
    "--mapping",
    multiple=True,
    panel="Optional flags",
    help="PatientID:replacement_id pair; repeat the flag or separate pairs with commas.",
)
@click.option(
    "--mapping-file",
    type=click.Path(path_type=Path, dir_okay=False),
    default=None,
    panel="Optional flags",
    help="JSON file mapping PatientID to replacement ID; .json may be omitted.",
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
            "Choose only one of --subj-id, --new-id, --mapping, or --mapping-file."
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
            on_warning=_log_warning,
        )
    except DichotomiseError as failure:
        error(str(failure))
        raise SystemExit(1) from failure

    success(f"Finished: {run.root}")
    _print_run_summary(run.reports_dir)
    for archive in sorted(run.archives_dir.glob("*.tar.gz")):
        console.print(f"  [green]✓[/green] {archive.name}")
