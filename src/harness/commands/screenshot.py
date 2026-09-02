from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from ..test.browser import capture_screenshots

console = Console()
err_console = Console(stderr=True)


def register_command(app: typer.Typer) -> None:
    @app.command(name="screenshot")
    def screenshot(
        path: Annotated[str, typer.Argument(help="Application path to render.")],
        email: Annotated[
            str,
            typer.Option("--email", help="Email used for dev login."),
        ],
        name: Annotated[
            str | None,
            typer.Option("--name", help="Filename prefix for both screenshots."),
        ] = None,
        output_dir: Annotated[
            Path,
            typer.Option("--output-dir", help="Directory for generated PNG files."),
        ] = Path("harness-artifacts"),
        click: Annotated[
            str | None,
            typer.Option(
                "--click", help="Click the first matching locator before capture."
            ),
        ] = None,
        hover: Annotated[
            str | None,
            typer.Option(
                "--hover", help="Hover the first matching locator before capture."
            ),
        ] = None,
        expect_visible: Annotated[
            str | None,
            typer.Option(
                "--expect-visible",
                help="Require the first matching locator to be visible before capture.",
            ),
        ] = None,
        expected_status: Annotated[
            int,
            typer.Option(
                "--expect-status",
                min=100,
                max=599,
                help="Required HTTP status for the page navigation.",
            ),
        ] = 200,
    ) -> None:
        """Capture authenticated desktop and phone screenshots."""
        try:
            result = capture_screenshots(
                path,
                email=email,
                name=name,
                output_dir=output_dir,
                click=click,
                hover=hover,
                expect_visible=expect_visible,
                expected_status=expected_status,
            )
        except (OSError, RuntimeError, ValueError) as error:
            err_console.print(f"[bold red]{error}[/bold red]")
            raise typer.Exit(1) from error
        console.print(f"Desktop: {result.desktop}")
        console.print(f"Phone: {result.phone}")
        for error in result.console_errors:
            err_console.print(f"Browser console: {error}")
