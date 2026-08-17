"""Pre-commit hook: check Jinja templates against the Pydantic models routes pass.

Discovers routes from ``views.py`` modules, works out which Pydantic model each
template's context variables hold, then walks each template's AST and reports any
attribute that does not exist on the resolved model.

The analysis is deliberately **whole-program**: renaming a field in a schema can
break a template nobody touched, so the staged filenames pre-commit passes are
accepted but not used to narrow the work. ``files:`` in the hook config only
decides whether to run at all.

Non-goals, stated plainly because the checker's credibility depends on them being
known:

* **No None-safety.** ``Optional`` is stripped, so ``card.latest_task.completion``
  is never flagged even though ``latest_task`` may be ``None``. Jinja renders such
  a deref as blank output rather than raising, so this bug class stays invisible
  here; only a render test catches it.
* **No expression inference.** Anything downstream of a filter, method call or
  arithmetic is unknown, and unknown never produces a diagnostic.
* **No ``{% if %}`` narrowing and no union discrimination.**
* **No macros or computed include names** — these are E900, not silently skipped.
"""

from __future__ import annotations

import importlib
import signal
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console

from .diagnostics import WARNING_CODES, Diagnostic
from .discovery import find_bindings
from .resolver import ResolutionError, Resolver
from .typerefs import TypeRef, normalize
from .walker import TemplateChecker

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2

DEFAULT_ENV_FACTORY = "backend.jinja:_build_templates"

# soft_wrap keeps one diagnostic on one line, so output stays greppable and
# `file:line:` prefixes are not broken across terminal-width boundaries.
console = Console(soft_wrap=True)
err_console = Console(stderr=True, soft_wrap=True)

_use_color: bool = False


def _handle_sigterm(signum: int, frame) -> None:
    raise SystemExit(EXIT_ERROR)


signal.signal(signal.SIGTERM, _handle_sigterm)


def print_error(msg: str) -> None:
    if _use_color:
        err_console.print(f"[bold red]{msg}[/bold red]")
    else:
        err_console.print(msg, highlight=False, style=None)


def print_warning(msg: str) -> None:
    if _use_color:
        err_console.print(f"[yellow]{msg}[/yellow]")
    else:
        err_console.print(msg, highlight=False, style=None)


def print_info(msg: str) -> None:
    if _use_color:
        err_console.print(f"[cyan]{msg}[/cyan]")
    else:
        err_console.print(msg, highlight=False, style=None)


app = typer.Typer(
    add_completion=False,
    help="Check that Jinja templates only access attributes their Pydantic context models have.",
)


def _import_object(dotted: str) -> object:
    """Import ``pkg.mod:attr`` or ``pkg.mod.attr``."""
    if ":" in dotted:
        module_name, _, attr = dotted.partition(":")
    else:
        module_name, _, attr = dotted.rpartition(".")
    module = importlib.import_module(module_name)
    obj = getattr(module, attr, None)
    if obj is None:
        raise AttributeError(f"{module_name} has no attribute {attr!r}")
    return obj


def _build_environment(templates_dir: Path, factory: str):
    """The app's own Jinja environment.

    Filters are resolved at compile time, so an environment missing the app's
    custom filters would report phantom errors on templates that use them.
    Failing to build the real environment is a hard error, not a fallback case:
    a bare ``Environment`` would silently skip the app's custom filters and
    give false confidence, which is worse than a loud failure.
    """
    try:
        built = _import_object(factory)(str(templates_dir))
    except Exception as exc:
        raise ResolutionError(
            f"could not build env factory '{factory}' ({exc}). "
            "The application may not be packaged -- check your uv pyproject.toml -- "
            f"or the factory '{factory}' has been moved."
        ) from exc
    return getattr(built, "env", built)


def _override_context(
    overrides: dict[str, str],
) -> tuple[dict[str, TypeRef], list[str]]:
    context: dict[str, TypeRef] = {}
    problems: list[str] = []
    for name, dotted in overrides.items():
        try:
            context[name] = normalize(_import_object(dotted))
        except Exception as exc:
            problems.append(
                f"override '{name}: {dotted}' could not be imported ({exc})"
            )
    return context, problems


def _label(context: dict[str, TypeRef]) -> str:
    inner = ", ".join(f"{k}: {v.label()}" for k, v in sorted(context.items()))
    return "{" + inner + "}"


