import uuid
from dataclasses import replace
from pathlib import Path

import pytest
import pytest_asyncio
from haystack import Document, component
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai.document_codec import MarkdownDocumentCodec
from src.backend.db.enums import UserRole
from src.backend.files.models import FileModel, StorageType
from src.backend.filesystem import LocalFileSystem
from src.backend.kb.exception import KnowledgeBaseAccessDeniedException
from src.backend.kb.models import KnowledgeBaseModel
from src.backend.kb.schemas import KnowledgeBaseCreate
from src.backend.kb.service import create_knowledge_base, get_knowledge_base
from src.backend.mcp.exceptions import McpSessionAccessDeniedException
from src.backend.mcp.models import McpToolCallModel, McpToolName
from src.backend.mcp.service import (
    McpPrincipal,
    get_mcp_session,
    record_mcp_tool_call,
    resolve_mcp_user,
)
from src.backend.rag.exception import (
    RagNotConvertedException,
    RagNotFoundException,
    RagNotIndexedException,
    RagOperationInProgressException,
)
from src.backend.rag.repository import RagRepository
from src.backend.rag.schemas import RagCreate, RagResponse, RagSearchRequest, RagUpdate
from src.backend.rag.service import (
    convert_rag_model_files,
    create_rag_model,
    delete_rag_model,
    get_mcp_rag_file_content,
    get_mcp_rag_models,
    get_rag_file_chunks,
    get_rag_file_conversion_data,
    get_rag_model,
    get_rag_models,
    poll_rag_operation,
    index_rag_model_files,
    search_rag_model,
    start_rag_operation,
    update_rag_model,
)
from src.backend.users.models import UserModel
from src.backend.users.schemas import User


@pytest_asyncio.fixture
async def rag_users(db_session: AsyncSession) -> list[User]:
    models = [
        UserModel(name="Owner", email="rag-owner@example.com", role=UserRole.MEMBER),
        UserModel(name="Viewer", email="rag-viewer@example.com", role=UserRole.MEMBER),
        UserModel(name="Other", email="rag-other@example.com", role=UserRole.MEMBER),
        UserModel(name="Admin", email="rag-admin@example.com", role=UserRole.ADMIN),
    ]
    for model in models:
        db_session.add(model)
        await db_session.flush()
    return [User.model_validate(model) for model in models]


@pytest.mark.integration
async def test_rag_model_crud_is_owner_scoped_and_keeps_source_kb(
    db_session: AsyncSession, rag_users: list[User]
):
    owner, _, other, admin = rag_users
    knowledge_base = await create_knowledge_base(
        db_session, KnowledgeBaseCreate(name="Source"), owner
    )
    first = await create_rag_model(
        db_session,
        RagCreate(name="First", source_knowledge_base_id=knowledge_base.id),
        owner,
    )
    second = await create_rag_model(
        db_session,
        RagCreate(name="Second", source_knowledge_base_id=knowledge_base.id),
        owner,
    )

    assert first.source_knowledge_base_id == second.source_knowledge_base_id
    assert first.converted_knowledge_base_id is None
    assert (await get_rag_models(db_session, owner))[1] == 2
    assert (await get_rag_models(db_session, other))[1] == 0
    assert (await get_rag_models(db_session, admin))[1] == 2
    with pytest.raises(RagNotFoundException):
        await get_rag_model(db_session, first.id, other)

    updated = await update_rag_model(
        db_session, first.id, RagUpdate(name="Renamed"), owner
    )
    assert updated.name == "Renamed"
    assert str(updated.source_knowledge_base_id) == str(knowledge_base.id)
    assert RagResponse.model_validate(updated).name == "Renamed"
    assert "source_knowledge_base_id" not in RagUpdate.model_fields

    await delete_rag_model(db_session, first.id, owner)
    with pytest.raises(RagNotFoundException):
        await get_rag_model(db_session, first.id, owner)
    assert await db_session.get(KnowledgeBaseModel, knowledge_base.id) is not None


@pytest.mark.integration
async def test_only_kb_creator_or_admin_can_create_rag_model(
    db_session: AsyncSession, rag_users: list[User]
):
    owner, viewer, _, admin = rag_users
    knowledge_base = await create_knowledge_base(
        db_session,
        KnowledgeBaseCreate(name="Shared source", shared_with=[viewer.id]),
        owner,
    )
    data = RagCreate(name="RAG", source_knowledge_base_id=knowledge_base.id)

    with pytest.raises(KnowledgeBaseAccessDeniedException):
        await create_rag_model(db_session, data, viewer)

    rag = await create_rag_model(db_session, data, admin)
    assert rag.owner_id == admin.id


