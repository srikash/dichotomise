"""A small Rich Console wrapper: success(), error()."""

from __future__ import annotations

from rich.console import Console

__all__ = ["Console", "console", "error", "success"]

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
