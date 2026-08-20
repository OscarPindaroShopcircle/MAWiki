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


class RagConvertedFileView(AppBaseModel):
    id: UUIDField
    name: str
    output_index: int
    preview: str


class RagSourceFileView(AppBaseModel):
    id: UUIDField
    name: str
    mime_type: str | None
    is_converted: bool
    converted_files: list[RagConvertedFileView]


class RagChunkView(AppBaseModel):
    id: str
    preview: str
    output_index: int
    page_number: int | None
    split_id: int
    split_idx_start: int
    character_count: int
    word_count: int
