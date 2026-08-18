"""Install commands — `menelao harness install` / `menelao harness uninstall`."""

from __future__ import annotations

from typing import Annotated, Callable, Optional

import typer
from rich.console import Console

from ..install import TARGETS, resolve_targets, run_install, run_uninstall

err_console = Console(stderr=True)


def register_commands(app: typer.Typer, *, is_dry_run: Callable[[], bool]) -> None:
    """Register install/uninstall commands on the harness app."""

    @app.command(name="install")
    def harness_install(
        agent: Annotated[
            Optional[list[str]],
            typer.Option(
                "--agent",
                help="Agent(s) to configure non-interactively. Use 'all' for every agent.",
            ),
        ] = None,
        yes: Annotated[
            bool,
            typer.Option("--yes", "-y", help="Skip confirmation prompt."),
        ] = False,
    ) -> None:
        """Install the harness MCP server into coding agent configs."""
        if is_dry_run():
            targets = resolve_targets(agent) if agent else TARGETS
            err_console.print("[cyan]Would install harness MCP server into:[/cyan]")
            for t in targets:
                err_console.print(f"  [white]{t.display_name}[/white] → {t.path}")
            return
        run_install(target_ids=agent, yes=yes)

    @app.command(name="uninstall")
    def harness_uninstall(
        agent: Annotated[
            Optional[list[str]],
            typer.Option(
                "--agent",
                help="Agent(s) to remove configuration from. Use 'all' for every agent.",
            ),
        ] = None,
        yes: Annotated[
            bool,
            typer.Option("--yes", "-y", help="Skip confirmation prompt."),
        ] = False,
    ) -> None:
        """Remove the harness MCP server from coding agent configs."""
        if is_dry_run():
            targets = resolve_targets(agent) if agent else TARGETS
            err_console.print("[cyan]Would remove harness MCP server from:[/cyan]")
            for t in targets:
                err_console.print(f"  [white]{t.display_name}[/white] → {t.path}")
            return
        run_uninstall(target_ids=agent, yes=yes)
