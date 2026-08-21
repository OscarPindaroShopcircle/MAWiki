"""Pre-commit hook that forbids SQLAlchemy models in JinjaX component props."""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2

err_console = Console(stderr=True, soft_wrap=True)


@dataclass(frozen=True)
class TypeInfo:
    models: frozenset[str] = frozenset()
    items: tuple["TypeInfo", ...] = ()

    def select(self, index: int) -> "TypeInfo":
        return self.items[index] if index < len(self.items) else TypeInfo()


@dataclass(frozen=True)
class Assignment:
    value: ast.expr
    indexes: tuple[int, ...] = ()


@dataclass
class ModuleIndex:
    dotted: str
    path: Path
    tree: ast.Module
    imports: dict[str, tuple[str, str]] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = field(
        default_factory=dict
    )


@dataclass(frozen=True)
class ModelDefinition:
    name: str
    fields: dict[str, frozenset[str]]


@dataclass(frozen=True)
class TemplateModelViolation:
    path: Path
    line: int
    column: int
    prop: str
    models: tuple[str, ...]

    def format(self) -> str:
        names = ", ".join(self.models)
        return (
            f"{self.path}:{self.line}:{self.column}: database model {names} "
            f"passed to catalog.render as '{self.prop}'"
        )


class Analyzer:
    def __init__(self, backend_root: Path):
        self.backend_root = backend_root.resolve()
        self.source_root = self.backend_root.parent
        self.models = discover_models(self.backend_root)
        self.modules: dict[Path, ModuleIndex] = {}

    def module(self, path: Path) -> ModuleIndex:
        path = path.resolve()
        if path not in self.modules:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            dotted = ".".join(path.relative_to(self.source_root).with_suffix("").parts)
            index = ModuleIndex(dotted=dotted, path=path, tree=tree)
            self._populate_module(index)
            self.modules[path] = index
        return self.modules[path]

    def _populate_module(self, index: ModuleIndex) -> None:
        package = index.dotted.split(".")[:-1]
        for node in index.tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                index.functions[node.name] = node
            if not isinstance(node, ast.ImportFrom) or node.module is None:
                continue
            base = package[: len(package) - (node.level - 1)] if node.level else []
            module = ".".join([*base, *node.module.split(".")])
            for name in node.names:
                if name.name == "*":
                    continue
                local = name.asname or name.name
                index.imports[local] = (module, name.name)
                if name.name in self.models:
                    index.aliases[local] = name.name

    def module_for_import(self, dotted: str) -> ModuleIndex | None:
        base = self.source_root.joinpath(*dotted.split("."))
        for path in (base.with_suffix(".py"), base / "__init__.py"):
            if path.is_file():
                return self.module(path)
        return None

    def annotation(self, node: ast.expr | None, module: ModuleIndex) -> TypeInfo:
        if node is None:
            return TypeInfo()
        if isinstance(node, ast.Name):
            name = module.aliases.get(node.id, node.id)
            return TypeInfo(frozenset({name})) if name in self.models else TypeInfo()
        if isinstance(node, ast.Attribute):
            return TypeInfo()
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            left = self.annotation(node.left, module)
            right = self.annotation(node.right, module)
            return TypeInfo(left.models | right.models, left.items + right.items)
        if not isinstance(node, ast.Subscript):
            return TypeInfo()
        values = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
        parts = tuple(self.annotation(value, module) for value in values)
        return TypeInfo(frozenset().union(*(part.models for part in parts)), parts)

    def call(self, node: ast.Call, module: ModuleIndex, scope: "Scope") -> TypeInfo:
        if isinstance(node.func, ast.Attribute):
            if node.func.attr == "model_validate":
                return TypeInfo()
            return TypeInfo()
        if not isinstance(node.func, ast.Name):
            return TypeInfo()
        name = module.aliases.get(node.func.id, node.func.id)
        if name in self.models:
            return TypeInfo(frozenset({name}))
        imported = module.imports.get(node.func.id)
        if imported is None:
            return TypeInfo()
        target_module = self.module_for_import(imported[0])
        if target_module is None:
            return TypeInfo()
        target = target_module.functions.get(imported[1])
        return self.annotation(target.returns, target_module) if target else TypeInfo()

    def expression(
        self, node: ast.expr, module: ModuleIndex, scope: "Scope"
    ) -> TypeInfo:
        while isinstance(node, ast.Await):
            node = node.value
        if isinstance(node, ast.Name):
            assignment = scope.assignments.get(node.id)
            if assignment is not None:
                value = self.expression(assignment.value, module, scope)
                for index in assignment.indexes:
                    value = value.select(index)
                return value
            return self.annotation(scope.parameters.get(node.id), module)
        if isinstance(node, ast.Call):
            return self.call(node, module, scope)
        if isinstance(node, ast.Attribute):
            base = self.expression(node.value, module, scope)
            field_models: set[str] = set()
            for model in base.models:
                field_models.update(self.models[model].fields.get(node.attr, ()))
            return TypeInfo(frozenset(field_models))
        if isinstance(node, ast.Subscript):
            return self.expression(node.value, module, scope)
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            parts = tuple(self.expression(value, module, scope) for value in node.elts)
            return TypeInfo(frozenset().union(*(part.models for part in parts)), parts)
        return TypeInfo()

    def scan_file(self, path: Path) -> list[TemplateModelViolation]:
        module = self.module(path)
        violations: list[TemplateModelViolation] = []
        for function in module.functions.values():
            scope = Scope.build(function)
            for node in ast.walk(function):
                if not isinstance(node, ast.Call) or not _is_catalog_render(node):
                    continue
                for keyword in node.keywords:
                    if keyword.arg is None:
                        continue
                    models = self.expression(keyword.value, module, scope).models
                    if models:
                        violations.append(
                            TemplateModelViolation(
                                path,
                                keyword.value.lineno,
                                keyword.value.col_offset + 1,
                                keyword.arg,
                                tuple(sorted(models)),
                            )
                        )
        return violations