def run_check(
    templates_dir: Path,
    source_root: Path,
    views_glob: str,
    repo_root: Path,
    env_factory: str,
    exclude_view_dirs: tuple[str, ...] = ("testdata",),
) -> tuple[list[Diagnostic], list[str]]:
    """Returns (diagnostics, warnings)."""
    resolved_root = str(source_root.resolve())
    if resolved_root not in sys.path:
        sys.path.insert(0, resolved_root)

    template_names = sorted(
        p.relative_to(templates_dir).as_posix() for p in templates_dir.rglob("*.html")
    )
    if not template_names:
        return [], [f"no templates found under {templates_dir}"]

    # `testdata` holds this checker's own fixture views, which render fixture
    # templates living outside `templates/`. A whole-program run must skip them or
    # every fixture route warns; the tests that target them pass no exclusions.
    view_paths = [
        path
        for path in sorted(repo_root.glob(views_glob))
        if not any(part in exclude_view_dirs for part in path.parts)
    ]
    bindings, warnings = find_bindings(view_paths, source_root)
    if not bindings:
        warnings.append(
            f"no TemplateResponse call sites discovered via '{views_glob}' - "
            "nothing could be checked"
        )

    env = _build_environment(templates_dir, env_factory)
    resolver = Resolver()

    diagnostics: list[Diagnostic] = []
    visited: set[str] = set()
    checked: set[str] = set()

    # Per-template overrides, read from `{# type: name: dotted.Path #}` headers.
    overrides: dict[str, dict[str, str]] = {}
    probe = TemplateChecker(env)
    for name in template_names:
        try:
            from .diagnostics import scan_suppressions

            found = scan_suppressions(probe.source(name)).overrides
        except Exception:
            found = {}
        if found:
            overrides[name] = found

    for binding in bindings:
        for position, template in enumerate(binding.templates):
            if template not in template_names:
                warnings.append(
                    f"{binding.where}: renders '{template}', which does not exist "
                    f"under {templates_dir}"
                )
                continue
            dict_key = (
                binding.dict_keys[position]
                if binding.dict_keys and position < len(binding.dict_keys)
                else None
            )
            context, resolve_warnings = resolver.resolve_binding(binding, dict_key)
            warnings.extend(resolve_warnings)

            extra, problems = _override_context(overrides.get(template, {}))
            warnings.extend(f"{template}: {p}" for p in problems)
            context.update(extra)

            checker = TemplateChecker(env, binding_label=_label(context))
            result = checker.check(template, context)
            diagnostics.extend(result.diagnostics)
            visited |= result.visited
            checked.add(template)

    # Templates with an explicit override but no discovered route still get checked.
    for template, raw in overrides.items():
        if template in checked:
            continue
        context, problems = _override_context(raw)
        warnings.extend(f"{template}: {p}" for p in problems)
        checker = TemplateChecker(env, binding_label=_label(context))
        result = checker.check(template, context)
        diagnostics.extend(result.diagnostics)
        visited |= result.visited
        checked.add(template)

    for name in template_names:
        if name not in visited:
            warnings.append(
                f"{name}: not rendered by any discovered route and never included, "
                "so it was not checked"
            )

    unique: dict[tuple, Diagnostic] = {}
    for diag in diagnostics:
        unique.setdefault((diag.code, diag.template, diag.lineno, diag.message), diag)
    ordered = sorted(unique.values(), key=lambda d: (d.template, d.lineno, d.code))
    return ordered, warnings


@app.callback(invoke_without_command=True)
def main(
    filenames: Annotated[
        Optional[list[Path]],
        typer.Argument(
            help="Staged files from pre-commit. Accepted but not used for scoping: "
            "the check is whole-program."
        ),
    ] = None,
    templates_dir: Annotated[
        Path,
        typer.Option("--templates-dir", help="Root of the Jinja templates."),
    ] = Path("templates"),
    source_root: Annotated[
        Path,
        typer.Option("--source-root", help="Import root for view modules."),
    ] = Path("src"),
    views_glob: Annotated[
        str,
        typer.Option("--views-glob", help="Glob for modules holding view routes."),
    ] = "src/**/*views.py",
    env_factory: Annotated[
        str,
        typer.Option(
            "--env-factory",
            help="'module:callable' taking a templates dir and returning a Jinja "
            "environment, so the app's custom filters are honoured.",
        ),
    ] = DEFAULT_ENV_FACTORY,
    exclude_view_dir: Annotated[
        Optional[list[str]],
        typer.Option(
            "--exclude-view-dir",
            help="Directory name to drop from the views glob (repeatable). "
            "Defaults to 'testdata'.",
        ),
    ] = None,
    strict: Annotated[
        bool,
        typer.Option(
            "--strict",
            help="Treat unresolved context types and unchecked templates as failures.",
        ),
    ] = False,
    color: Annotated[
        bool, typer.Option("--color", help="Enable colored output.")
    ] = False,
) -> None:
    """Check templates against the Pydantic models their routes pass."""
    global _use_color
    _use_color = color

    repo_root = Path.cwd()
    if not templates_dir.is_dir():
        print_error(f"{templates_dir}: templates directory not found")
        raise typer.Exit(EXIT_USAGE)
    if not source_root.is_dir():
        print_error(f"{source_root}: source root not found")
        raise typer.Exit(EXIT_USAGE)

    if str(source_root.resolve()) not in sys.path:
        sys.path.insert(0, str(source_root.resolve()))

    try:
        diagnostics, warnings = run_check(
            templates_dir=templates_dir,
            source_root=source_root,
            views_glob=views_glob,
            repo_root=repo_root,
            env_factory=env_factory,
            exclude_view_dirs=tuple(exclude_view_dir or ["testdata"]),
        )
    except ResolutionError as exc:
        print_error(str(exc))
        raise typer.Exit(EXIT_USAGE)

    errors = [d for d in diagnostics if d.code not in WARNING_CODES]

    for diag in errors:
        for line in diag.render(templates_dir):
            print_error(line)

    if warnings and (strict or errors):
        for warning in warnings:
            print_warning(f"warning: {warning}")

    if errors or (strict and warnings):
        raise typer.Exit(EXIT_ERROR)

    # Silent success.
    raise typer.Exit(EXIT_OK)


def cli() -> None:
    try:
        app()
    except KeyboardInterrupt:
        # 130 is reserved by pre-commit for user interrupt; let it propagate.
        raise
    except BrokenPipeError:
        sys.stderr.close()
        sys.exit(EXIT_OK)
    except SystemExit as exc:
        sys.exit(exc.code)
    except ResolutionError as exc:
        print_error(str(exc))
        sys.exit(EXIT_USAGE)
    except Exception as exc:
        print_error(f"Unexpected error: {exc}")
        sys.exit(EXIT_ERROR)
