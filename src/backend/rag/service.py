import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from ..db.enums import UserRole
from ..kb.exception import KnowledgeBaseAccessDeniedException
from ..kb.service import get_knowledge_base
from ..users.schemas import User
from .exception import RagNotFoundException
from .models import RagModel
from .repository import RagRepository
from .schemas import RagCreate, RagUpdate


def _is_admin(user: User) -> bool:
    return user.role == UserRole.ADMIN


async def create_rag_model(db: AsyncSession, data: RagCreate, user: User) -> RagModel:
    knowledge_base = await get_knowledge_base(db, data.source_knowledge_base_id, user)
    if not _is_admin(user) and knowledge_base.created_by_id != user.id:
        raise KnowledgeBaseAccessDeniedException(knowledge_base.id)
    return await RagRepository(db).create(data, user.id)


async def get_rag_model(db: AsyncSession, rag_id: uuid.UUID, user: User) -> RagModel:
    rag = await RagRepository(db).get(rag_id, user.id, _is_admin(user))
    if rag is None:
        raise RagNotFoundException(rag_id)
    return rag


async def get_rag_models(
    db: AsyncSession, user: User, page: int = 1, page_size: int = 20
) -> tuple[list[RagModel], int]:
    return await RagRepository(db).get_page(user.id, _is_admin(user), page, page_size)


async def update_rag_model(
    db: AsyncSession, rag_id: uuid.UUID, data: RagUpdate, user: User
) -> RagModel:
    rag = await get_rag_model(db, rag_id, user)
    return await RagRepository(db).update(rag, data)


async def delete_rag_model(db: AsyncSession, rag_id: uuid.UUID, user: User) -> None:
    rag = await get_rag_model(db, rag_id, user)
    await RagRepository(db).delete(rag)
