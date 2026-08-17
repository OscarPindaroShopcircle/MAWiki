"""Turning a context expression into a concrete Pydantic type.

The resolution chain, tried in order for each ``context={"key": <expr>}`` value:

* ``Model(...)``                  -> that class
* ``Model.model_validate(x)``     -> that class
* ``helper(...)`` with a return annotation      -> the annotation
* ``helper(...)`` without one     -> the models its ``return`` statements build
* a local variable               -> its assignment, ``await`` stripped, then re-resolved
* a function parameter           -> its annotation
* a string literal or f-string   -> ``str``

Two refinements beyond the plain chain, both needed by real routes:

**Unparametrized generics.** ``_projects_grid_view`` returns
``PaginatedResponse(data=[_to_card(p) for p in projects], ...)`` with no generic
argument, so the class alone says ``data: List[~T]`` — an unbound TypeVar, which
would make ``view.data`` unknown and silently stop checking every template
reached through it. The argument is recovered from the constructor keywords: the
comprehension element ``_to_card(p)`` resolves to ``ProjectCardView``, giving
``PaginatedResponse[ProjectCardView]``.

**Branch correlation.** A dispatcher like ``_build_tab`` returns a different model
per ``if tab == "...":`` branch, and the template name is ``_TAB_PARTIALS[tab]``.
Both are keyed on the same literal, so each template is matched to the model from
the branch with the same key.

Annotations are read off *imported* objects via ``typing.get_type_hints`` rather
than parsed from source, so forward references and generic subscripts resolve for
free.
"""

from __future__ import annotations

import ast
import importlib
import typing
from dataclasses import dataclass, field

from .discovery import ModuleIndex, RouteBinding
from .typerefs import (
    UNKNOWN,
    ModelRef,
    OpaqueRef,
    TypeRef,
    UnknownRef,
    is_pydantic_model,
    normalize,
    unparametrized_typevars,
)


class ResolutionError(RuntimeError):
    """A module named by a view could not be imported — a setup failure."""


