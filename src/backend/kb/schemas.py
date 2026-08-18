from typing import Annotated

from pydantic import Field

from ..files.schemas import FileResponse
from ..schemas import AppBaseModel, TimestampMixin, UUIDField
from ..users.schemas import UserResponse


class KnowledgeBaseCreate(AppBaseModel):
    name: Annotated[str, Field(min_length=1, max_length=255)]
    shared_with: list[UUIDField] = Field(default_factory=list)


class KnowledgeBaseUpdate(AppBaseModel):
    name: Annotated[str | None, Field(default=None, min_length=1, max_length=255)]
    shared_with: list[UUIDField] | None = None


class KnowledgeBaseResponse(AppBaseModel, TimestampMixin):
    id: Annotated[UUIDField, Field(description="Knowledge base ID")]
    name: Annotated[str, Field(max_length=255)]
    created_by: UserResponse
    files: list[FileResponse] | None = None
    shared_with: list[UserResponse] | None = None
