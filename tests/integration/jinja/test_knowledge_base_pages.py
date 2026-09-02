import uuid
from datetime import datetime, timezone

import pytest
from haystack import Document

from src.backend.db.enums import UserRole
from src.backend.jinja import get_catalog
from src.backend.knowledge_bases.schemas import (
    ChunkView,
    ConvertedFileView,
    SourceOption,
    SourceFileView,
    KnowledgeBaseView,
)
from src.backend.knowledge_bases.views import _chunk_views
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


def _knowledge_base(
    converted: bool = False, indexed: bool = False
) -> KnowledgeBaseView:
    return KnowledgeBaseView(
        id=uuid.uuid4(),
        name="Engineering Search",
        source_id=uuid.uuid4(),
        source_name="Engineering Docs",
        is_converted=converted,
        is_indexed=indexed,
    )


@pytest.mark.integration
def test_knowledge_base_list_and_create_dialog_render() -> None:
    catalog = get_catalog(COMPONENTS_DIR, env="test")
    knowledge_base = _knowledge_base()

    html = catalog.render(
        "pages.knowledge_bases.KnowledgeBaseList",
        knowledge_bases=[knowledge_base],
        current_user=_user(),
    )
    dialog = catalog.render(
        "pages.knowledge_bases.CreateDialog",
        sources=[
            SourceOption(value=str(knowledge_base.source_id), label="Engineering Docs")
        ],
    )

    assert "Engineering Search" in html
    assert f'href="/knowledge-bases/{knowledge_base.id}"' in html
    assert "New Knowledge Base" in html
    assert 'name="sourceId"' in dialog
    assert "Engineering Docs" in dialog


@pytest.mark.integration
def test_knowledge_base_detail_and_polling_status_render() -> None:
    catalog = get_catalog(COMPONENTS_DIR, env="test")
    knowledge_base = _knowledge_base(converted=True)
    now = datetime.now(timezone.utc)
    task = TaskResponse(
        id=uuid.uuid4(),
        name="knowledge_base-conversion",
        status=TaskStatus.IN_PROGRESS,
        completion=0,
        created_at=now,
        updated_at=now,
    )

    html = catalog.render(
        "pages.knowledge_bases.KnowledgeBaseDetail",
        knowledge_base=knowledge_base,
        current_user=_user(),
    )
    status = catalog.render(
        "pages.knowledge_bases.OperationStatus",
        knowledge_base_id=knowledge_base.id,
        operation="conversion",
        task=task,
    )
    index_action = catalog.render(
        "pages.knowledge_bases.IndexAction",
        knowledge_base_id=knowledge_base.id,
        is_converted=True,
        is_indexed=False,
        task=None,
        oob=True,
    )

    assert "Convert supported source files" in html
    assert "build the FAISS index" in html
    assert "Engineering Docs" in html
    assert f'hx-get="/knowledge-bases/{knowledge_base.id}/conversion/status"' in status
    assert "in progress" in status
    assert "<progress" in status
    assert 'hx-swap-oob="outerHTML"' in index_action
    assert f'hx-post="/knowledge-bases/{knowledge_base.id}/index"' in index_action


@pytest.mark.integration
def test_knowledge_base_file_panel_detail_and_chunks_render() -> None:
    catalog = get_catalog(COMPONENTS_DIR, env="test")
    knowledge_base = _knowledge_base(converted=True, indexed=True)
    converted = ConvertedFileView(
        id=uuid.uuid4(),
        name="report.pdf.md",
        output_index=0,
        content="# Converted report text\n\n<script>alert('unsafe')</script>",
    )
    file = SourceFileView(
        id=uuid.uuid4(),
        name="report.pdf",
        mime_type="application/pdf",
        is_converted=True,
        converted_files=[converted],
    )
    chunk = ChunkView(
        id="chunk-hash",
        preview="A pastel chunk preview",
        output_index=0,
        page_number=2,
        split_id=1,
        split_idx_start=420,
        split_idx_end=660,
        character_count=240,
        word_count=40,
        color_index=0,
    )

    files = catalog.render(
        "pages.knowledge_bases.FileList",
        knowledge_base_id=knowledge_base.id,
        files=[file],
    )
    detail = catalog.render(
        "pages.knowledge_bases.FileDetail",
        knowledge_base=knowledge_base,
        file=file,
        chunks=[chunk],
        current_user=_user(),
    )
    chunks = catalog.render("pages.knowledge_bases.ChunkList", chunks=[chunk])

    assert "circle-check" in files
    assert f'href="/knowledge-bases/{knowledge_base.id}/files/{file.id}"' in files
    assert "<h1>Converted report text</h1>" in detail
    assert "&lt;script&gt;alert('unsafe')&lt;/script&gt;" in detail
    assert 'data-knowledge-base-mode="source"' in detail
    assert 'data-start="420" data-end="660"' in detail
    assert "Page 2" in chunks
    assert "Characters 420–660" in chunks
    assert "A pastel chunk preview" in chunks


def test_chunk_views_include_end_offsets_and_stable_colors() -> None:
    chunks = _chunk_views(
        [
            Document(content="alpha", meta={"split_idx_start": 7}),
            Document(content="beta", meta={"split_idx_start": 20}),
        ]
    )

    assert chunks[0].split_idx_end == 12
    assert chunks[0].color_index == 0
    assert chunks[1].split_idx_end == 24
    assert chunks[1].color_index == 1
