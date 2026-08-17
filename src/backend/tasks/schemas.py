from typing import Annotated

from pydantic import Field

from .models import TaskStatus
from ..schemas import AppBaseModel, TimestampMixin, UUIDField


class TaskCreate(AppBaseModel):
    name: Annotated[str, Field(min_length=1, max_length=255, examples=["ingest-csv"])]
    status: Annotated[TaskStatus, Field(default=TaskStatus.WAITING)]
    completion: Annotated[float, Field(default=0.0, ge=0, le=100, examples=[0.0])]
    message: Annotated[str | None, Field(default=None)]


class TaskUpdate(AppBaseModel):
    name: Annotated[str | None, Field(default=None, min_length=1, max_length=255)]
    status: Annotated[TaskStatus | None, Field(default=None)]
    completion: Annotated[float | None, Field(default=None, ge=0, le=100)]
    message: Annotated[str | None, Field(default=None)]


class TaskResponse(AppBaseModel, TimestampMixin):
    id: Annotated[UUIDField, Field(description="Task ID")]
    name: Annotated[str, Field(max_length=255)]
    status: Annotated[TaskStatus, Field(description="Current lifecycle status")]
    completion: Annotated[float, Field(ge=0, le=100)]
    message: Annotated[str | None, Field(default=None)]
