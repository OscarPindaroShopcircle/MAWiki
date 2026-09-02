import re
import uuid
from datetime import datetime, timezone

import pytest

from src.backend.db.enums import UserRole
from src.backend.jinja import get_catalog
from src.backend.users.schemas import User

COMPONENTS_DIR = "src/frontend/components"

_now = datetime.now(timezone.utc)


def _make_user(role: UserRole) -> User:
    return User(
        id=uuid.uuid4(),
        name="Test User",
        email="test@example.com",
        role=role,
        created_at=_now,
        updated_at=_now,
    )


@pytest.mark.integration
def test_sidebar_shows_showcase_in_dev_for_admin() -> None:
    catalog = get_catalog(COMPONENTS_DIR, env="dev")
    html = catalog.render(
        "layout.Sidebar",
        current_user=_make_user(UserRole.ADMIN),
        active="home",
    )
    assert "Showcase" in html
    assert 'href="/components"' in html


@pytest.mark.integration
def test_sidebar_hides_showcase_in_production_for_admin() -> None:
    catalog = get_catalog(COMPONENTS_DIR, env="production")
    html = catalog.render(
        "layout.Sidebar",
        current_user=_make_user(UserRole.ADMIN),
        active="home",
    )
    assert "Showcase" not in html
    assert 'href="/components"' not in html


@pytest.mark.integration
def test_sidebar_hides_showcase_for_non_admin_regardless_of_env() -> None:
    for env in ("dev", "production"):
        catalog = get_catalog(COMPONENTS_DIR, env=env)
        html = catalog.render(
            "layout.Sidebar",
            current_user=_make_user(UserRole.MEMBER),
            active="home",
        )
        assert "Showcase" not in html, f"Showcase leaked for MEMBER in {env}"
        assert 'href="/components"' not in html, (
            f"components link leaked for MEMBER in {env}"
        )


@pytest.mark.integration
def test_showcase_marks_its_sidebar_item_active() -> None:
    catalog = get_catalog(COMPONENTS_DIR, env="dev")
    html = catalog.render(
        "pages.showcase.Showcase",
        users=[],
        current_user=_make_user(UserRole.ADMIN),
    )

    assert re.search(
        r'href="/components"\s+class="sidebar-link sidebar-link-active"', html
    )
    assert not re.search(r'href="/"\s+class="sidebar-link sidebar-link-active"', html)
