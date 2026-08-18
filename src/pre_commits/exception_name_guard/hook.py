"""Pre-commit hook that enforces exception class naming conventions."""

from __future__ import annotations

import ast
import signal
import sys
from pathlib import Path
from types import FrameType
from typing import Annotated, Optional

import typer
from rich.console import Console

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2

console = Console()
err_console = Console(stderr=True, soft_wrap=True)
_use_color = False


def _handle_sigterm(signum: int, frame: FrameType | None) -> None:
    raise SystemExit(EXIT_ERROR)


signal.signal(signal.SIGTERM, _handle_sigterm)


def print_error(message: str) -> None:
    if _use_color:
        err_console.print(f"[bold red]{message}[/bold red]")
    else:
        err_console.print(message, highlight=False, style=None)


def _base_name(base: ast.expr) -> str:
    if isinstance(base, ast.Name):
        return base.id
    if isinstance(base, ast.Attribute):
        return base.attr
    return ""


def _exception_classes(tree: ast.Module) -> list[ast.ClassDef]:
    classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
    exception_names = {"BaseException", "Exception"}
    found: list[ast.ClassDef] = []

    changed = True
    while changed:
        changed = False
        for node in classes:
            if node in found:
                continue
            bases = {_base_name(base) for base in node.bases}
            if bases & exception_names or any(
                base.endswith(("Exception", "Error")) for base in bases
            ):
                found.append(node)
                exception_names.add(node.name)
                changed = True

    return found


def check_single_file(filepath: Path, content: str) -> list[str]:
    try:
        tree = ast.parse(content, filename=str(filepath))
    except SyntaxError as exc:
        return [f"{filepath}:{exc.lineno}: cannot parse Python file: {exc.msg}"]

    return [
        f"{filepath}:{node.lineno}: exception class {node.name!r} must end with "
        "'Exception' or 'Error'"
        for node in _exception_classes(tree)
        if not node.name.endswith(("Exception", "Error"))
    ]


def check_files(filenames: list[Path]) -> list[str]:
    errors: list[str] = []
    for filepath in filenames:
        try:
            content = filepath.read_text(encoding="utf-8")
        except FileNotFoundError:
            errors.append(f"{filepath}: file not found")
            continue
        except PermissionError:
            errors.append(f"{filepath}: permission denied")
            continue
        except UnicodeDecodeError:
            errors.append(f"{filepath}: not a valid UTF-8 text file")
            continue
        errors.extend(check_single_file(filepath, content))
    return errors


app = typer.Typer(
    add_completion=False,
    help="Check that exception class names end with Exception or Error.",
)


@app.callback(invoke_without_command=True)
def main(
    filenames: Annotated[
        Optional[list[Path]],
        typer.Argument(help="Files to check (passed by pre-commit)."),
    ] = None,
    color: Annotated[
        bool,
        typer.Option("--color", help="Enable colored output."),
    ] = False,
) -> None:
    """Check Python exception class names."""
    global _use_color
    _use_color = color

    errors = check_files(filenames or [])
    if errors:
        for error in errors:
            print_error(error)
        raise typer.Exit(EXIT_ERROR)
    raise typer.Exit(EXIT_OK)


def cli() -> None:
    try:
        app()
    except KeyboardInterrupt:
        raise
    except BrokenPipeError:
        sys.stderr.close()
        sys.exit(EXIT_OK)
    except SystemExit as exc:
        sys.exit(exc.code)
    except Exception as exc:
        print_error(f"Unexpected error: {exc}")
        sys.exit(EXIT_ERROR)
