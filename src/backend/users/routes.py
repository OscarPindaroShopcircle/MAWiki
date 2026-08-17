import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..dependencies import get_db_session
from ..schemas import ListResponse
from .exceptions import UserNotFound
from .schemas import UserCreate, UserResponse, UserUpdate
from .service import create_user, get_user, get_all_users, update_user, delete_user


router = APIRouter(prefix="/users", tags=["users"])


@router.post(
    "/",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "User successfully created"},
    },
)
async def create_user_endpoint(
    user_data: UserCreate,
    db: AsyncSession = Depends(get_db_session),
):
    """Create a new user with the provided name."""
    user = await create_user(db, user_data)
    return user


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    responses={
        200: {"description": "User found and returned"},
        404: {"description": "User not found"},
    },
)
async def get_user_endpoint(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
):
    """Retrieve a single user by their ID."""
    user = await get_user(db, user_id)
    if user is None:
        raise UserNotFound(user_id)
    return user


@router.get(
    "/",
    response_model=ListResponse[UserResponse],
    responses={
        200: {"description": "List of all users returned"},
    },
)
async def get_all_users_endpoint(
    db: AsyncSession = Depends(get_db_session),
):
    """Retrieve all users in the system."""
    users = await get_all_users(db)
    return ListResponse(data=users)


@router.patch(
    "/{user_id}",
    response_model=UserResponse,
    responses={
        200: {"description": "User successfully updated"},
        404: {"description": "User not found"},
    },
)
async def update_user_endpoint(
    user_id: uuid.UUID,
    user_data: UserUpdate,
    db: AsyncSession = Depends(get_db_session),
):
    """Update an existing user's name."""
    user = await update_user(db, user_id, user_data)
    if user is None:
        raise UserNotFound(user_id)
    return user


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        204: {"description": "User successfully deleted"},
        404: {"description": "User not found"},
    },
)
async def delete_user_endpoint(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
):
    """Delete a user by their ID."""
    deleted = await delete_user(db, user_id)
    if not deleted:
        raise UserNotFound(user_id)
