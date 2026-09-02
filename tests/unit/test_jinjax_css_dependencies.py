from __future__ import annotations

from pathlib import Path

from backend.jinja import get_catalog
from pre_commits.jinjax_css_dependencies.hook import run_check

REPO_ROOT = Path(__file__).parents[2]
COMPONENTS_DIR = REPO_ROOT / "src" / "frontend" / "components"


def _component(root: Path, path: str, source: str, *, css: bool = False) -> Path:
    component = root / f"{path}.jinja"
    component.parent.mkdir(parents=True, exist_ok=True)
    component.write_text(source)
    if css:
        component.with_suffix(".css").write_text("")
    return component


def test_adds_referenced_component_css(tmp_path: Path) -> None:
    components = tmp_path / "components"
    grid = _component(
        components,
        "pages/KnowledgeBaseGrid",
        "{#def knowledge_bases #}\n"
        "{% for knowledge_base in knowledge_bases %}\n"
        "<common.Card><common.Pill /></common.Card>\n"
        "{% endfor %}\n",
    )
    _component(components, "common/Card", "<div>{{ content }}</div>\n", css=True)
    _component(components, "common/Pill", "<span>{{ content }}</span>\n", css=True)

    assert run_check(components) == [grid]
    assert grid.read_text() == (
        "{#def knowledge_bases #}\n"
        "{#css common/Card.css, common/Pill.css #}\n"
        "{% for knowledge_base in knowledge_bases %}\n"
        "<common.Card><common.Pill /></common.Card>\n"
        "{% endfor %}\n"
    )
    assert run_check(components, check=True) == []


def test_includes_transitive_component_css(tmp_path: Path) -> None:
    components = tmp_path / "components"
    page = _component(components, "pages/Page", "<common.Parent />\n")
    _component(
        components,
        "common/Parent",
        "{% if visible %}<common.Child />{% endif %}\n",
        css=True,
    )
    _component(
        components,
        "common/Child",
        "{% if visible %}<common.Leaf />{% endif %}\n",
        css=True,
    )
    _component(components, "common/Leaf", "<span>{{ content }}</span>\n", css=True)

    run_check(components)

    assert page.read_text() == (
        "{#css common/Child.css, common/Leaf.css, common/Parent.css #}\n"
        "<common.Parent />\n"
    )


def test_preserves_explicit_css_and_ignores_unknown_tags(tmp_path: Path) -> None:
    components = tmp_path / "components"
    page = _component(
        components,
        "pages/Page",
        "{#def title #}\n"
        "{#css common/Dialog.css #}\n"
        "<!-- <common.Hidden /> -->\n"
        "<main><common.Card /></main>\n",
    )
    _component(
        components, "common/Dialog", "<dialog>{{ content }}</dialog>\n", css=True
    )
    _component(components, "common/Card", "<div>{{ content }}</div>\n", css=True)

    run_check(components)

    assert page.read_text() == (
        "{#def title #}\n"
        "{#css common/Dialog.css, common/Card.css #}\n"
        "<!-- <common.Hidden /> -->\n"
        "<main><common.Card /></main>\n"
    )


def test_knowledge_base_list_preloads_card_css_when_empty() -> None:
    catalog = get_catalog(str(COMPONENTS_DIR))

    html = catalog.render(
        "pages.knowledge_bases.KnowledgeBaseList",
        knowledge_bases=[],
        current_user=None,
    )

    assert "/static/components/common/Card.css" in html
    assert "/static/components/common/Pill.css" in html
