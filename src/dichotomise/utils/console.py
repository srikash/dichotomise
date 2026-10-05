"""A small Rich Console wrapper: status(), progress(), success(), error()."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from rich.console import Console

__all__ = ["Console", "console", "error", "status", "success"]

console = Console()


def success(message: str) -> None:
    """Print a message marking something as finished, in green.

    soft_wrap: `message` often contains a filesystem path, which must never
    be broken across lines by Rich's column-wrapping.
    """
    console.print(f"[bold green]✓[/bold green] {message}", soft_wrap=True)


def error(message: str) -> None:
    """Print a message marking something as failed, in red."""
    console.print(f"[bold red]✗[/bold red] {message}", soft_wrap=True)


@contextmanager
def status(message: str) -> Iterator[None]:
    """Show a spinner with `message` for the duration of the wrapped block."""
    with console.status(message):
        yield
