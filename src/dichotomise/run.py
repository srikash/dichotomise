"""Run: the output paths for one dichotomise run."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from dichotomise.errors import DestinationExistsError


@dataclass(frozen=True)
class Run:
    """The output folder for one dichotomise run, and where each stage writes."""

    root: Path
    timestamp: str

    @property
    def working_dir(self) -> Path:
        return self.root / "working"

    @property
    def source_archive_dir(self) -> Path:
        return self.root / "source"

    @property
    def archives_dir(self) -> Path:
        return self.root / "archives"

    @property
    def reports_dir(self) -> Path:
        return self.root / "reports"

    @property
    def status_path(self) -> Path:
        """Return the file recording whether this run completed."""
        return self.root / "run-status.json"

    def set_status(self, status: str) -> None:
        """Record the current lifecycle status without storing patient information."""
        self.status_path.write_text(json.dumps({"status": status}) + "\n")


def start_run(out_dir: Path, *, now: datetime | None = None) -> Run:
    """Create a new, timestamped run folder under `out_dir` and return its Run.

    Raises DestinationExistsError, rather than a raw filesystem error, on
    the rare case of two runs starting within the same second.
    """
    timestamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    root = out_dir / f"{timestamp}_dichotomise_outputs"
    try:
        root.mkdir(parents=True)
    except FileExistsError as error:
        raise DestinationExistsError(
            f"A run folder already exists for this second: {root}. Wait a moment and try again."
        ) from error
    run = Run(root=root, timestamp=timestamp)
    run.set_status("in_progress")
    return run
