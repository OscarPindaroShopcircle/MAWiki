import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import UserModel
from .schemas import UserCreate, UserUpdate


class UserRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_user(self, user_data: UserCreate) -> UserModel:
        user = UserModel(name=user_data.name, email=user_data.email)
        self.db.add(user)
        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def get_user(self, user_id: uuid.UUID) -> UserModel | None:
        result = await self.db.execute(select(UserModel).where(UserModel.id == user_id))
        return result.scalar_one_or_none()

    async def get_all_users(self) -> list[UserModel]:
        result = await self.db.execute(select(UserModel))
        return list(result.scalars().all())

    async def update_user(
        self, user_id: uuid.UUID, user_data: UserUpdate
    ) -> UserModel | None:
        user = await self.get_user(user_id)
        if user is None:
            return None

        user.name = user_data.name
        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def delete_user(self, user_id: uuid.UUID) -> bool:
        user = await self.get_user(user_id)
        if user is None:
            return False

        await self.db.delete(user)
        await self.db.flush()
        return True
