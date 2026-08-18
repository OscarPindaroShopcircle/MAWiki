import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload, selectinload

from ..users.models import UserModel
from .models import KnowledgeBaseModel
from .schemas import KnowledgeBaseCreate, KnowledgeBaseUpdate


class KnowledgeBaseRepository:
    """Async database access for knowledge bases."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _get_users(self, user_ids: list[uuid.UUID]) -> list[UserModel]:
        if not user_ids:
            return []
        result = await self.db.execute(
            select(UserModel).where(UserModel.id.in_(user_ids))
        )
        users = list(result.scalars().all())
        if len(users) != len(set(user_ids)):
            raise ValueError("One or more shared users do not exist")
        return users

    @staticmethod
    def _visible(user_id: uuid.UUID):
        return or_(
            KnowledgeBaseModel.created_by_id == user_id,
            KnowledgeBaseModel.shared_with.any(UserModel.id == user_id),
        )

    def _options(self, include_files: bool, include_shared_with: bool):
        return (
            selectinload(KnowledgeBaseModel.created_by),
            selectinload(KnowledgeBaseModel.files)
            if include_files
            else noload(KnowledgeBaseModel.files),
            selectinload(KnowledgeBaseModel.shared_with)
            if include_shared_with
            else noload(KnowledgeBaseModel.shared_with),
        )

    async def create(
        self, data: KnowledgeBaseCreate, created_by_id: uuid.UUID
    ) -> KnowledgeBaseModel:
        created_by = await self.db.get(UserModel, created_by_id)
        if created_by is None:
            raise ValueError("Creator does not exist")
        knowledge_base = KnowledgeBaseModel(
            name=data.name,
            created_by=created_by,
            created_by_id=created_by_id,
            shared_with=await self._get_users(data.shared_with),
        )
        self.db.add(knowledge_base)
        await self.db.flush()
        return knowledge_base

    async def get(
        self,
        knowledge_base_id: uuid.UUID,
        user_id: uuid.UUID,
        is_admin: bool,
        include_files: bool = False,
        include_shared_with: bool = False,
    ) -> KnowledgeBaseModel | None:
        stmt = (
            select(KnowledgeBaseModel)
            .options(*self._options(include_files, include_shared_with))
            .where(KnowledgeBaseModel.id == knowledge_base_id)
        )
        if not is_admin:
            stmt = stmt.where(self._visible(user_id))
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_page(
        self,
        user_id: uuid.UUID,
        is_admin: bool,
        page: int = 1,
        page_size: int = 20,
        include_files: bool = False,
        include_shared_with: bool = False,
    ) -> tuple[list[KnowledgeBaseModel], int]:
        if page < 1 or page_size < 1:
            raise ValueError("page and page_size must be positive")

        visibility = self._visible(user_id)
        count_stmt = select(func.count()).select_from(KnowledgeBaseModel)
        stmt = select(KnowledgeBaseModel).options(
            *self._options(include_files, include_shared_with)
        )
        if not is_admin:
            count_stmt = count_stmt.where(visibility)
            stmt = stmt.where(visibility)

        total = await self.db.scalar(count_stmt)
        result = await self.db.execute(
            stmt.order_by(KnowledgeBaseModel.created_at, KnowledgeBaseModel.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.scalars().all()), total or 0

    async def update(
        self,
        knowledge_base: KnowledgeBaseModel,
        data: KnowledgeBaseUpdate,
    ) -> KnowledgeBaseModel:
        if data.name is not None:
            knowledge_base.name = data.name
        if data.shared_with is not None:
            knowledge_base.shared_with = await self._get_users(data.shared_with)

        await self.db.flush()
        return knowledge_base

    async def delete(self, knowledge_base: KnowledgeBaseModel) -> None:
        await self.db.delete(knowledge_base)
        await self.db.flush()
