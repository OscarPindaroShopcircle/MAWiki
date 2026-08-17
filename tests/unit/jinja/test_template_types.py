"""Tests for the Jinja-vs-Pydantic attribute checker.

Three layers:

* the walker, driven with an explicit context over fixture templates — this is
  where every diagnostic code is pinned, including the *negative* cases that
  record deliberate non-goals
* discovery and resolution over a fixture ``views.py`` covering each rule of the
  resolution chain, notably the unparametrized-generic inference
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader

from pre_commits.template_types.discovery import find_bindings
from pre_commits.template_types.resolver import Resolver
from pre_commits.template_types.testdata.models import Branch, Leaf
from pre_commits.template_types.typerefs import ModelRef, SeqRef, normalize
from pre_commits.template_types.walker import TemplateChecker

REPO_ROOT = Path(__file__).parents[3]
TESTDATA = REPO_ROOT / "src" / "pre_commits" / "template_types" / "testdata"
ERRORS = TESTDATA / "errors"
FIXTURE_TEMPLATES = TESTDATA / "templates"
FIXTURE_VIEWS = "src/pre_commits/template_types/testdata/views.py"


def _check(directory: Path, template: str, context: dict) -> list:
    env = Environment(loader=FileSystemLoader(directory))
    return TemplateChecker(env).check(template, context).diagnostics


def _branch_context() -> dict:
    return {"view": ModelRef(Branch)}


# --------------------------------------------------------------------------
# walker: each diagnostic code
# --------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    ("template", "code", "lineno", "needle"),
    [
        ("bad_attr.html", "E101", 1, "no attribute 'nmae'"),
        ("bad_nested.html", "E101", 1, "no attribute 'lef'"),
        ("bad_list.html", "E102", 1, "not an attribute of a list"),
        ("bad_opaque.html", "E103", 1, "datetime has no attribute 'strfime'"),
        ("bad_name.html", "E110", 1, "'mystery' is not provided"),
        ("bad_alias.html", "E101", 1, "no attribute 'createdAt'"),
        ("bad_loop_elem.html", "E101", 1, "no attribute 'nmae'"),
        ("bad_set_alias.html", "E101", 2, "no attribute 'nmae'"),
        ("bad_property.html", "E101", 1, "no attribute 'nmae'"),
        ("bad_assign_block.html", "E101", 1, "no attribute 'nmae'"),
        ("unsupported_macro.html", "E900", 1, "unsupported Jinja construct Macro"),
        ("bad_with.html", "E101", 2, "no attribute 'nmae'"),
    ],
)
def test_diagnostic_is_reported(template, code, lineno, needle):
    found = _check(ERRORS, template, _branch_context())
    assert [(d.code, d.lineno) for d in found] == [(code, lineno)], found
    assert needle in found[0].message


@pytest.mark.unit
@pytest.mark.parametrize(
    "template",
    [
        "ok_property.html",
        "ok_enum.html",
        "leaf_row.html",
        "ok_with_shadow.html",
        "ok_optional_name.html",
    ],
)
def test_clean_fixtures_report_nothing(template):
    context = _branch_context() | {"leaf": ModelRef(Leaf)}
    assert _check(ERRORS, template, context) == []


@pytest.mark.unit
def test_optional_deref_is_not_reported():
    """Pins a deliberate non-goal: None-safety is out of scope.

    ``maybe_leaf`` is ``Leaf | None``, so this deref could fail at runtime. The
    checker stays silent by design — stripping Optional is what makes
    ``{% set alias = view.maybe_leaf %}`` usable. If this test ever starts
    failing, None-checking was added and the docs need updating.
    """
    assert _check(ERRORS, "ok_optional.html", _branch_context()) == []


@pytest.mark.unit
def test_alias_misuse_suggests_the_snake_case_field():
    found = _check(ERRORS, "bad_alias.html", _branch_context())
    assert "created_at" in found[0].detail


@pytest.mark.unit
def test_typo_suggests_the_closest_field():
    found = _check(ERRORS, "bad_attr.html", _branch_context())
    assert "did you mean 'name'?" in found[0].detail


# --------------------------------------------------------------------------
# walker: includes, cycles, suppression
# --------------------------------------------------------------------------


@pytest.mark.unit
def test_include_cycle_is_reported_not_hung():
    found = _check(ERRORS, "cycle_a.html", _branch_context())
    assert [d.code for d in found] == ["E901"]


@pytest.mark.unit
def test_include_without_context_does_not_inherit_scope():
    """`without context` starts the partial empty, so its free name is unbound."""
    found = _check(ERRORS, "include_no_context.html", {"leaf": ModelRef(Leaf)})
    assert [d.code for d in found] == ["E110"]
    assert found[0].template == "leaf_row.html"
    assert found[0].included_from == ("include_no_context.html", 1)


@pytest.mark.unit
def test_with_binding_flows_into_an_include():
    """The real pattern: `{% with view = view.leaf %}{% include %}{% endwith %}`."""
    found = _check(ERRORS, "with_include.html", _branch_context())
    assert [(d.code, d.template) for d in found] == [("E102", "leaf_row.html")]
    assert found[0].included_from == ("with_include.html", 8)


@pytest.mark.unit
def test_line_and_code_suppression():
    found = _check(ERRORS, "suppressed_line.html", _branch_context())
    # line 1 blanket-ignored, line 2 ignored by code, line 3's ignore is for a
    # different code so it still reports.
    assert [(d.code, d.lineno) for d in found] == [("E101", 3)]


@pytest.mark.unit
def test_file_suppression():
    assert _check(ERRORS, "suppressed_file.html", _branch_context()) == []


@pytest.mark.unit
def test_e900_cannot_be_suppressed(tmp_path):
    (tmp_path / "t.html").write_text(
        "{# type: ignore-file #}\n{% macro m() %}x{% endmacro %}\n"
    )
    found = _check(tmp_path, "t.html", {})
    assert [d.code for d in found] == ["E900"]


# --------------------------------------------------------------------------
# discovery + resolution
# --------------------------------------------------------------------------


def _bindings():
    paths = sorted(REPO_ROOT.glob(FIXTURE_VIEWS))
    bindings, notes = find_bindings(paths, REPO_ROOT / "src")
    return {
        b.templates[0] if len(b.templates) == 1 else b.templates: b for b in bindings
    }, notes


@pytest.mark.unit
def test_discovery_finds_routes_across_both_routers():
    bindings, _ = _bindings()
    rendered = set()
    for key in bindings:
        rendered.update(key if isinstance(key, tuple) else (key,))
    assert "branch.html" in rendered
    assert "second.html" in rendered, "a second APIRouter must also be discovered"


@pytest.mark.unit
def test_discovery_ignores_undecorated_and_untemplated_functions():
    bindings, _ = _bindings()
    rendered = set()
    for key in bindings:
        rendered.update(key if isinstance(key, tuple) else (key,))
    assert "never_rendered.html" not in rendered


@pytest.mark.unit
@pytest.mark.parametrize(
    ("template", "key", "expected"),
    [
        ("branch.html", "view", Branch),
        ("branch_via_return.html", "view", Branch),
        ("leaf.html", "leaf", Leaf),
    ],
)
def test_resolution_chain(template, key, expected):
    bindings, _ = _bindings()
    context, _ = Resolver().resolve_binding(bindings[template], None)
    assert context[key] == ModelRef(expected)


@pytest.mark.unit
def test_unparametrized_generic_is_inferred_from_constructor_kwargs():
    """Gap B: without this, everything below `view.data` goes unchecked.

    ``_unannotated_generic`` returns ``Page(data=[_leaf_of(r) for r in rows])``
    with no generic argument, so the class alone yields ``List[~T]``.
    """
    bindings, _ = _bindings()
    context, _ = Resolver().resolve_binding(bindings["page.html"], None)
    ref = context["view"]
    assert isinstance(ref, ModelRef)
    assert normalize(ref.cls.model_fields["data"].annotation) == SeqRef(ModelRef(Leaf))


@pytest.mark.unit
def test_generic_element_type_flows_across_an_include():
    """The full chain: generic -> loop variable -> include -> attribute check."""
    bindings, _ = _bindings()
    context, _ = Resolver().resolve_binding(bindings["page.html"], None)
    env = Environment(loader=FileSystemLoader(FIXTURE_TEMPLATES))
    assert TemplateChecker(env).check("page.html", context).diagnostics == []

    broken = FIXTURE_TEMPLATES.parent / "tmp_page_broken"
    broken.mkdir(exist_ok=True)
    try:
        shutil.copy(FIXTURE_TEMPLATES / "page.html", broken / "page.html")
        (broken / "leaf_row.html").write_text("{{ leaf.nmae }}\n")
        env = Environment(loader=FileSystemLoader(broken))
        found = TemplateChecker(env).check("page.html", context).diagnostics
        assert [d.code for d in found] == ["E101"], found
        assert found[0].template == "leaf_row.html"
    finally:
        shutil.rmtree(broken)


@pytest.mark.unit
def test_scalar_and_fstring_context_resolve():
    bindings, _ = _bindings()
    context, _ = Resolver().resolve_binding(bindings["scalars.html"], None)
    assert context["item_id"].label() == "UUID"
    assert context["label"].label() == "str"
    assert context["leaf"] == ModelRef(Leaf)


@pytest.mark.unit
def test_dynamic_template_name_correlates_with_dispatcher_branch():
    """Gap A: `name=_TABS[tab]` plus a dispatcher keyed on the same literal."""
    paths = sorted(REPO_ROOT.glob(FIXTURE_VIEWS))
    bindings, _ = find_bindings(paths, REPO_ROOT / "src")
    tabbed = [b for b in bindings if len(b.templates) == 2]
    assert tabbed, "the dict-subscript template name should yield two candidates"
    binding = tabbed[0]
    resolver = Resolver()
    resolved = {}
    for position, template in enumerate(binding.templates):
        context, _ = resolver.resolve_binding(binding, binding.dict_keys[position])
        resolved[template] = context["view"].label()
    assert resolved == {"tab_alpha.html": "TabAlpha", "tab_beta.html": "TabBeta"}


@pytest.mark.unit
def test_unresolvable_context_warns_and_checks_nothing():
    bindings, _ = _bindings()
    context, warnings = Resolver().resolve_binding(bindings["unresolved.html"], None)
    assert context["value"].label() == "unknown"
    assert any("unresolved" in w for w in warnings)
    env = Environment(loader=FileSystemLoader(FIXTURE_TEMPLATES))
    # Unknown is absorbing: no false positives on a chain we cannot type.
    assert TemplateChecker(env).check("unresolved.html", context).diagnostics == []
