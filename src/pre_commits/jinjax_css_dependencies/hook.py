from __future__ import annotations

import re
import signal
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2

err_console = Console(stderr=True, soft_wrap=True)

DEFAULT_COMPONENTS_DIR = Path("src/frontend/components")
COMPONENT_TAG = re.compile(r"<\s*((?:[A-Za-z_][A-Za-z0-9_]*\.)*[A-Z][A-Za-z0-9_]*)\b")
CSS_DIRECTIVE = re.compile(r"(?m)^\s*\{#css\s+(.+?)\s*#\}\s*\n?")
DEF_DIRECTIVE = re.compile(r"\A\s*\{#def.*?#\}\s*", re.DOTALL)
COMMENTS = re.compile(r"\{#.*?#\}|<!--.*?-->", re.DOTALL)


def _handle_sigterm(signum: int, frame: object) -> None:
    raise SystemExit(EXIT_ERROR)


signal.signal(signal.SIGTERM, _handle_sigterm)


def component_references(source: str) -> tuple[str, ...]:
    source = COMMENTS.sub("", source)
    return tuple(
        dict.fromkeys(match.group(1) for match in COMPONENT_TAG.finditer(source))
    )


class DependencyResolver:
    def __init__(self, components_dir: Path):
        self.components_dir = components_dir
        self.cache: dict[Path, set[str]] = {}
        self.resolving: set[Path] = set()

    def dependencies(self, component: Path) -> set[str]:
        if component in self.cache:
            return self.cache[component]
        if component in self.resolving:
            return set()

        self.resolving.add(component)
        dependencies: set[str] = set()
        for reference in component_references(component.read_text(encoding="utf-8")):
            child = self.components_dir.joinpath(*reference.split(".")).with_suffix(
                ".jinja"
            )
            if not child.is_file():
                continue
            css_path = child.with_suffix(".css")
            if css_path.is_file():
                dependencies.add(css_path.relative_to(self.components_dir).as_posix())
            dependencies.update(self.dependencies(child))
        self.resolving.remove(component)
        self.cache[component] = dependencies
        return dependencies


def _css_assets(match: re.Match[str]) -> list[str]:
    return [asset.strip() for asset in match.group(1).split(",") if asset.strip()]


def _with_dependencies(source: str, dependencies: set[str]) -> str:
    match = CSS_DIRECTIVE.search(source)
    existing = _css_assets(match) if match else []
    assets = [
        *existing,
        *(asset for asset in sorted(dependencies) if asset not in existing),
    ]
    if not assets:
        return source

    directive = "{#css " + ", ".join(assets) + " #}\n"
    if match:
        return source[: match.start()] + directive + source[match.end() :]

    definition = DEF_DIRECTIVE.match(source)
    insertion = definition.end() if definition else 0
    return source[:insertion] + directive + source[insertion:]


def run_check(components_dir: Path, *, check: bool = False) -> list[Path]:
    resolver = DependencyResolver(components_dir)
    changed: list[Path] = []
    for component in sorted(components_dir.rglob("*.jinja")):
        source = component.read_text(encoding="utf-8")
        updated = _with_dependencies(source, resolver.dependencies(component))
        if updated == source:
            continue
        changed.append(component)
        if not check:
            component.write_text(updated, encoding="utf-8")
    return changed


app = typer.Typer(
    add_completion=False,
    help="Synchronize JinjaX CSS dependencies with referenced components.",
)


@app.callback(invoke_without_command=True)
def main(
    filenames: Annotated[
        Optional[list[Path]],
        typer.Argument(
            help="Staged files from pre-commit. Accepted but not used for scoping."
        ),
    ] = None,
    components_dir: Annotated[
        Path,
        typer.Option(
            "--components-dir", help="Root directory containing JinjaX components."
        ),
    ] = DEFAULT_COMPONENTS_DIR,
    check: Annotated[
        bool,
        typer.Option(
            "--check", help="Report unsynchronized dependencies without writing."
        ),
    ] = False,
) -> None:
    if not components_dir.is_dir():
        err_console.print(f"{components_dir}: components directory not found")
        raise typer.Exit(EXIT_USAGE)

    changed = run_check(components_dir, check=check)
    if not changed:
        raise typer.Exit(EXIT_OK)

    action = (
        "out of sync — run without --check to synchronize"
        if check
        else "CSS dependencies synchronized"
    )
    for path in changed:
        err_console.print(f"{path}: {action}")
    raise typer.Exit(EXIT_ERROR)


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
        err_console.print(f"Unexpected error: {exc}")
        sys.exit(EXIT_ERROR)
