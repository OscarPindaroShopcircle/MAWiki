from typing import Annotated

import typer
from rich.console import Console

from ..test import environment, state

console = Console()
err_console = Console(stderr=True)
env_app = typer.Typer(
    no_args_is_help=True, help="Create isolated development environments."
)


@env_app.command()
def up(
    mode: Annotated[
        state.EnvironmentMode,
        typer.Option(
            help="local starts PostgreSQL; docker also starts backend and Open WebUI."
        ),
    ] = state.EnvironmentMode.LOCAL,
    database_port: Annotated[int, typer.Option("--db-port", min=0, max=65535)] = 0,
    backend_port: Annotated[int, typer.Option("--backend-port", min=0, max=65535)] = 0,
    openwebui_port: Annotated[
        int, typer.Option("--openwebui-port", min=0, max=65535)
    ] = 0,
) -> None:
    """Start an isolated environment using .env.test and config.test.yaml."""
    try:
        environment_state = environment.up(
            mode,
            database_port=database_port,
            backend_port=backend_port,
            openwebui_port=openwebui_port,
        )
    except environment.EnvironmentError as error:
        err_console.print(f"[bold red]{error}[/bold red]")
        raise typer.Exit(1) from error
    console.print(
        f"[green]{environment_state.mode.value} environment ready[/green] "
        f"(database: localhost:{environment_state.ports.database})"
    )
    if environment_state.mode == state.EnvironmentMode.DOCKER:
        console.print(f"Backend: http://localhost:{environment_state.ports.backend}")
        console.print(
            f"Open WebUI: http://localhost:{environment_state.ports.openwebui}"
        )


@env_app.command()
def status() -> None:
    """Show the active environment for this worktree."""
    try:
        environment_state, output = environment.status()
    except environment.EnvironmentError as error:
        err_console.print(f"[bold red]{error}[/bold red]")
        raise typer.Exit(1) from error
    if environment_state is not None:
        console.print(
            f"[cyan]{environment_state.mode.value}[/cyan] "
            f"project={environment_state.compose_project}"
        )
    console.print(output)


@env_app.command()
def teardown() -> None:
    """Stop the active environment and restore config.test.yaml."""
    try:
        environment.teardown()
    except environment.EnvironmentError as error:
        err_console.print(f"[bold red]{error}[/bold red]")
        raise typer.Exit(1) from error
    console.print("[green]Environment stopped and config restored.[/green]")
