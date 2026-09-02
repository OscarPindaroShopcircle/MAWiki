import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload, selectinload

from ..sources.models import SourceModel
from ..users.models import UserModel
from .models import KnowledgeBaseModel
from .schemas import KnowledgeBaseCreate, KnowledgeBaseUpdate


class KnowledgeBaseRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _options(
        include_source: bool = False,
        include_tasks: bool = False,
        include_index: bool = False,
    ):
        return (
            selectinload(KnowledgeBaseModel.owner),
            selectinload(KnowledgeBaseModel.source)
            if include_source
            else noload(KnowledgeBaseModel.source),
            selectinload(KnowledgeBaseModel.conversion_task)
            if include_tasks
            else noload(KnowledgeBaseModel.conversion_task),
            selectinload(KnowledgeBaseModel.indexing_task)
            if include_tasks
            else noload(KnowledgeBaseModel.indexing_task),
            selectinload(KnowledgeBaseModel.index_file)
            if include_index
            else noload(KnowledgeBaseModel.index_file),
        )

    async def create(
        self, data: KnowledgeBaseCreate, owner_id: uuid.UUID
    ) -> KnowledgeBaseModel:
        owner = await self.db.get(UserModel, owner_id)
        if owner is None:
            raise ValueError("Owner does not exist")
        knowledge_base = KnowledgeBaseModel(
            name=data.name, owner=owner, owner_id=owner_id, source_id=data.source_id
        )
        self.db.add(knowledge_base)
        await self.db.flush()
        return knowledge_base

    async def get(
        self,
        knowledge_base_id: uuid.UUID,
        owner_id: uuid.UUID,
        is_admin: bool,
        include_source: bool = False,
        include_tasks: bool = False,
        include_index: bool = False,
    ) -> KnowledgeBaseModel | None:
        stmt = (
            select(KnowledgeBaseModel)
            .options(*self._options(include_source, include_tasks, include_index))
            .where(KnowledgeBaseModel.id == knowledge_base_id)
        )
        if not is_admin:
            stmt = stmt.where(KnowledgeBaseModel.owner_id == owner_id)
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def get_for_operation(
        self, knowledge_base_id: uuid.UUID, lock: bool = False
    ) -> KnowledgeBaseModel | None:
        stmt = (
            select(KnowledgeBaseModel)
            .options(
                selectinload(KnowledgeBaseModel.owner),
                selectinload(KnowledgeBaseModel.source).selectinload(SourceModel.files),
                selectinload(KnowledgeBaseModel.converted_source).selectinload(
                    SourceModel.files
                ),
                selectinload(KnowledgeBaseModel.conversion_task),
                selectinload(KnowledgeBaseModel.indexing_task),
                selectinload(KnowledgeBaseModel.index_file),
            )
            .where(KnowledgeBaseModel.id == knowledge_base_id)
        )
        if lock:
            stmt = stmt.with_for_update()
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def get_page(
        self,
        owner_id: uuid.UUID,
        is_admin: bool,
        page: int,
        page_size: int,
        include_source: bool = False,
    ) -> tuple[list[KnowledgeBaseModel], int]:
        count_stmt = select(func.count()).select_from(KnowledgeBaseModel)
        stmt = select(KnowledgeBaseModel).options(
            *self._options(include_source=include_source)
        )
        if not is_admin:
            count_stmt = count_stmt.where(KnowledgeBaseModel.owner_id == owner_id)
            stmt = stmt.where(KnowledgeBaseModel.owner_id == owner_id)
        total = await self.db.scalar(count_stmt)
        result = await self.db.execute(
            stmt.order_by(KnowledgeBaseModel.created_at, KnowledgeBaseModel.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.scalars().all()), total or 0

    async def update(
        self, knowledge_base: KnowledgeBaseModel, data: KnowledgeBaseUpdate
    ) -> KnowledgeBaseModel:
        knowledge_base.name = data.name
        await self.db.flush()
        await self.db.refresh(knowledge_base, attribute_names=["updated_at"])
        return knowledge_base

    async def delete(self, knowledge_base: KnowledgeBaseModel) -> None:
        await self.db.delete(knowledge_base)
        await self.db.flush()
