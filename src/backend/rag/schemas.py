from typing import Annotated

from pydantic import Field

from ..schemas import AppBaseModel, TimestampMixin, UUIDField
from ..users.schemas import UserResponse


class RagCreate(AppBaseModel):
    name: Annotated[str, Field(min_length=1, max_length=255)]
    source_knowledge_base_id: UUIDField


class RagUpdate(AppBaseModel):
    name: Annotated[str, Field(min_length=1, max_length=255)]


class RagResponse(AppBaseModel, TimestampMixin):
    id: UUIDField
    name: str
    owner: UserResponse
    source_knowledge_base_id: UUIDField
    converted_knowledge_base_id: UUIDField | None
    conversion_task_id: UUIDField | None
    indexing_task_id: UUIDField | None
    index_file_id: UUIDField | None


class RagSearchRequest(AppBaseModel):
    query: Annotated[str, Field(min_length=1)]
    top_k: Annotated[int, Field(default=10, ge=1, le=50)]


class RagSearchResult(AppBaseModel):
    content: str
    score: float
    file_id: UUIDField
    file_name: str


class RagSearchResponse(AppBaseModel):
    results: list[RagSearchResult]
