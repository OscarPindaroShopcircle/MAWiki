import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.db.enums import UserRole
from src.backend.kb.exception import KnowledgeBaseAccessDeniedException
from src.backend.kb.models import KnowledgeBaseModel
from src.backend.kb.schemas import KnowledgeBaseCreate
from src.backend.kb.service import create_knowledge_base
from src.backend.rag.exception import RagNotFoundException
from src.backend.rag.schemas import RagCreate, RagResponse, RagUpdate
from src.backend.rag.service import (
    create_rag_model,
    delete_rag_model,
    get_rag_model,
    get_rag_models,
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
