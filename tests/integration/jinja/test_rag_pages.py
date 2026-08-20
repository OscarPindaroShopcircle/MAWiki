import uuid
from datetime import datetime, timezone

import pytest

from src.backend.db.enums import UserRole
from src.backend.jinja import get_catalog
from src.backend.rag.schemas import RagKnowledgeBaseOption, RagView
from src.backend.tasks.models import TaskStatus
from src.backend.tasks.schemas import TaskResponse
from src.backend.users.schemas import User

COMPONENTS_DIR = "src/frontend/components"


def _user() -> User:
    now = datetime.now(timezone.utc)
    return User(
        id=uuid.uuid4(),
        name="Test User",
        email="test@example.com",
        role=UserRole.MEMBER,
        created_at=now,
        updated_at=now,
    )


def _rag(converted: bool = False, indexed: bool = False) -> RagView:
    return RagView(
        id=uuid.uuid4(),
        name="Engineering Search",
        source_knowledge_base_id=uuid.uuid4(),
        source_knowledge_base_name="Engineering Docs",
        is_converted=converted,
        is_indexed=indexed,
    )


@pytest.mark.integration
def test_rag_list_and_create_dialog_render() -> None:
    catalog = get_catalog(COMPONENTS_DIR, env="test")
    rag = _rag()

    html = catalog.render("pages.rag.RagList", rag_models=[rag], current_user=_user())
    dialog = catalog.render(
        "pages.rag.CreateDialog",
        knowledge_bases=[
            RagKnowledgeBaseOption(
                value=str(rag.source_knowledge_base_id), label="Engineering Docs"
            )
        ],
    )

    assert "Engineering Search" in html
    assert f'href="/rag/{rag.id}"' in html
    assert "New RAG Model" in html
    assert 'name="sourceKnowledgeBaseId"' in dialog
    assert "Engineering Docs" in dialog


@pytest.mark.integration
def test_rag_detail_and_polling_status_render() -> None:
    catalog = get_catalog(COMPONENTS_DIR, env="test")
    rag = _rag(converted=True)
    now = datetime.now(timezone.utc)
    task = TaskResponse(
        id=uuid.uuid4(),
        name="rag-conversion",
        status=TaskStatus.IN_PROGRESS,
        completion=0,
        created_at=now,
        updated_at=now,
    )

    html = catalog.render("pages.rag.RagDetail", rag=rag, current_user=_user())
    status = catalog.render(
        "pages.rag.OperationStatus",
        rag_id=rag.id,
        operation="conversion",
        task=task,
    )
    index_action = catalog.render(
        "pages.rag.IndexAction",
        rag_id=rag.id,
        is_converted=True,
        is_indexed=False,
        task=None,
        oob=True,
    )

    assert "Convert supported source files" in html
    assert "Build a FAISS index" in html
    assert "Engineering Docs" in html
    assert f'hx-get="/rag/{rag.id}/conversion/status"' in status
    assert "in progress" in status
    assert "<progress" in status
    assert 'hx-swap-oob="outerHTML"' in index_action
    assert f'hx-post="/rag/{rag.id}/index"' in index_action
