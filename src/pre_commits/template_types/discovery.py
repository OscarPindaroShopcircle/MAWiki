"""Finding which template each route renders, and with what context.

Pure ``ast`` work — nothing is imported here. The walk mirrors how the app is
actually wired:

1. module-level ``<name> = APIRouter(...)`` assignments give the router names
2. functions decorated with ``@<router>.<method>(...)`` are the routes
3. of those, only ones taking a ``Jinja2Templates`` parameter render anything
4. inside them, ``<that parameter>.TemplateResponse(name=..., context={...})``
   yields the template path (relative to the templates root) and the context

``name=`` is usually a literal. When it is a subscript of a module-level dict of
literals (``name=_TAB_PARTIALS[tab]``) every value is a candidate, and the
subscript variable is recorded so the resolver can try to correlate each template
with the matching branch of the view helper.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ModuleIndex:
    """Everything the resolver needs about one ``views.py``."""

    dotted: str
    path: Path
    tree: ast.Module
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = field(
        default_factory=dict
    )
    dict_constants: dict[str, dict[str, str]] = field(default_factory=dict)


@dataclass
class RouteBinding:
    """One ``TemplateResponse`` call site."""

    module: ModuleIndex
    func: ast.FunctionDef | ast.AsyncFunctionDef
    lineno: int
    templates: tuple[str, ...]
    context: dict[str, ast.expr]
    # Gap A: when `templates` came from a dict subscript, the dict keys parallel
    # to `templates`, plus the variable indexing it.
    dict_keys: tuple[str, ...] | None = None
    correlation_var: str | None = None

    @property
    def where(self) -> str:
        return f"{self.module.path}:{self.lineno}"


def _dotted_name(path: Path, source_root: Path) -> str:
    rel = path.resolve().relative_to(source_root.resolve()).with_suffix("")
    return ".".join(rel.parts)


def _annotation_text(node: ast.expr | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def _string_dict(node: ast.expr) -> dict[str, str] | None:
    """A dict literal whose keys and values are all plain strings."""
    if not isinstance(node, ast.Dict):
        return None
    out: dict[str, str] = {}
    for key, value in zip(node.keys, node.values):
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            return None
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            return None
        out[key.value] = value.value
    return out


def index_module(path: Path, source_root: Path) -> ModuleIndex:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    index = ModuleIndex(dotted=_dotted_name(path, source_root), path=path, tree=tree)
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            index.functions[stmt.name] = stmt
        elif isinstance(stmt, ast.Assign):
            literal = _string_dict(stmt.value)
            if literal is None:
                continue
            for target in stmt.targets:
                if isinstance(target, ast.Name):
                    index.dict_constants[target.id] = literal
    return index


def _router_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for stmt in tree.body:
        if not isinstance(stmt, ast.Assign) or not isinstance(stmt.value, ast.Call):
            continue
        func = stmt.value.func
        called = getattr(func, "id", None) or getattr(func, "attr", None)
        if called != "APIRouter":
            continue
        for target in stmt.targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
    return names


def _is_route(func: ast.FunctionDef | ast.AsyncFunctionDef, routers: set[str]) -> bool:
    for dec in func.decorator_list:
        call = dec.func if isinstance(dec, ast.Call) else dec
        if (
            isinstance(call, ast.Attribute)
            and getattr(call.value, "id", None) in routers
        ):
            return True
    return False


def _template_param_names(func: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    args = func.args
    everything = list(args.args) + list(args.kwonlyargs) + list(args.posonlyargs)
    return {
        arg.arg
        for arg in everything
        if "Jinja2Templates" in _annotation_text(arg.annotation)
    }


def _resolve_template_names(
    node: ast.expr, module: ModuleIndex
) -> tuple[tuple[str, ...], tuple[str, ...] | None, str | None]:
    """(template names, parallel dict keys, correlation variable)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return (node.value,), None, None

    if isinstance(node, ast.Subscript):
        container = getattr(node.value, "id", None)
        mapping = module.dict_constants.get(container or "")
        if mapping:
            index = node.slice
            var = index.id if isinstance(index, ast.Name) else None
            if isinstance(index, ast.Constant) and isinstance(index.value, str):
                value = mapping.get(index.value)
                return ((value,) if value else ()), (index.value,), None
            keys = tuple(mapping)
            return tuple(mapping[k] for k in keys), keys, var

    return (), None, None


def find_bindings(
    view_paths: list[Path], source_root: Path
) -> tuple[list[RouteBinding], list[str]]:
    """Discover every ``TemplateResponse`` call site. Returns (bindings, notes)."""
    bindings: list[RouteBinding] = []
    notes: list[str] = []

    for path in sorted(view_paths):
        try:
            module = index_module(path, source_root)
        except (SyntaxError, UnicodeDecodeError) as exc:
            notes.append(f"{path}: could not parse ({exc})")
            continue

        routers = _router_names(module.tree)
        if not routers:
            continue

        for func in module.functions.values():
            if not _is_route(func, routers):
                continue
            template_vars = _template_param_names(func)
            if not template_vars:
                continue

            for node in ast.walk(func):
                if not isinstance(node, ast.Call):
                    continue
                callee = node.func
                if not isinstance(callee, ast.Attribute):
                    continue
                if callee.attr != "TemplateResponse":
                    continue
                if getattr(callee.value, "id", None) not in template_vars:
                    continue

                kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
                name_node = kwargs.get("name")
                if name_node is None:
                    notes.append(
                        f"{path}:{node.lineno}: TemplateResponse without a "
                        "keyword `name=`, skipped"
                    )
                    continue

                names, dict_keys, correlation = _resolve_template_names(
                    name_node, module
                )
                if not names:
                    notes.append(
                        f"{path}:{node.lineno}: could not resolve template name "
                        f"`{_annotation_text(name_node)}`, skipped"
                    )
                    continue

                context: dict[str, ast.expr] = {}
                ctx_node = kwargs.get("context")
                if isinstance(ctx_node, ast.Dict):
                    for key, value in zip(ctx_node.keys, ctx_node.values):
                        if isinstance(key, ast.Constant) and isinstance(key.value, str):
                            context[key.value] = value
                        else:
                            notes.append(
                                f"{path}:{node.lineno}: non-literal context key, skipped"
                            )
                elif ctx_node is not None:
                    notes.append(
                        f"{path}:{node.lineno}: context is not a dict literal "
                        f"(`{_annotation_text(ctx_node)}`), treated as empty"
                    )

                bindings.append(
                    RouteBinding(
                        module=module,
                        func=func,
                        lineno=node.lineno,
                        templates=names,
                        context=context,
                        dict_keys=dict_keys,
                        correlation_var=correlation,
                    )
                )

    return bindings, notes
