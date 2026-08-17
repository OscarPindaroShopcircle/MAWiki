import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import TaskModel
from .schemas import TaskCreate, TaskUpdate


class TaskRepository:
    """Async CRUD for TaskModel."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: TaskCreate) -> TaskModel:
        task = TaskModel(**data.model_dump())
        self.db.add(task)
        await self.db.flush()
        await self.db.refresh(task)
        return task

    async def get(self, task_id: uuid.UUID) -> TaskModel | None:
        result = await self.db.execute(select(TaskModel).where(TaskModel.id == task_id))
        return result.scalar_one_or_none()

    async def get_all(
        self, limit: int | None = None, offset: int = 0
    ) -> list[TaskModel]:
        stmt = (
            select(TaskModel)
            .order_by(TaskModel.created_at, TaskModel.id)
            .offset(offset)
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update(self, task_id: uuid.UUID, data: TaskUpdate) -> TaskModel | None:
        task = await self.get(task_id)
        if task is None:
            return None

        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(task, field, value)

        await self.db.flush()
        await self.db.refresh(task)
        return task

    async def delete(self, task_id: uuid.UUID) -> bool:
        task = await self.get(task_id)
        if task is None:
            return False

        await self.db.delete(task)
        await self.db.flush()
        return True
