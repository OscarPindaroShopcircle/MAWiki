import uuid
from datetime import datetime, timezone

import pytest

from src.backend.db.enums import UserRole
from src.backend.files.schemas import FileResponse
from src.backend.jinja import get_catalog
from src.backend.kb.schemas import KnowledgeBaseResponse
from src.backend.users.schemas import UserResponse

COMPONENTS_DIR = "src/frontend/components"


@pytest.mark.integration
def test_knowledge_base_components_render_response_schemas() -> None:
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
    knowledge_base = KnowledgeBaseResponse(
        id=uuid.uuid4(),
        name="Engineering Docs",
        created_by=user,
        files=[file],
        shared_with=None,
        created_at=now,
        updated_at=now,
    )
    catalog = get_catalog(COMPONENTS_DIR, env="test")

    listing = catalog.render(
        "pages.kb.KnowledgeBaseList",
        knowledge_bases=[knowledge_base],
        current_user=user,
    )
    detail = catalog.render(
        "pages.kb.KnowledgeBaseDetail",
        knowledge_base=knowledge_base,
        files=knowledge_base.files,
        has_more=True,
        current_user=user,
    )
    files = catalog.render(
        "pages.kb.FilesTable",
        knowledge_base_id=knowledge_base.id,
        files=knowledge_base.files,
        has_more=True,
    )

    assert "Engineering Docs" in listing
    assert f'href="/knowledge-bases/{knowledge_base.id}"' in listing
    assert "report.pdf" in detail
    assert 'data-max-files="5"' in detail
    assert 'data-max-bytes="26214400"' in detail
    assert "UploadMenu.js" in detail
    assert f"/files/{file.id}/download" in files
    assert 'hx-trigger="revealed"' in files
    assert "page=2&amp;page_size=50" in files
