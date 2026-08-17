"""Static checks over the Jinja templates.

These never render anything, so they need no app, DB, or request context. They
catch the breakage that otherwise ships silently: a syntax error or a typo'd
filter (``test_template_compiles``), and a renamed partial that some
``{% include %}`` still points at (``test_referenced_templates_exist``).

The environment comes from the app's own ``_build_templates`` rather than a bare
``Environment``. That matters because Jinja resolves **filters at compile time**
against the environment: a template using ``{{ x | money }}`` fails to compile in
an environment where ``money`` isn't registered. Sourcing the env from the app
means custom filters are picked up automatically and these tests can't drift out
of sync with production. Register new filters inside ``_build_templates`` (or
something it calls) and there is nothing to do here.

Attribute access against the models routes actually pass is checked separately,
by ``pre_commits.template_types`` (the ``template-types`` pre-commit hook) and its
tests in ``test_template_types.py``.

What nothing here catches, because it is all runtime: unguarded ``Optional``
dereferences (Jinja renders those as blank output rather than raising), Jinja
globals such as ``url_for``, and block/inheritance behaviour. Those need view
tests that actually render a response.
"""

import pathlib

import pytest
from jinja2 import meta

# Private, but deliberately: it is the single place the app's Jinja environment
# is configured, so it is the only env that stays honest about filters. If this
# import breaks, the fix is to point it at the new factory, not to fall back to
# a bare Environment -- a bare env would silently stop checking custom filters.
from backend.jinja import _build_templates

TEMPLATES = pathlib.Path(__file__).parents[3] / "templates"
NAMES = sorted(p.relative_to(TEMPLATES).as_posix() for p in TEMPLATES.rglob("*.html"))


def _env():
    return _build_templates(str(TEMPLATES)).env


def test_templates_are_discovered():
    """Guard against the parametrized tests silently degrading to zero cases."""
    assert NAMES, f"no templates found under {TEMPLATES}"


@pytest.mark.unit
@pytest.mark.parametrize("name", NAMES)
def test_template_compiles(name):
    _env().get_template(name)


@pytest.mark.unit
@pytest.mark.parametrize("name", NAMES)
def test_referenced_templates_exist(name):
    """Every statically-named extends/include/import target must resolve."""
    env = _env()
    source = env.loader.get_source(env, name)[0]
    referenced = meta.find_referenced_templates(env.parse(source))

    # `None` marks a dynamically-computed target (e.g. `{% include some_var %}`)
    # which cannot be resolved without rendering; skip those rather than fail.
    missing = [
        ref for ref in referenced if ref is not None and not (TEMPLATES / ref).is_file()
    ]
    assert not missing, f"{name} references non-existent template(s): {missing}"
