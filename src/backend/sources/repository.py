import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload, selectinload

from ..files.models import FileModel
from ..users.models import UserModel
from .models import SourceModel, SourceOrigin, source_files
from .schemas import SourceCreate, SourceUpdate


class SourceRepository:
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
            SourceModel.created_by_id == user_id,
            SourceModel.shared_with.any(UserModel.id == user_id),
        )

    def _options(self, include_files: bool, include_shared_with: bool):
        return (
            selectinload(SourceModel.created_by),
            selectinload(SourceModel.files)
            if include_files
            else noload(SourceModel.files),
            selectinload(SourceModel.shared_with)
            if include_shared_with
            else noload(SourceModel.shared_with),
        )

    async def create(self, data: SourceCreate, created_by_id: uuid.UUID) -> SourceModel:
        created_by = await self.db.get(UserModel, created_by_id)
        if created_by is None:
            raise ValueError("Creator does not exist")
        source = SourceModel(
            name=data.name,
            origin=SourceOrigin.USER,
            created_by=created_by,
            created_by_id=created_by_id,
            files=[],
            shared_with=await self._get_users(data.shared_with),
        )
        self.db.add(source)
        await self.db.flush()
        return source

    async def get(
        self,
        source_id: uuid.UUID,
        user_id: uuid.UUID,
        is_admin: bool,
        include_files: bool = False,
        include_shared_with: bool = False,
    ) -> SourceModel | None:
        stmt = (
            select(SourceModel)
            .options(*self._options(include_files, include_shared_with))
            .where(SourceModel.id == source_id)
        )
        if not is_admin:
            stmt = stmt.where(self._visible(user_id))
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def get_page(
        self,
        user_id: uuid.UUID,
        is_admin: bool,
        page: int = 1,
        page_size: int = 20,
        include_files: bool = False,
        include_shared_with: bool = False,
        origin: SourceOrigin = SourceOrigin.USER,
    ) -> tuple[list[SourceModel], int]:
        if page < 1 or page_size < 1:
            raise ValueError("page and page_size must be positive")
        visibility = self._visible(user_id)
        count_stmt = (
            select(func.count())
            .select_from(SourceModel)
            .where(SourceModel.origin == origin)
        )
        stmt = (
            select(SourceModel)
            .options(*self._options(include_files, include_shared_with))
            .where(SourceModel.origin == origin)
        )
        if not is_admin:
            count_stmt = count_stmt.where(visibility)
            stmt = stmt.where(visibility)
        total = await self.db.scalar(count_stmt)
        result = await self.db.execute(
            stmt.order_by(SourceModel.created_at, SourceModel.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.scalars().all()), total or 0

    async def get_existing_file_ids(
        self, source_id: uuid.UUID, file_ids: list[uuid.UUID]
    ) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
        existing = await self.db.scalars(
            select(FileModel.id).where(FileModel.id.in_(file_ids))
        )
        linked = await self.db.scalars(
            select(source_files.c.file_id).where(
                source_files.c.source_id == source_id,
                source_files.c.file_id.in_(file_ids),
            )
        )
        return set(existing), set(linked)

    async def get_files_page(
        self, source_id: uuid.UUID, page: int = 1, page_size: int = 50
    ) -> tuple[list[FileModel], bool]:
        if page < 1 or page_size < 1:
            raise ValueError("page and page_size must be positive")
        result = await self.db.execute(
            select(FileModel)
            .join(source_files, source_files.c.file_id == FileModel.id)
            .where(source_files.c.source_id == source_id)
            .order_by(FileModel.created_at.desc(), FileModel.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size + 1)
        )
        files = list(result.scalars().all())
        return files[:page_size], len(files) > page_size

    async def update(self, source: SourceModel, data: SourceUpdate) -> SourceModel:
        if data.name is not None:
            source.name = data.name
        if data.shared_with is not None:
            source.shared_with = await self._get_users(data.shared_with)
        await self.db.flush()
        return source

    async def delete(self, source: SourceModel) -> None:
        await self.db.delete(source)
        await self.db.flush()
