"""Pre-commit hook that prevents direct database commits in Python files."""

from __future__ import annotations

import ast
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2

# This deliberately accepts any receiver name (session, db_session, tx, etc.).
# It is only a fast candidate filter; AST validation below avoids strings/comments.
COMMIT_CALL_RE = re.compile(r"\b[A-Za-z_]\w*\s*\.\s*commit\s*\(")
GREP_COMMIT_PATTERN = (
    r"(^|[^[:alnum:]_])[[:alpha:]_][[:alnum:]_]*"
    r"[[:space:]]*\.[[:space:]]*commit[[:space:]]*\("
)

err_console = Console(stderr=True, soft_wrap=True)


@dataclass(frozen=True)
class CommitViolation:
    path: Path
    line: int
    column: int
    function: str

    def format(self) -> str:
        return f"{self.path}:{self.line}:{self.column}: direct commit() is forbidden"


def _matches_path(path: Path, configured: str) -> bool:
    """Match absolute, relative, or repository-suffix paths."""
    candidate = Path(configured)
    resolved = path.resolve()
    if candidate.is_absolute():
        return resolved == candidate.resolve()
    normalized = path.as_posix()
    configured_posix = candidate.as_posix().removeprefix("./")
    return normalized == configured_posix or normalized.endswith("/" + configured_posix)


def _function_for_call(tree: ast.AST, call: ast.Call) -> str:
    """Return the innermost enclosing function name, or ``<module>``."""
    owner = "<module>"
    owner_start = -1
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        end = getattr(node, "end_lineno", node.lineno)
        if node.lineno <= call.lineno <= end and node.lineno >= owner_start:
            owner = node.name
            owner_start = node.lineno
    return owner


def _allowed_function(path: Path, function: str, allowed: tuple[str, ...]) -> bool:
    return any(
        ":" in spec
        and _matches_path(path, spec.rsplit(":", 1)[0])
        and function == spec.rsplit(":", 1)[1]
        for spec in allowed
    )


def scan_file(
    path: Path, allowed_functions: tuple[str, ...] = ()
) -> list[CommitViolation]:
    """Find real ``anything.commit()`` calls in *path*.

    Regex makes clean files cost one read and one search. Files with candidates
    are parsed with AST so comments, strings, and function-scoped exceptions are
    handled correctly.
    """
    try:
        source = path.read_text()
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    if not COMMIT_CALL_RE.search(source):
        return []

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        raise ValueError(f"cannot parse {path}: {exc}") from exc

    violations: list[CommitViolation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "commit" or not isinstance(
            node.func.value, (ast.Name, ast.Attribute)
        ):
            continue
        function = _function_for_call(tree, node)
        if not _allowed_function(path, function, allowed_functions):
            violations.append(
                CommitViolation(path, node.lineno, node.col_offset + 1, function)
            )
    return violations


def _needs_ast(path: Path, allowed_functions: tuple[str, ...]) -> bool:
    """Return whether *path* has a function-scoped exception to resolve."""
    return any(
        ":" in spec and _matches_path(path, spec.rsplit(":", 1)[0])
        for spec in allowed_functions
    )


def _grep_candidates(paths: list[Path]) -> list[Path]:
    """Find files containing textual candidates with grep."""
    if shutil.which("grep") is None:
        raise OSError("grep is not available")
    result = subprocess.run(
        ["grep", "-l", "-E", GREP_COMMIT_PATTERN, "--", *(str(p) for p in paths)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in (0, 1):
        raise OSError(result.stderr.strip() or "grep failed")

    candidates: list[Path] = []
    for output_line in result.stdout.splitlines():
        path = Path(output_line)
        if path not in candidates:
            candidates.append(path)
    return candidates


def check_files(
    filenames: list[Path],
    excluded_files: tuple[str, ...] = (),
    allowed_functions: tuple[str, ...] = (),
) -> list[CommitViolation]:
    """Check files with grep where possible and AST where exceptions require it."""
    paths = [
        path
        for path in filenames
        if path.suffix == ".py"
        and not any(_matches_path(path, item) for item in excluded_files)
    ]
    ast_paths = [path for path in paths if _needs_ast(path, allowed_functions)]
    grep_paths = [path for path in paths if path not in ast_paths]

    try:
        grep_candidates = _grep_candidates(grep_paths) if grep_paths else []
        ast_paths.extend(grep_candidates)
    except OSError:
        ast_paths = paths

    violations: list[CommitViolation] = []
    seen: set[Path] = set()
    for path in ast_paths:
        if path not in seen:
            violations.extend(scan_file(path, allowed_functions))
            seen.add(path)
    return violations


app = typer.Typer(add_completion=False, help="Ban direct database session commits.")


@app.callback(invoke_without_command=True)
def main(
    filenames: Annotated[
        Optional[list[Path]],
        typer.Argument(help="Python files supplied by pre-commit."),
    ] = None,
    exclude_file: Annotated[
        Optional[list[str]],
        typer.Option(
            "--exclude-file", help="File path to skip; repeat for multiple files."
        ),
    ] = None,
    allow_function: Annotated[
        Optional[list[str]],
        typer.Option(
            "--allow-function",
            help="Allow one function using FILE:FUNCTION; repeat for multiple functions.",
        ),
    ] = None,
) -> None:
    """Reject direct commit() calls unless explicitly excepted."""
    try:
        violations = check_files(
            filenames or [], tuple(exclude_file or ()), tuple(allow_function or ())
        )
    except ValueError as exc:
        err_console.print(str(exc))
        raise typer.Exit(EXIT_USAGE)
    for violation in violations:
        err_console.print(violation.format())
    raise typer.Exit(EXIT_ERROR if violations else EXIT_OK)


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