@component
class KeywordDocumentEmbedder:
    @component.output_types(documents=list[Document])
    def run(self, documents: list[Document]) -> dict[str, list[Document]]:
        return {
            "documents": [
                replace(
                    document,
                    embedding=[0.0, 1.0]
                    if "gamma" in (document.content or "")
                    else [1.0, 0.0],
                )
                for document in documents
            ]
        }


@component
class KeywordTextEmbedder:
    @component.output_types(embedding=list[float])
    def run(self, text: str) -> dict[str, list[float]]:
        return {"embedding": [0.0, 1.0] if "gamma" in text else [1.0, 0.0]}


@pytest.mark.integration
async def test_conversion_index_search_and_reconversion_replace_artifacts(
    db_session: AsyncSession, rag_users: list[User], tmp_path: Path
):
    owner = rag_users[0]
    filesystem = LocalFileSystem(tmp_path)
    knowledge_base = await create_knowledge_base(
        db_session, KnowledgeBaseCreate(name="Source documents"), owner
    )
    source_id = uuid.uuid4()
    source = FileModel(
        id=source_id,
        name="source.txt",
        location=f"knowledge-bases/{knowledge_base.id}/{source_id}",
        mime_type="text/plain",
        storage_type=StorageType.LOCAL,
    )
    await filesystem.write_async(source.location, b"alpha document")
    db_session.add(source)
    knowledge_base = await get_knowledge_base(
        db_session, knowledge_base.id, owner, include_files=True
    )
    knowledge_base.files.append(source)
    unsupported_id = uuid.uuid4()
    unsupported = FileModel(
        id=unsupported_id,
        name="image.png",
        location=f"knowledge-bases/{knowledge_base.id}/{unsupported_id}",
        mime_type="image/png",
        storage_type=StorageType.LOCAL,
    )
    await filesystem.write_async(unsupported.location, b"not an image")
    db_session.add(unsupported)
    knowledge_base.files.append(unsupported)
    await db_session.flush()
    rag = await create_rag_model(
        db_session,
        RagCreate(name="Searchable", source_knowledge_base_id=knowledge_base.id),
        owner,
    )

    message = await convert_rag_model_files(db_session, rag.id, filesystem)
    converted = await RagRepository(db_session).get_for_operation(rag.id)
    assert message == "Converted 1/2 source files; unsupported: image.png"
    assert converted is not None
    converted_id = converted.converted_knowledge_base_id
    old_converted = converted.converted_knowledge_base.files[0]
    converted_document = MarkdownDocumentCodec.loads(
        await filesystem.read_async(old_converted.location),
        document_id=str(old_converted.id),
    )
    assert converted_document.content == "alpha document"
    assert converted_document.meta["source_file_id"] == str(source.id)
    assert converted_document.meta["output_index"] == 0
    _, converted_by_source = await get_rag_file_conversion_data(
        db_session, rag.id, owner, filesystem
    )
    assert converted_by_source[str(source.id)][0][0].id == old_converted.id
    assert str(unsupported.id) not in converted_by_source

    assert "Indexed 1 document chunks" == await index_rag_model_files(
        db_session, rag.id, filesystem, KeywordDocumentEmbedder(), embedding_dim=2
    )
    indexed = await RagRepository(db_session).get_for_operation(rag.id)
    old_index = indexed.index_file
    chunks = await get_rag_file_chunks(db_session, rag.id, source.id, owner, filesystem)
    assert len(chunks) == 1
    assert chunks[0].meta["source_file_id"] == str(source.id)
    assert chunks[0].meta["source_id"] == str(old_converted.id)
    results = await search_rag_model(
        db_session,
        rag.id,
        RagSearchRequest(query="alpha", top_k=1),
        filesystem,
        KeywordTextEmbedder(),
    )
    assert results[0]["content"] == "alpha document"
    assert results[0]["score"] == pytest.approx(1.0)

    await filesystem.write_async(source.location, b"gamma replacement")
    await convert_rag_model_files(db_session, rag.id, filesystem)
    reconverted = await RagRepository(db_session).get_for_operation(rag.id)
    assert reconverted.converted_knowledge_base_id == converted_id
    assert reconverted.index_file_id is None
    assert not (tmp_path / old_converted.location).exists()
    assert not (tmp_path / old_index.location).exists()
    replacement = reconverted.converted_knowledge_base.files[0]
    assert (
        MarkdownDocumentCodec.loads(
            await filesystem.read_async(replacement.location),
            document_id=str(replacement.id),
        ).content
        == "gamma replacement"
    )
    with pytest.raises(RagNotIndexedException):
        await search_rag_model(
            db_session,
            rag.id,
            RagSearchRequest(query="gamma"),
            filesystem,
            KeywordTextEmbedder(),
        )

    preserved = reconverted.converted_knowledge_base.files[0]
    source.name = "source.bin"
    source.mime_type = "application/octet-stream"
    await db_session.flush()
    with pytest.raises(ValueError, match="No files could be converted"):
        await convert_rag_model_files(db_session, rag.id, filesystem)
    assert (tmp_path / preserved.location).exists()


