from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import RagModel


class RagRepository:
    """Database access for RagModel."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, item_id: int) -> RagModel | None:
        result = await self.db.execute(select(RagModel).where(RagModel.id == item_id))
        return result.scalar_one_or_none()

    async def get_all(self) -> list[RagModel]:
        result = await self.db.execute(select(RagModel))
        return list(result.scalars().all())
