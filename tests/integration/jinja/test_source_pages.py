import uuid
from datetime import datetime, timezone

import pytest

from src.backend.db.enums import UserRole
from src.backend.files.schemas import FileResponse
from src.backend.jinja import get_catalog
from src.backend.sources.models import SourceOrigin
from src.backend.sources.schemas import SourceResponse
from src.backend.users.schemas import UserResponse

COMPONENTS_DIR = "src/frontend/components"


@pytest.mark.integration
def test_source_components_render_response_schemas() -> None:
    now = datetime.now(timezone.utc)
    user = UserResponse(
        id=uuid.uuid4(),
        name="Test User",
        email="test@example.com",
        role=UserRole.MEMBER,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    file = FileResponse(
        id=uuid.uuid4(),
        name="report.pdf",
        mime_type="application/pdf",
        created_at=now,
        updated_at=now,
    )
    source = SourceResponse(
        id=uuid.uuid4(),
        name="Engineering Docs",
        origin=SourceOrigin.USER,
        created_by=user,
        files=[file],
        shared_with=None,
        created_at=now,
        updated_at=now,
    )
    catalog = get_catalog(COMPONENTS_DIR, env="test")

    listing = catalog.render(
        "pages.sources.SourceList",
        sources=[source],
        current_user=user,
    )
    detail = catalog.render(
        "pages.sources.SourceDetail",
        source=source,
        files=source.files,
        has_more=True,
        current_user=user,
    )
    files = catalog.render(
        "pages.sources.FilesTable",
        source_id=source.id,
        files=source.files,
        has_more=True,
    )

    assert "Engineering Docs" in listing
    assert f'href="/sources/{source.id}"' in listing
    assert "report.pdf" in detail
    assert 'data-max-files="5"' in detail
    assert 'data-max-bytes="26214400"' in detail
    system_source = source.model_copy(update={"origin": SourceOrigin.SYSTEM})
    system_listing = catalog.render(
        "pages.sources.SourceList",
        sources=[system_source],
        origin="SYSTEM",
        current_user=user,
    )
    system_detail = catalog.render(
        "pages.sources.SourceDetail",
        source=system_source,
        files=system_source.files,
        current_user=user,
    )

    assert "Data Sources" in listing
    assert "/sources?origin=SYSTEM" in listing
    assert "UploadMenu.js" in detail
    assert "New Data Source" not in system_listing
    assert "UploadMenu.js" not in system_detail
    assert "System-generated" in system_detail
    assert f"/files/{file.id}/download" in files
    assert 'hx-trigger="revealed"' in files
    assert "page=2&amp;page_size=50" in files
