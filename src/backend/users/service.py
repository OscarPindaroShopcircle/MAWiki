import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import UserModel
from .schemas import UserCreate, UserUpdate


async def create_user(db: AsyncSession, user_data: UserCreate) -> UserModel:
    user = UserModel(name=user_data.name, email=user_data.email)
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


async def get_user(db: AsyncSession, user_id: uuid.UUID) -> UserModel | None:
    result = await db.execute(select(UserModel).where(UserModel.id == user_id))
    return result.scalar_one_or_none()


async def get_all_users(db: AsyncSession) -> list[UserModel]:
    result = await db.execute(select(UserModel))
    return list(result.scalars().all())


async def update_user(
    db: AsyncSession, user_id: uuid.UUID, user_data: UserUpdate
) -> UserModel | None:
    user = await get_user(db, user_id)
    if user is None:
        return None

    user.name = user_data.name
    await db.flush()
    await db.refresh(user)
    return user


async def delete_user(db: AsyncSession, user_id: uuid.UUID) -> bool:
    user = await get_user(db, user_id)
    if user is None:
        return False

    await db.delete(user)
    await db.flush()
    return True
