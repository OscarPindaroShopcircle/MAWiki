"""Pre-commit hook: keep ``src/backend/db/registry.py`` in sync with model classes.

Scans every ``models.py`` (and ``models/*.py``) under ``src/backend/`` —
excluding the ``db/`` package itself — for ``class X(Base, ...)`` definitions
via AST, then rewrites ``db/registry.py`` so it imports every discovered model
class by name. ``db/registry.py`` is the single import point that registers all
tables with ``Base.metadata`` for alembic / ``create_all``.

Why AST, not regex:
    A regex for ``class \\w+(Base`` would false-positive on ``class Foo(BaseMixin)``
    and miss ``class Foo(  Base  , Mixin)``. AST parsing resolves the base list
    exactly — a class is a model iff one of its bases is a ``Name`` or
    ``Attribute`` whose final segment is ``Base``.

Why per-class, not per-module:
    Importing the module is enough to register the table, but naming every
    class makes the registry greppable and lets ``__all__`` serve as a quick
    inventory. The ``# noqa: F401`` marks each import as intentionally
    side-effect-only.

Circular-import safety:
    The registry is imported only by entry points (``alembic/env.py``,
    ``server.py``). ``db/db.py`` and ``db/__init__.py`` never import the
    registry or any feature module, so there is no cycle regardless of the
    order of the lines below — each model module imports ``Base`` itself
    before its class body runs.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2

err_console = Console(stderr=True, soft_wrap=True)

DEFAULT_BACKEND_ROOT = Path("src/backend")
DEFAULT_REGISTRY = Path("src/backend/db/registry.py")
DEFAULT_SOURCE_ROOT = Path("src")

# The db/ package is infrastructure (Base, mixins, enums, the registry itself)
# — never scanned for models.
DB_PACKAGE_NAME = "db"


@dataclass(frozen=True)
class ModelClass:
    """A discovered ``class X(Base, ...)``."""

    name: str
    module_dotted: str  # relative import path from db/, e.g. "..users.models"


def _is_base(node: ast.expr) -> bool:
    """True if *node* is ``Base`` or ``something.Base``."""
    if isinstance(node, ast.Name):
        return node.id == "Base"
    if isinstance(node, ast.Attribute):
        return node.attr == "Base"
    return False


def _extract_models(file_path: Path, backend_root: Path) -> list[ModelClass]:
    """Parse *file_path* and return every ``class X(Base, ...)`` it defines."""
    source = file_path.read_text()
    tree = ast.parse(source, filename=str(file_path))

    # Relative import path from db/ to this module: "..users.models"
    rel = file_path.relative_to(backend_root).with_suffix("")
    dotted = ".." + ".".join(rel.parts)

    models: list[ModelClass] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if any(_is_base(base) for base in node.bases):
            models.append(ModelClass(name=node.name, module_dotted=dotted))
    return models


def discover_models(backend_root: Path) -> list[ModelClass]:
    """Find all model classes under *backend_root*, excluding ``db/``.

    Scans both ``<feature>/models.py`` and ``<feature>/models/*.py`` to support
    future features that grow beyond a single model file.
    """
    if not backend_root.is_dir():
        return []

    results: list[ModelClass] = []
    # <feature>/models.py
    for file_path in sorted(backend_root.glob("*/models.py")):
        if file_path.parent.name == DB_PACKAGE_NAME:
            continue
        results.extend(_extract_models(file_path, backend_root))
    # <feature>/models/*.py  (package-per-feature, future-proofing)
    for file_path in sorted(backend_root.glob("*/models/*.py")):
        if file_path.parent.parent.name == DB_PACKAGE_NAME:
            continue
        if file_path.name.startswith("_"):
            continue
        results.extend(_extract_models(file_path, backend_root))
    return results


def generate_registry(models: list[ModelClass], header: str) -> str:
    """Build the full text of ``db/registry.py`` from *models*.

    *header* is preserved verbatim — typically the module docstring and any
    comments before the first import line.
    """
    # Group by module, sort classes within each group.
    by_module: dict[str, list[str]] = {}
    for m in models:
        by_module.setdefault(m.module_dotted, []).append(m.name)
    for names in by_module.values():
        names.sort()

    lines: list[str] = []
    for module in sorted(by_module):
        names = by_module[module]
        if len(names) == 1:
            lines.append(f"from {module} import {names[0]}  # noqa: F401")
        else:
            inner = ",\n    ".join(names)
            lines.append(f"from {module} import (  # noqa: F401\n    {inner},\n)")

    all_names = sorted(m.name for m in models)
    all_block = "__all__ = [\n" + "\n".join(f'    "{n}",' for n in all_names) + "\n]\n"

    body = "\n".join(lines)
    return f"{header.rstrip()}\n\n{body}\n\n{all_block}"


def _split_header(text: str) -> tuple[str, str]:
    """Split registry source into (header, rest) at the first import line.

    *header* is everything before the first ``from `` / ``import `` line —
    preserved verbatim so the docstring and any comments survive rewrites.
    """
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("from ") or stripped.startswith("import "):
            return "".join(lines[:i]), "".join(lines[i:])
    return text, ""


def run_check(
    backend_root: Path,
    registry_path: Path,
    *,
    check: bool = False,
) -> tuple[bool, str]:
    """Synchronise *registry_path* with the discovered models.

    Returns ``(in_sync, generated)``. When *check* is False and the file is
    out of sync, the registry is rewritten in place.
    """
    models = discover_models(backend_root)
    if not models:
        return False, ""

    existing = registry_path.read_text() if registry_path.is_file() else ""
    header, _ = _split_header(existing) if existing else ("", "")
    if not header:
        # Fall back to a minimal header so the file is never empty.
        header = (
            '"""Central import point that registers every model with Base.metadata."""'
        )

    generated = generate_registry(models, header)

    if generated == existing:
        return True, generated

    if not check:
        registry_path.write_text(generated)
    return False, generated


app = typer.Typer(
    add_completion=False,
    help="Keep db/registry.py in sync with model class definitions.",
)


@app.callback(invoke_without_command=True)
def main(
    filenames: Annotated[
        Optional[list[Path]],
        typer.Argument(
            help="Staged files from pre-commit. Accepted but not used for scoping: "
            "the check is whole-program.",
        ),
    ] = None,
    source_root: Annotated[
        Path,
        typer.Option("--source-root", help="Import root (unused, kept for symmetry)."),
    ] = DEFAULT_SOURCE_ROOT,
    backend_root: Annotated[
        Path,
        typer.Option("--backend-root", help="Root of the backend package to scan."),
    ] = DEFAULT_BACKEND_ROOT,
    registry: Annotated[
        Path,
        typer.Option("--registry", help="Path to db/registry.py to maintain."),
    ] = DEFAULT_REGISTRY,
    check: Annotated[
        bool,
        typer.Option(
            "--check",
            help="CI mode: never write, just exit 1 if the registry is out of sync.",
        ),
    ] = False,
) -> None:
    """Synchronise db/registry.py with the model classes discovered under backend/."""
    if not backend_root.is_dir():
        err_console.print(f"{backend_root}: backend root not found")
        raise typer.Exit(EXIT_USAGE)
    if not registry.parent.is_dir():
        err_console.print(f"{registry}: parent directory not found")
        raise typer.Exit(EXIT_USAGE)

    in_sync, generated = run_check(backend_root, registry, check=check)
    if in_sync:
        raise typer.Exit(EXIT_OK)

    if check:
        err_console.print(f"{registry}: out of sync — run locally to fix")
    else:
        err_console.print(f"{registry}: rewritten to match discovered models")
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
