"""Harness CLI — `menelao harness ...`."""

from __future__ import annotations

import enum
import signal
import sys
from typing import Annotated, Optional

import typer
from rich.console import Console

from .commands.environment import env_app
from .commands.install import register_commands as register_install_commands
from .commands.test import test_app

err_console = Console(stderr=True)


class Verbosity(enum.IntEnum):
    QUIET = 0
    NORMAL = 1
    VERBOSE = 2


_verbosity: Verbosity = Verbosity.NORMAL
_dry_run: bool = False


def should_print(min_level: Verbosity) -> bool:
    return _verbosity >= min_level


EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_INTERRUPTED = 130


def _handle_sigterm(signum: int, frame: object) -> None:
    err_console.print("[bold yellow]Received SIGTERM — shutting down.[/bold yellow]")
    raise SystemExit(EXIT_INTERRUPTED)


signal.signal(signal.SIGTERM, _handle_sigterm)

app = typer.Typer(no_args_is_help=True, help="Development harnesses for agents.")


@app.callback()
def main(
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Increase output verbosity."),
    ] = False,
    quiet: Annotated[
        bool,
        typer.Option("--quiet", "-q", help="Suppress all non-error output."),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show what would happen without executing."),
    ] = False,
) -> None:
    """Menelao development harnesses — spin up test environments, configure agents."""
    global _verbosity, _dry_run
    if verbose and quiet:
        err_console.print("[bold red]-v and -q are mutually exclusive.[/bold red]")
        raise typer.Exit(code=EXIT_USAGE)
    if verbose:
        _verbosity = Verbosity.VERBOSE
    elif quiet:
        _verbosity = Verbosity.QUIET
    _dry_run = dry_run
    if _dry_run and should_print(Verbosity.NORMAL):
        err_console.print(
            "[bold yellow]Dry-run mode — no changes will be made.[/bold yellow]"
        )


app.add_typer(env_app, name="env")
app.add_typer(test_app, name="test")
register_install_commands(app, is_dry_run=lambda: _dry_run)


def cli() -> None:
    """Entrypoint for pyproject.toml [project.scripts]."""
    try:
        app()
    except KeyboardInterrupt:
        err_console.print("\n[yellow]Interrupted.[/yellow]")
        sys.exit(EXIT_INTERRUPTED)
    except BrokenPipeError:
        sys.stderr.close()
        sys.exit(EXIT_OK)
    except SystemExit as exc:
        sys.exit(exc.code)
    except Exception as exc:
        err_console.print(f"[bold red]Unexpected error: {exc}[/bold red]")
        sys.exit(EXIT_ERROR)
