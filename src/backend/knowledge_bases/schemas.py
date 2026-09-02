from typing import Annotated

from pydantic import Field

from ..schemas import AppBaseModel, TimestampMixin, UUIDField
from ..tasks.schemas import TaskResponse
from ..users.schemas import UserResponse


class KnowledgeBaseCreate(AppBaseModel):
    name: Annotated[str, Field(min_length=1, max_length=255)]
    source_id: UUIDField


class KnowledgeBaseUpdate(AppBaseModel):
    name: Annotated[str, Field(min_length=1, max_length=255)]


class KnowledgeBaseResponse(AppBaseModel, TimestampMixin):
    id: UUIDField
    name: str
    owner: UserResponse
    source_id: UUIDField
    converted_source_id: UUIDField | None
    conversion_task_id: UUIDField | None
    indexing_task_id: UUIDField | None
    index_file_id: UUIDField | None


class KnowledgeBaseSearchRequest(AppBaseModel):
    query: Annotated[str, Field(min_length=1)]
    top_k: Annotated[int, Field(default=10, ge=1, le=50)]


class KnowledgeBaseSearchResult(AppBaseModel):
    content: str
    score: float
    file_id: UUIDField
    file_name: str


class KnowledgeBaseSearchResponse(AppBaseModel):
    results: list[KnowledgeBaseSearchResult]


class SourceOption(AppBaseModel):
    value: str
    label: str


class KnowledgeBaseView(AppBaseModel):
    id: UUIDField
    name: str
    source_id: UUIDField
    source_name: str
    is_converted: bool
    is_indexed: bool
    conversion_task: TaskResponse | None = None
    indexing_task: TaskResponse | None = None


class ConvertedFileView(AppBaseModel):
    id: UUIDField
    name: str
    output_index: int
    content: str


class SourceFileView(AppBaseModel):
    id: UUIDField
    name: str
    mime_type: str | None
    is_converted: bool
    converted_files: list[ConvertedFileView]


class ChunkView(AppBaseModel):
    id: str
    preview: str
    output_index: int
    page_number: int | None
    split_id: int
    split_idx_start: int
    split_idx_end: int
    character_count: int
    word_count: int
    color_index: int
