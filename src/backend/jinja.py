"""Jinja environment factory and the app's custom filters.
ù
The environment is built in one place -- ``_build_templates`` -- so that the
compile-time checks (the ``template-types`` pre-commit hook and the
``test_templates_compile`` suite) and runtime rendering share the same set of
filters. A template using ``{{ x | money }}`` fails to compile in an
environment where ``money`` isn't registered, so sourcing the env from here
keeps the checks honest. Register new filters in ``_build_templates`` (or
something it calls) and there is nothing else to do.
"""

from __future__ import annotations

import zlib
from datetime import UTC, datetime
from functools import lru_cache
from jinjax.catalog import Catalog
from markupsafe import Markup

import jinjax
from fastapi.templating import Jinja2Templates

from .db.enums import UserRole


def _is_admin(user) -> bool:
    """Jinja test: ``{% if current_user is admin %}`` — checks for the ADMIN role."""
    return user is not None and user.role == UserRole.ADMIN


def _is_dev(env: str) -> bool:
    """Jinja test: ``{% if env is dev %}`` — checks for the dev environment."""
    return env == "dev"


def _money(value: float | None) -> str:
    """Jinja filter: ``{{ view.cost.total_cost | money }}`` -> ``"$0.42"``.

    Centralised so the hub's cost pill, metric cards, and per-version rows
    all format the same way instead of repeating ``"$%.2f"|format(...)``.
    """
    return f"${value or 0:.2f}"


def _money_precise(value: float | None) -> str:
    """Jinja filter for costs that are routinely fractions of a cent.

    ``{{ row.avg_cost_per_prediction | money_precise }}`` -> ``"$0.0031"``.
    A single prediction can cost well under a cent, and ``money`` would render
    every such figure as ``$0.00`` -- which reads as free rather than as cheap.
    Falls back to ``money``'s two decimals once the value is big enough for
    them to mean something.
    """
    if value is None:
        return "—"
    if value == 0:
        return "$0.00"
    if abs(value) < 0.01:
        return f"${value:.4f}"
    return f"${value:.2f}"


def _metric_value(value: float | None) -> str:
    """Jinja filter for a metric cell: percentage with 2 decimals, or an em dash.

    A NULL metric means "not applicable to this archetype" or "not computed" --
    never zero -- so it must not render as ``0.00%``.
    """
    if value is None:
        return "—"
    return f"{value * 100:.2f}%"


def _cat_index(value: str, n: int = 8) -> int:
    """Jinja filter: deterministic category index from a string.

    ``{{ user.name | cat_index }}`` -> ``3``
    Uses ``zlib.crc32`` so the same name always maps to the same index
    across process restarts. Used by the Avatar component to pick a
    ``--cat-N`` color without the backend knowing about colors.
    """
    return zlib.crc32((value or "").strip().lower().encode("utf-8")) % n


def _time(value) -> str:
    """Jinja filter: wrap a datetime in a ``<time>`` element with the raw ISO string.

    ``{{ inv.expires_at | time }}`` -> ``<time datetime="2026-08-18T...">...</time>``

    The text content is the raw ISO string; a client-side JS utility
    (``format-times.js``) replaces it with the user's local timezone format.
    Falls back to the ISO string if JS is disabled.
    """
    if value is None:
        return "—"
    iso = value.isoformat() if hasattr(value, "isoformat") else str(value)
    return Markup(f'<time datetime="{iso}">{iso}</time>')


@lru_cache(maxsize=1)
def _build_templates(templates_dir: str):
    templates = Jinja2Templates(directory=templates_dir)
    templates.env.filters["money"] = _money
    templates.env.filters["money_precise"] = _money_precise
    templates.env.filters["metric_value"] = _metric_value
    templates.env.filters["time"] = _time
    templates.env.globals["now"] = lambda: datetime.now(UTC)
    return templates


@lru_cache(maxsize=1)
def get_catalog(components_dir: str, *, env: str = "dev") -> Catalog:
    """Build the JinjaX catalog — the object that manages components.

    Components are ``.jinja`` files inside ``components_dir`` (and its
    subfolders). CSS/JS files colocated next to a component are
    auto-loaded and served via a StaticFiles mount (see ``server.py``).
    """
    catalog = jinjax.Catalog(
        globals={"env": env},
        tests={"admin": _is_admin, "dev": _is_dev},
    )
    catalog.add_folder(components_dir)
    catalog.jinja_env.filters["cat_index"] = _cat_index
    catalog.jinja_env.filters["time"] = _time
    return catalog
