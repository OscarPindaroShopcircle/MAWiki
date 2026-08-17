import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import FileModel
from .schemas import FileCreate, FileUpdate


class FileRepository:
    """Async CRUD for FileModel."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: FileCreate) -> FileModel:
        file = FileModel(**data.model_dump())
        self.db.add(file)
        await self.db.flush()
        await self.db.refresh(file)
        return file

    async def get(self, file_id: uuid.UUID) -> FileModel | None:
        result = await self.db.execute(select(FileModel).where(FileModel.id == file_id))
        return result.scalar_one_or_none()

    async def get_all(
        self, limit: int | None = None, offset: int = 0
    ) -> list[FileModel]:
        stmt = select(FileModel).order_by(FileModel.created_at).offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update(self, file_id: uuid.UUID, data: FileUpdate) -> FileModel | None:
        file = await self.get(file_id)
        if file is None:
            return None

        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(file, field, value)

        await self.db.flush()
        await self.db.refresh(file)
        return file

    async def delete(self, file_id: uuid.UUID) -> bool:
        file = await self.get(file_id)
        if file is None:
            return False

        await self.db.delete(file)
        await self.db.flush()
        return True
