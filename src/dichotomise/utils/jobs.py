"""The user's `--jobs` choice, shared by the header readers and `pigz`.

One pipeline runs per process, so a module-level setting is enough; both readers
sit in the parent process, so the worker processes never need it.
"""

from __future__ import annotations

_jobs: int | None = None


def set_jobs(count: int | None) -> None:
    """Fix the number of parallel workers, or None to size them automatically."""
    global _jobs
    _jobs = count


def get_jobs() -> int | None:
    """The `--jobs` count, or None when it is left automatic."""
    return _jobs
