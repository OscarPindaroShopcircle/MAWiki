import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..dependencies import get_db_session
from .exceptions import TaskNotFoundException
from .repository import TaskRepository
from .schemas import TaskResponse

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get(
    "/{task_id}",
    response_model=TaskResponse,
    responses={
        200: {"description": "Task found and returned"},
        404: {"description": "Task not found"},
    },
)
async def get_task(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
):
    """Poll a task's status/completion — e.g. after POST /projects."""
    task = await TaskRepository(db).get(task_id)
    if task is None:
        raise TaskNotFoundException(task_id)
    return task
