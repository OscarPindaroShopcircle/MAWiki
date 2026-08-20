import uuid
from datetime import datetime, timezone

import pytest

from src.backend.db.enums import UserRole
from src.backend.jinja import get_catalog
from src.backend.rag.schemas import (
    RagChunkView,
    RagConvertedFileView,
    RagKnowledgeBaseOption,
    RagSourceFileView,
    RagView,
)
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
    assert "build the FAISS index" in html
    assert "Engineering Docs" in html
    assert f'hx-get="/rag/{rag.id}/conversion/status"' in status
    assert "in progress" in status
    assert "<progress" in status
    assert 'hx-swap-oob="outerHTML"' in index_action
    assert f'hx-post="/rag/{rag.id}/index"' in index_action


@pytest.mark.integration
def test_rag_file_panel_detail_and_chunks_render() -> None:
    catalog = get_catalog(COMPONENTS_DIR, env="test")
    rag = _rag(converted=True, indexed=True)
    converted = RagConvertedFileView(
        id=uuid.uuid4(),
        name="report.pdf.md",
        output_index=0,
        preview="Converted report text",
    )
    file = RagSourceFileView(
        id=uuid.uuid4(),
        name="report.pdf",
        mime_type="application/pdf",
        is_converted=True,
        converted_files=[converted],
    )
    chunk = RagChunkView(
        id="chunk-hash",
        preview="A pastel chunk preview",
        output_index=0,
        page_number=2,
        split_id=1,
        split_idx_start=420,
        character_count=240,
        word_count=40,
    )

    files = catalog.render("pages.rag.FileList", rag_id=rag.id, files=[file])
    detail = catalog.render(
        "pages.rag.FileDetail", rag=rag, file=file, current_user=_user()
    )
    chunks = catalog.render("pages.rag.ChunkList", chunks=[chunk])

    assert "circle-check" in files
    assert f'href="/rag/{rag.id}/files/{file.id}"' in files
    assert "Converted report text" in detail
    assert f"/rag/{rag.id}/files/{file.id}/chunks" in detail
    assert "Page 2" in chunks
    assert "Offset 420" in chunks
    assert "A pastel chunk preview" in chunks