@dataclass
class _Scope:
    """A function body: its module, its parameters, and its local assignments."""

    module: ModuleIndex
    func: ast.FunctionDef | ast.AsyncFunctionDef
    assigns: dict[str, ast.expr] = field(default_factory=dict)

    @classmethod
    def build(
        cls, module: ModuleIndex, func: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> "_Scope":
        assigns: dict[str, ast.expr] = {}
        for node in ast.walk(func):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        assigns[target.id] = node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.value is not None:
                    assigns[node.target.id] = node.value
        return cls(module=module, func=func, assigns=assigns)


def _strip_await(node: ast.expr) -> ast.expr:
    while isinstance(node, ast.Await):
        node = node.value
    return node


def _text(node: ast.expr) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return "<expr>"


class Resolver:
    def __init__(self) -> None:
        self._modules: dict[str, object] = {}
        self.warnings: list[str] = []

    # -- module / name access ------------------------------------------------

    def _module_obj(self, module: ModuleIndex):
        if module.dotted not in self._modules:
            try:
                self._modules[module.dotted] = importlib.import_module(module.dotted)
            except Exception as exc:  # ImportError and anything raised at import time
                raise ResolutionError(f"cannot import {module.dotted}: {exc}") from exc
        return self._modules[module.dotted]

    def lookup(self, module: ModuleIndex, dotted: str) -> object | None:
        """Resolve a (possibly dotted) name against the module's namespace."""
        obj: object | None = self._module_obj(module)
        for part in dotted.split("."):
            if obj is None:
                return None
            obj = getattr(obj, part, None)
        return obj

    def _hints(self, obj: object) -> dict[str, object]:
        try:
            return typing.get_type_hints(obj)
        except Exception:
            return {}

    # -- generic inference (Gap B) -----------------------------------------

    def _typevar_slot(self, annotation: object, tv: typing.TypeVar) -> str | None:
        """Where ``tv`` sits in a field annotation: directly, or as a sequence element."""
        if annotation is tv:
            return "direct"
        for arg in typing.get_args(annotation):
            if arg is tv:
                return "seq"
        return None

    def _element_expr(self, node: ast.expr) -> ast.expr | None:
        node = _strip_await(node)
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
            return node.elt
        if isinstance(node, (ast.List, ast.Set, ast.Tuple)) and node.elts:
            return node.elts[0]
        if isinstance(node, ast.Call):
            # e.g. list(...) / sorted(...) around a comprehension
            for arg in node.args:
                inner = self._element_expr(arg)
                if inner is not None:
                    return inner
        return None

    def _parametrize(
        self, cls: type, call: ast.Call, scope: _Scope
    ) -> tuple[TypeRef, str | None]:
        """Fill a generic model's free TypeVars from the constructor keywords."""
        free = unparametrized_typevars(cls)
        if not free:
            return ModelRef(cls), None

        kwargs = {kw.arg: kw.value for kw in call.keywords if kw.arg}
        substitutions: list[object] = []
        for tv in free:
            found: object | None = None
            for field_name, info in cls.model_fields.items():
                slot = self._typevar_slot(info.annotation, tv)
                if slot is None or field_name not in kwargs:
                    continue
                value = kwargs[field_name]
                target = value if slot == "direct" else self._element_expr(value)
                if target is None:
                    continue
                ref = self.resolve(target, scope)
                if isinstance(ref, ModelRef):
                    found = ref.cls
                    break
                if isinstance(ref, OpaqueRef) and ref.py_type is not None:
                    found = ref.py_type
                    break
            if found is None:
                return (
                    ModelRef(cls),
                    f"{cls.__name__} is generic but its type argument could not be "
                    f"inferred; attributes below `.{free[0].__name__}` go unchecked",
                )
            substitutions.append(found)

        try:
            parametrized = cls[tuple(substitutions)]  # type: ignore[index]
        except Exception:
            return ModelRef(cls), f"could not parametrize {cls.__name__}"
        return normalize(parametrized), None

    # -- the main expression resolver --------------------------------------

    def resolve(self, node: ast.expr, scope: _Scope, depth: int = 0) -> TypeRef:
        ref, _ = self.resolve_detailed(node, scope, depth)
        return ref

    def resolve_detailed(
        self, node: ast.expr, scope: _Scope, depth: int = 0
    ) -> tuple[TypeRef, str | None]:
        """Resolve an expression; the second element is a warning, if any."""
        if depth > 6:
            return UNKNOWN, "resolution too deep"
        node = _strip_await(node)

        if isinstance(node, (ast.Constant, ast.JoinedStr)):
            if isinstance(node, ast.JoinedStr) or isinstance(node.value, str):
                return OpaqueRef(str), None
            return OpaqueRef(type(node.value)), None

        if isinstance(node, ast.Call):
            return self._resolve_call(node, scope, depth)

        if isinstance(node, ast.Name):
            if node.id in scope.assigns:
                return self.resolve_detailed(scope.assigns[node.id], scope, depth + 1)
            hints = self._hints(self.lookup(scope.module, scope.func.name) or object)
            if node.id in hints:
                return normalize(hints[node.id]), None
            return UNKNOWN, f"`{node.id}` is not a local assignment or a parameter"

        if isinstance(node, ast.IfExp):
            for branch in (node.body, node.orelse):
                ref, _ = self.resolve_detailed(branch, scope, depth + 1)
                if not isinstance(ref, UnknownRef):
                    return ref, None
            return UNKNOWN, None

        if isinstance(node, ast.Attribute):
            return UNKNOWN, (
                f"`{_text(node)}` is an attribute access; only Pydantic models, "
                "helper calls, parameters and literals are resolved"
            )

        return UNKNOWN, f"`{_text(node)}` has no resolvable type"

    def _resolve_call(
        self, node: ast.Call, scope: _Scope, depth: int
    ) -> tuple[TypeRef, str | None]:
        callee = node.func

        # Model.model_validate(x) -> Model
        if isinstance(callee, ast.Attribute):
            if callee.attr == "model_validate":
                obj = self.lookup(scope.module, _text(callee.value))
                if is_pydantic_model(obj):
                    return self._parametrize(obj, node, scope)  # type: ignore[arg-type]
            return UNKNOWN, f"`{_text(node)}` is not a resolvable call"

        if not isinstance(callee, ast.Name):
            return UNKNOWN, f"`{_text(node)}` is not a resolvable call"

        name = callee.id

        # A constructor: Model(...)
        obj = self.lookup(scope.module, name)
        if is_pydantic_model(obj):
            return self._parametrize(obj, node, scope)  # type: ignore[arg-type]

        # A helper function in the same module.
        helper_ast = scope.module.functions.get(name)
        if helper_ast is None:
            return UNKNOWN, f"`{name}(...)` is not defined in {scope.module.dotted}"

        if obj is not None:
            annotated = self._hints(obj).get("return")
            if annotated is not None:
                return normalize(annotated), None

        # No return annotation: look at what the return statements build.
        branches = self.return_refs(helper_ast, scope.module, depth)
        distinct = {ref for _, ref in branches if not isinstance(ref, UnknownRef)}
        if len(distinct) == 1:
            return next(iter(distinct)), None
        if len(distinct) > 1:
            return UNKNOWN, (
                f"`{name}(...)` has no return annotation and returns "
                f"{len(distinct)} different types"
            )
        return UNKNOWN, (
            f"`{name}(...)` has no return annotation and no resolvable "
            "model construction in its return statements"
        )

    def return_refs(
        self,
        func: ast.FunctionDef | ast.AsyncFunctionDef,
        module: ModuleIndex,
        depth: int = 0,
    ) -> list[tuple[str | None, TypeRef]]:
        """Types returned by a function, tagged with any ``x == "literal"`` guard."""
        inner = _Scope.build(module, func)
        results: list[tuple[str | None, TypeRef]] = []

        def guard_key(test: ast.expr) -> str | None:
            if (
                isinstance(test, ast.Compare)
                and len(test.ops) == 1
                and isinstance(test.ops[0], ast.Eq)
                and isinstance(test.comparators[0], ast.Constant)
                and isinstance(test.comparators[0].value, str)
            ):
                return test.comparators[0].value
            return None

        def visit(body: list[ast.stmt], key: str | None) -> None:
            for stmt in body:
                if isinstance(stmt, ast.Return) and stmt.value is not None:
                    ref, _ = self.resolve_detailed(stmt.value, inner, depth + 1)
                    results.append((key, ref))
                elif isinstance(stmt, ast.If):
                    visit(stmt.body, guard_key(stmt.test) or key)
                    visit(stmt.orelse, key)
                elif isinstance(stmt, (ast.Try, ast.With, ast.AsyncWith)):
                    visit(stmt.body, key)
                elif isinstance(stmt, (ast.For, ast.AsyncFor, ast.While)):
                    visit(stmt.body, key)

        visit(func.body, None)
        return results

    # -- entry point --------------------------------------------------------

    def resolve_binding(
        self, binding: RouteBinding, dict_key: str | None
    ) -> tuple[dict[str, TypeRef], list[str]]:
        """Context types for one (call site, template) pair, plus warnings."""
        scope = _Scope.build(binding.module, binding.func)
        route_hints = self._hints(
            self.lookup(binding.module, binding.func.name) or object
        )
        context: dict[str, TypeRef] = {}
        warnings: list[str] = []

        for key, expr in binding.context.items():
            # Parameters resolve straight from the route signature.
            if isinstance(expr, ast.Name) and expr.id not in scope.assigns:
                if expr.id in route_hints:
                    context[key] = normalize(route_hints[expr.id])
                    continue

            ref, warning = self.resolve_detailed(expr, scope)

            # A dispatcher correlated with the template name (Gap A).
            if isinstance(ref, UnknownRef) and dict_key is not None:
                correlated = self._correlate(expr, scope, dict_key)
                if correlated is not None:
                    ref, warning = correlated, None

            context[key] = ref
            if isinstance(ref, UnknownRef) and warning:
                warnings.append(
                    f"{binding.where}: context '{key}' unresolved - {warning}"
                )
            elif warning:
                warnings.append(f"{binding.where}: context '{key}' - {warning}")

        return context, warnings

    def _correlate(
        self, expr: ast.expr, scope: _Scope, dict_key: str
    ) -> TypeRef | None:
        """Pick the dispatcher branch guarded by the same literal as the template."""
        expr = _strip_await(expr)
        if isinstance(expr, ast.Name):
            expr = _strip_await(scope.assigns.get(expr.id, expr))
        if not isinstance(expr, ast.Call) or not isinstance(expr.func, ast.Name):
            return None
        helper = scope.module.functions.get(expr.func.id)
        if helper is None:
            return None
        for key, ref in self.return_refs(helper, scope.module):
            if key == dict_key and not isinstance(ref, UnknownRef):
                return ref
        return None
