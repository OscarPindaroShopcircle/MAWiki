"""Test harness commands — `menelao harness test ...`."""

from __future__ import annotations

import signal
import time
from typing import Annotated

import typer
from rich.console import Console

from ..test import compose, config, ports
from ..test.server import serve as serve_test

err_console = Console(stderr=True)

test_app = typer.Typer(no_args_is_help=True, help="Test database harness.")

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2


def _teardown() -> None:
    """Stop containers and restore config. Idempotent."""
    try:
        compose.down()
    except compose.ComposeError:
        pass
    config.restore()


@test_app.command(name="serve")
def test_serve() -> None:
    """Start the test-harness MCP server over stdio (for agents)."""
    serve_test()


@test_app.command(name="up")
def test_up(
    port: Annotated[
        int,
        typer.Option(
            "--port",
            "-p",
            help="Preferred port. 0 = auto-detect free port.",
        ),
    ] = 0,
) -> None:
    """Spin up the test database. Ctrl+C to tear down."""
    try:
        config.validate()
    except config.ConfigError as exc:
        err_console.print(f"[bold red]{exc}[/bold red]")
        raise typer.Exit(code=EXIT_USAGE) from exc

    try:
        chosen = ports.find_free_port(start=port or 5432)
    except RuntimeError as exc:
        err_console.print(f"[bold red]{exc}[/bold red]")
        raise typer.Exit(code=EXIT_ERROR) from exc

    config.backup()
    config.patch_port(chosen)

    try:
        compose.up(chosen)
    except compose.ComposeError as exc:
        config.restore()
        err_console.print(f"[bold red]{exc}[/bold red]")
        raise typer.Exit(code=EXIT_ERROR) from exc

    try:
        compose.run_migrations()
    except compose.ComposeError as exc:
        err_console.print(f"[bold red]{exc}[/bold red]")
        err_console.print(
            "[yellow]Run 'menelao harness test down' to clean up.[/yellow]"
        )
        raise typer.Exit(code=EXIT_ERROR) from exc

    err_console.print(
        f"[green]Test database ready on localhost:{chosen} (db: backend_test)[/green]"
    )
    err_console.print("[cyan]Press Ctrl+C to tear down.[/cyan]")

    shutdown = False

    def _on_signal(*_args: object) -> None:
        nonlocal shutdown
        shutdown = True

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    while not shutdown:
        time.sleep(2)
        if not compose.is_healthy():
            err_console.print(
                "\n[yellow]Test container stopped (someone ran 'down'?).[/yellow]"
            )
            config.restore()
            raise typer.Exit(code=EXIT_OK)

    err_console.print("\n[cyan]Tearing down...[/cyan]")
    _teardown()
    err_console.print("[green]Done.[/green]")


@test_app.command(name="down")
def test_down() -> None:
    """Stop and remove test containers, restore config."""
    _teardown()
    err_console.print("[green]Containers stopped, config restored.[/green]")


@test_app.command(name="status")
def test_status() -> None:
    """Show test container status."""
    err_console.print(compose.status_text())
