import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..users.models import UserModel
from .models import RagModel
from .schemas import RagCreate, RagUpdate


class RagRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: RagCreate, owner_id: uuid.UUID) -> RagModel:
        owner = await self.db.get(UserModel, owner_id)
        if owner is None:
            raise ValueError("Owner does not exist")
        rag = RagModel(
            name=data.name,
            owner=owner,
            owner_id=owner_id,
            source_knowledge_base_id=data.source_knowledge_base_id,
        )
        self.db.add(rag)
        await self.db.flush()
        return rag

    async def get(
        self, rag_id: uuid.UUID, owner_id: uuid.UUID, is_admin: bool
    ) -> RagModel | None:
        stmt = (
            select(RagModel)
            .options(selectinload(RagModel.owner))
            .where(RagModel.id == rag_id)
        )
        if not is_admin:
            stmt = stmt.where(RagModel.owner_id == owner_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_page(
        self, owner_id: uuid.UUID, is_admin: bool, page: int, page_size: int
    ) -> tuple[list[RagModel], int]:
        count_stmt = select(func.count()).select_from(RagModel)
        stmt = select(RagModel).options(selectinload(RagModel.owner))
        if not is_admin:
            count_stmt = count_stmt.where(RagModel.owner_id == owner_id)
            stmt = stmt.where(RagModel.owner_id == owner_id)
        total = await self.db.scalar(count_stmt)
        result = await self.db.execute(
            stmt.order_by(RagModel.created_at, RagModel.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.scalars().all()), total or 0

    async def update(self, rag: RagModel, data: RagUpdate) -> RagModel:
        rag.name = data.name
        await self.db.flush()
        await self.db.refresh(rag, attribute_names=["updated_at"])
        return rag

    async def delete(self, rag: RagModel) -> None:
        await self.db.delete(rag)
        await self.db.flush()