@dataclass
class Scope:
    parameters: dict[str, ast.expr | None]
    assignments: dict[str, Assignment]

    @classmethod
    def build(cls, function: ast.FunctionDef | ast.AsyncFunctionDef) -> "Scope":
        parameters = {
            parameter.arg: parameter.annotation
            for parameter in [
                *function.args.posonlyargs,
                *function.args.args,
                *function.args.kwonlyargs,
            ]
        }
        assignments: dict[str, Assignment] = {}
        for node in ast.walk(function):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    _record_assignment(assignments, target, node.value)
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                _record_assignment(assignments, node.target, node.value)
        return cls(parameters, assignments)


def _record_assignment(
    assignments: dict[str, Assignment],
    target: ast.expr,
    value: ast.expr,
    indexes: tuple[int, ...] = (),
) -> None:
    if isinstance(target, ast.Name):
        assignments[target.id] = Assignment(value, indexes)
    elif isinstance(target, (ast.Tuple, ast.List)):
        for index, item in enumerate(target.elts):
            _record_assignment(assignments, item, value, (*indexes, index))


def _is_base(node: ast.expr) -> bool:
    return (isinstance(node, ast.Name) and node.id == "Base") or (
        isinstance(node, ast.Attribute) and node.attr == "Base"
    )


def _annotation_models(node: ast.expr | None, model_names: set[str]) -> frozenset[str]:
    if node is None:
        return frozenset()
    return frozenset(
        child.id
        for child in ast.walk(node)
        if isinstance(child, ast.Name) and child.id in model_names
    )


def discover_models(backend_root: Path) -> dict[str, ModelDefinition]:
    classes: list[ast.ClassDef] = []
    for path in backend_root.rglob("models.py"):
        if "db" in path.relative_to(backend_root).parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        classes.extend(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef)
            and any(_is_base(base) for base in node.bases)
        )
    names = {item.name for item in classes}
    return {
        item.name: ModelDefinition(
            item.name,
            {
                field.target.id: _annotation_models(field.annotation, names)
                for field in item.body
                if isinstance(field, ast.AnnAssign)
                and isinstance(field.target, ast.Name)
            },
        )
        for item in classes
    }


def _is_catalog_render(node: ast.Call) -> bool:
    return (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "render"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "catalog"
    )


def run_check(backend_root: Path) -> list[TemplateModelViolation]:
    if not backend_root.is_dir():
        raise ValueError(f"{backend_root}: backend root not found")
    analyzer = Analyzer(backend_root)
    violations: list[TemplateModelViolation] = []
    for path in sorted(backend_root.rglob("views.py")):
        violations.extend(analyzer.scan_file(path))
    return sorted(violations, key=lambda item: (item.path, item.line, item.column))


app = typer.Typer(
    add_completion=False,
    help="Forbid database models from being passed to JinjaX catalog.render.",
)


@app.callback(invoke_without_command=True)
def main(
    filenames: Annotated[
        Optional[list[Path]],
        typer.Argument(help="Staged files from pre-commit; the check scans all views."),
    ] = None,
    backend_root: Annotated[
        Path,
        typer.Option("--backend-root", help="Root of the backend package to scan."),
    ] = Path("src/backend"),
) -> None:
    del filenames
    try:
        violations = run_check(backend_root)
    except (OSError, SyntaxError, ValueError) as exc:
        err_console.print(str(exc))
        raise typer.Exit(EXIT_USAGE) from exc
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
