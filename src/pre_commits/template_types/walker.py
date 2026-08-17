"""Walking a template's Jinja AST and checking every attribute chain.

Scopes are plain dicts copied on entry to a nested body, and bodies are walked in
source order, so ``{% set %}``-before-use falls out without extra machinery.

``{% include %}`` is inlined at the include site **with the live scope**, which is
exactly Jinja's plain-include semantics. That handles the two awkward cases in
this codebase for free: ``card`` is a ``{% for %}`` variable in
``project_grid.html`` that crosses into ``project_card.html``, and ``page_url`` is
a ``{% set %}`` in ``projects/companies.html`` satisfying a free variable in
``company_rows.html``.

Any node type not handled below raises E900 rather than being skipped. Silent
coverage loss is the worst failure mode for a checker: the day someone adds a
``{% macro %}``, this should say so instead of quietly stopping.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from jinja2 import Environment, nodes

from .diagnostics import Diagnostic, Suppressions, scan_suppressions
from .typerefs import UNKNOWN, SeqRef, TypeRef, UnknownRef, getattr_type

# Jinja globals and loop bookkeeping that are always in scope.
BUILTIN_NAMES = frozenset(
    {
        "request",
        "url_for",
        "loop",
        "self",
        "range",
        "dict",
        "lipsum",
        "cycler",
        "joiner",
        "namespace",
    }
)

# Expression nodes whose result we do not model, but whose operands we still walk.
_OPAQUE_EXPR = (
    nodes.Filter,
    nodes.Test,
    nodes.Call,
    nodes.Concat,
    nodes.Add,
    nodes.Sub,
    nodes.Mul,
    nodes.Div,
    nodes.FloorDiv,
    nodes.Mod,
    nodes.Pow,
    nodes.And,
    nodes.Or,
    nodes.Not,
    nodes.Neg,
    nodes.Pos,
    nodes.Compare,
    nodes.Operand,
    nodes.List,
    nodes.Dict,
    nodes.Tuple,
    nodes.Pair,
    nodes.Keyword,
    nodes.Slice,
    nodes.MarkSafe,
    nodes.MarkSafeIfAutoescape,
)


def chain_text(node: nodes.Node) -> str:
    """Reconstruct a readable attribute chain for a diagnostic."""
    if isinstance(node, nodes.Name):
        return node.name
    if isinstance(node, nodes.Getattr):
        return f"{chain_text(node.node)}.{node.attr}"
    if isinstance(node, nodes.Getitem):
        inner = node.arg
        key = repr(inner.value) if isinstance(inner, nodes.Const) else "..."
        return f"{chain_text(node.node)}[{key}]"
    if isinstance(node, nodes.Const):
        return repr(node.value)
    return node.__class__.__name__.lower()


@dataclass
class _Frame:
    """One template being walked, and how we got there."""

    name: str
    suppressions: Suppressions
    included_from: tuple[str, int] | None = None
    # Names the template itself declares optional, via `x | default(...)` or
    # `x is defined`. Such a name is legitimately absent from the context, so a
    # bare reference to it elsewhere in the same file is not an unbound name.
    optional: frozenset[str] = frozenset()


# Filters and tests through which a template says "this name may be missing".
_DEFAULT_FILTERS = frozenset({"default", "d"})
_DEFINEDNESS_TESTS = frozenset({"defined", "undefined"})


def optional_names(tree: nodes.Template) -> frozenset[str]:
    """Names guarded by ``| default(...)`` or ``is defined`` anywhere in a template."""
    found: set[str] = set()
    for filter_ in tree.find_all(nodes.Filter):
        if filter_.name in _DEFAULT_FILTERS and isinstance(filter_.node, nodes.Name):
            found.add(filter_.node.name)
    for test in tree.find_all(nodes.Test):
        if test.name in _DEFINEDNESS_TESTS and isinstance(test.node, nodes.Name):
            found.add(test.node.name)
    return frozenset(found)


@dataclass
class CheckResult:
    diagnostics: list[Diagnostic] = field(default_factory=list)
    visited: set[str] = field(default_factory=set)


class TemplateChecker:
    def __init__(self, env: Environment, binding_label: str = "") -> None:
        self.env = env
        self.binding_label = binding_label
        self._ast_cache: dict[str, nodes.Template] = {}
        self._source_cache: dict[str, str] = {}

    # -- source access -------------------------------------------------------

    def source(self, name: str) -> str:
        if name not in self._source_cache:
            self._source_cache[name] = self.env.loader.get_source(self.env, name)[0]
        return self._source_cache[name]

    def parse(self, name: str) -> nodes.Template:
        if name not in self._ast_cache:
            self._ast_cache[name] = self.env.parse(self.source(name), name=name)
        return self._ast_cache[name]

    # -- entry point ---------------------------------------------------------

    def check(self, template: str, context: dict[str, TypeRef]) -> CheckResult:
        self.result = CheckResult()
        scope: dict[str, TypeRef] = dict(context)
        self._visit_template(template, scope, included_from=None, path=())
        return self.result

    # -- reporting -----------------------------------------------------------

    def _report(
        self,
        frame: _Frame,
        code: str,
        lineno: int,
        message: str,
        detail: str = "",
    ) -> None:
        if not frame.suppressions.allows(code, lineno):
            return
        parts = [detail] if detail else []
        if self.binding_label:
            parts.append(f"binding {self.binding_label}")
        self.result.diagnostics.append(
            Diagnostic(
                code=code,
                template=frame.name,
                lineno=lineno,
                message=message,
                detail="  ".join(parts),
                included_from=frame.included_from,
            )
        )

    # -- template / body traversal ------------------------------------------

    def _visit_template(
        self,
        name: str,
        scope: dict[str, TypeRef],
        included_from: tuple[str, int] | None,
        path: tuple[str, ...],
    ) -> None:
        if name in path:
            frame = _Frame(name, Suppressions(), included_from)
            self._report(
                frame, "E901", 1, f"include cycle: {' -> '.join((*path, name))}"
            )
            return

        try:
            tree = self.parse(name)
            source = self.source(name)
        except Exception as exc:
            frame = _Frame(name, Suppressions(), included_from)
            self._report(frame, "E900", 1, f"could not parse template: {exc}")
            return

        frame = _Frame(
            name, scan_suppressions(source), included_from, optional_names(tree)
        )
        self.result.visited.add(name)
        # A file-level ignore does not skip the walk: E900/E901 are unsuppressible,
        # and includes below still need visiting for coverage accounting.
        self._walk_body(tree.body, scope, frame, path + (name,))

    def _walk_body(
        self,
        body: list[nodes.Node],
        scope: dict[str, TypeRef],
        frame: _Frame,
        path: tuple[str, ...],
    ) -> None:
        for node in body:
            self._walk_stmt(node, scope, frame, path)

    def _walk_stmt(
        self,
        node: nodes.Node,
        scope: dict[str, TypeRef],
        frame: _Frame,
        path: tuple[str, ...],
    ) -> None:
        if isinstance(node, nodes.Output):
            for child in node.nodes:
                if isinstance(child, nodes.TemplateData):
                    continue
                self._eval(child, scope, frame, path)
            return

        if isinstance(node, nodes.If):
            self._eval(node.test, scope, frame, path)
            self._walk_body(node.body, dict(scope), frame, path)
            for elif_ in node.elif_:
                self._walk_stmt(elif_, dict(scope), frame, path)
            self._walk_body(node.else_, dict(scope), frame, path)
            return

        if isinstance(node, nodes.For):
            iter_ref = self._eval(node.iter, scope, frame, path)
            inner = dict(scope)
            element = iter_ref.elem if isinstance(iter_ref, SeqRef) else UNKNOWN
            if isinstance(node.target, nodes.Name):
                inner[node.target.name] = element
            elif isinstance(node.target, nodes.Tuple):
                for item in node.target.items:
                    if isinstance(item, nodes.Name):
                        inner[item.name] = UNKNOWN
            if node.test is not None:
                self._eval(node.test, inner, frame, path)
            self._walk_body(node.body, inner, frame, path)
            self._walk_body(node.else_, dict(scope), frame, path)
            return

        if isinstance(node, nodes.Assign):
            value = self._eval(node.node, scope, frame, path)
            if isinstance(node.target, nodes.Name):
                scope[node.target.name] = value
            elif isinstance(node.target, nodes.Tuple):
                for item in node.target.items:
                    if isinstance(item, nodes.Name):
                        scope[item.name] = UNKNOWN
            return

        if isinstance(node, nodes.AssignBlock):
            # The captured body is checked in the current scope; the result is text.
            self._walk_body(node.body, dict(scope), frame, path)
            if isinstance(node.target, nodes.Name):
                scope[node.target.name] = UNKNOWN
            return

        if isinstance(node, nodes.With):
            # `{% with %}` extends the enclosing scope rather than replacing it, and
            # each value is evaluated before its own target is bound - so
            # `{% with view = view.companies %}` reads the *outer* `view`.
            inner = dict(scope)
            for target, value in zip(node.targets, node.values, strict=False):
                resolved = self._eval(value, inner, frame, path)
                if isinstance(target, nodes.Name):
                    inner[target.name] = resolved
                elif isinstance(target, nodes.Tuple):
                    for item in target.items:
                        if isinstance(item, nodes.Name):
                            inner[item.name] = UNKNOWN
            self._walk_body(node.body, inner, frame, path)
            return

        if isinstance(node, nodes.Block):
            self._walk_body(node.body, dict(scope), frame, path)
            return

        if isinstance(node, nodes.Extends):
            if isinstance(node.template, nodes.Const):
                self._visit_template(
                    node.template.value, dict(scope), frame.included_from, path
                )
            return

        if isinstance(node, nodes.Include):
            self._walk_include(node, scope, frame, path)
            return

        if isinstance(node, nodes.Scope):
            self._walk_body(node.body, dict(scope), frame, path)
            return

        if isinstance(node, nodes.ExprStmt):
            self._eval(node.node, scope, frame, path)
            return

        self._report(
            frame,
            "E900",
            getattr(node, "lineno", 1) or 1,
            f"unsupported Jinja construct {node.__class__.__name__}",
            detail="this checker does not model it; attributes inside go unchecked",
        )

    def _walk_include(
        self,
        node: nodes.Include,
        scope: dict[str, TypeRef],
        frame: _Frame,
        path: tuple[str, ...],
    ) -> None:
        targets: list[str] = []
        if isinstance(node.template, nodes.Const):
            value = node.template.value
            targets = [value] if isinstance(value, str) else list(value)
        elif isinstance(node.template, nodes.List):
            targets = [
                item.value
                for item in node.template.items
                if isinstance(item, nodes.Const)
            ]
        if not targets:
            self._report(
                frame,
                "E900",
                node.lineno,
                "include with a computed template name is not analysed",
            )
            return

        # `without context` means the partial starts empty; a plain include shares
        # the caller's scope, which is what makes loop vars and {% set %} flow in.
        inherited = dict(scope) if node.with_context else {}
        for target in targets:
            self._visit_template(
                target, dict(inherited), (frame.name, node.lineno), path
            )

    # -- expression evaluation ----------------------------------------------

    def _eval(
        self,
        node: nodes.Node,
        scope: dict[str, TypeRef],
        frame: _Frame,
        path: tuple[str, ...],
    ) -> TypeRef:
        if isinstance(node, nodes.Name):
            if node.name in scope:
                return scope[node.name]
            if node.name in BUILTIN_NAMES or node.name in self.env.globals:
                return UNKNOWN
            if node.name in frame.optional:
                return UNKNOWN
            self._report(
                frame,
                "E110",
                node.lineno,
                f"name '{node.name}' is not provided by this template's context",
                detail=(
                    "in scope here: "
                    + (", ".join(sorted(scope)) if scope else "(nothing)")
                ),
            )
            return UNKNOWN

        if isinstance(node, nodes.Getattr):
            base = self._eval(node.node, scope, frame, path)
            outcome = getattr_type(base, node.attr)
            if outcome.code is not None:
                detail = f"in `{chain_text(node)}`"
                if outcome.hint:
                    detail = f"{detail} - {outcome.hint}"
                self._report(
                    frame, outcome.code, node.lineno, outcome.message, detail=detail
                )
            return outcome.ref

        if isinstance(node, nodes.Getitem):
            base = self._eval(node.node, scope, frame, path)
            if not isinstance(node.arg, nodes.Const):
                self._eval(node.arg, scope, frame, path)
                return UNKNOWN
            if isinstance(base, SeqRef) and isinstance(node.arg.value, int):
                return base.elem
            return UNKNOWN

        if isinstance(node, nodes.CondExpr):
            self._eval(node.test, scope, frame, path)
            first = self._eval(node.expr1, scope, frame, path)
            second = (
                self._eval(node.expr2, scope, frame, path)
                if node.expr2 is not None
                else UNKNOWN
            )
            return first if not isinstance(first, UnknownRef) else second

        if isinstance(node, (nodes.Const, nodes.TemplateData)):
            return UNKNOWN

        if isinstance(node, _OPAQUE_EXPR):
            for child in node.iter_child_nodes():
                self._eval(child, scope, frame, path)
            return UNKNOWN

        self._report(
            frame,
            "E900",
            getattr(node, "lineno", 1) or 1,
            f"unsupported Jinja expression {node.__class__.__name__}",
        )
        return UNKNOWN