@pytest.mark.integration
async def test_rag_operations_are_pollable_and_cannot_overlap(
    db_session: AsyncSession, rag_users: list[User]
):
    owner, _, other, _ = rag_users
    knowledge_base = await create_knowledge_base(
        db_session, KnowledgeBaseCreate(name="Tasks"), owner
    )
    rag = await create_rag_model(
        db_session,
        RagCreate(name="Task RAG", source_knowledge_base_id=knowledge_base.id),
        owner,
    )

    with pytest.raises(RagNotConvertedException):
        await start_rag_operation(db_session, rag.id, owner, "indexing")
    task = await start_rag_operation(db_session, rag.id, owner, "conversion")
    assert (
        await poll_rag_operation(db_session, rag.id, owner, "conversion")
    ).id == task.id
    with pytest.raises(RagOperationInProgressException):
        await start_rag_operation(db_session, rag.id, owner, "conversion")
    with pytest.raises(RagNotFoundException):
        await poll_rag_operation(db_session, rag.id, other, "conversion")


@pytest.mark.integration
async def test_mcp_services_are_company_wide_and_session_audited(
    db_session: AsyncSession, rag_users: list[User], tmp_path: Path
):
    owner = rag_users[0]
    filesystem = LocalFileSystem(tmp_path)
    knowledge_base = await create_knowledge_base(
        db_session, KnowledgeBaseCreate(name="Company docs"), owner
    )
    source_id = uuid.uuid4()
    source = FileModel(
        id=source_id,
        name="company.txt",
        location=f"knowledge-bases/{knowledge_base.id}/{source_id}",
        mime_type="text/plain",
        storage_type=StorageType.LOCAL,
    )
    await filesystem.write_async(source.location, b"company knowledge")
    db_session.add(source)
    knowledge_base = await get_knowledge_base(
        db_session, knowledge_base.id, owner, include_files=True
    )
    knowledge_base.files.append(source)
    await db_session.flush()
    rag = await create_rag_model(
        db_session,
        RagCreate(name="Company RAG", source_knowledge_base_id=knowledge_base.id),
        owner,
    )
    await convert_rag_model_files(db_session, rag.id, filesystem)
    await index_rag_model_files(
        db_session, rag.id, filesystem, KeywordDocumentEmbedder(), embedding_dim=2
    )

    assert [str(model.id) for model in await get_mcp_rag_models(db_session)] == [
        str(rag.id)
    ]
    results = await search_rag_model(
        db_session,
        rag.id,
        RagSearchRequest(query="company", top_k=1),
        filesystem,
        KeywordTextEmbedder(),
    )
    assert results[0]["source_file_id"] == str(source.id)
    file_name, content = await get_mcp_rag_file_content(
        db_session, rag.id, source.id, filesystem
    )
    assert file_name == source.name
    assert content == "company knowledge"

    user = await resolve_mcp_user(
        db_session,
        McpPrincipal(
            provider="google", subject="employee-1", email="employee@example.com"
        ),
    )
    session = await get_mcp_session(db_session, user, None)
    await record_mcp_tool_call(
        db_session,
        session,
        McpToolName.SEARCH,
        rag_id=rag.id,
        query="company",
    )
    assert (await get_mcp_session(db_session, user, session.id)).id == session.id
    calls = list((await db_session.execute(select(McpToolCallModel))).scalars().all())
    assert [(str(call.session_id), call.tool, call.query) for call in calls] == [
        (str(session.id), McpToolName.SEARCH, "company")
    ]

    other_user = await resolve_mcp_user(
        db_session,
        McpPrincipal(
            provider="google", subject="employee-2", email="other@example.com"
        ),
    )
    with pytest.raises(McpSessionAccessDeniedException):
        await get_mcp_session(db_session, other_user, session.id)
