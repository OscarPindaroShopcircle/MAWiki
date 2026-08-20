"""Test commands — `menelao harness test ...`."""

from __future__ import annotations

import subprocess
from typing import Annotated

import typer
from rich.console import Console

from ..test import environment, state
from ..test.server import serve as serve_test

err_console = Console(stderr=True)
test_app = typer.Typer(
    no_args_is_help=True, help="Run tests against active environments."
)


def _run(command: list[str]) -> None:
    result = subprocess.run(command)
    if result.returncode:
        raise typer.Exit(result.returncode)


def _require_environment(mode: state.EnvironmentMode | None = None) -> None:
    environment_state, _ = environment.status()
    if environment_state is None:
        raise typer.BadParameter("No active environment for this worktree.")
    if mode is not None and environment_state.mode != mode:
        raise typer.BadParameter(
            f"This command requires a {mode.value} environment, found {environment_state.mode.value}."
        )


@test_app.command()
def serve() -> None:
    """Start the test-harness MCP server over stdio."""
    serve_test()


@test_app.command()
def unit() -> None:
    """Run unit tests without an environment."""
    _run(["uv", "run", "pytest", "tests/unit"])


@test_app.command()
def integration() -> None:
    """Run integration tests against the active test database."""
    _require_environment()
    _run(["uv", "run", "pytest", "-m", "integration"])


@test_app.command()
def e2e() -> None:
    """Run E2E tests against the active Docker environment."""
    _require_environment(state.EnvironmentMode.DOCKER)
    _run(["uv", "run", "pytest", "-m", "e2e"])


@test_app.command()
def run(
    command: Annotated[
        list[str], typer.Argument(help="Command to run after environment startup.")
    ],
    mode: Annotated[
        state.EnvironmentMode, typer.Option()
    ] = state.EnvironmentMode.LOCAL,
) -> None:
    """Create an environment, run a command, and always tear it down."""
    if state.read() is not None:
        raise typer.BadParameter(
            "Teardown the active environment before using test run."
        )
    try:
        environment.up(mode)
        _run(command)
    except environment.EnvironmentError as error:
        err_console.print(f"[bold red]{error}[/bold red]")
        raise typer.Exit(1) from error
    finally:
        try:
            environment.teardown()
        except environment.EnvironmentError as error:
            err_console.print(f"[bold red]{error}[/bold red]")
