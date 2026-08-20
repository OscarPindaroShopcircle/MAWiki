from typing import Annotated

from pydantic import Field

from ..schemas import AppBaseModel, TimestampMixin, UUIDField
from ..tasks.schemas import TaskResponse
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


class RagKnowledgeBaseOption(AppBaseModel):
    value: str
    label: str


class RagView(AppBaseModel):
    id: UUIDField
    name: str
    source_knowledge_base_id: UUIDField
    source_knowledge_base_name: str
    is_converted: bool
    is_indexed: bool
    conversion_task: TaskResponse | None = None
    indexing_task: TaskResponse | None = None
