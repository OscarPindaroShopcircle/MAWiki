import uuid
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import HTMLResponse
from haystack import Document
from jinjax.catalog import Catalog
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_current_user
from ..config import AppConfig, get_app_config
from ..dependencies import get_catalog_dep, get_db_session
from ..files.models import FileModel
from ..filesystem.base import FileSystem
from ..filesystem.dependencies import get_filesystem
from ..sources.models import SourceOrigin
from ..sources.service import get_sources
from ..tasks.models import TaskModel, TaskStatus
from ..tasks.schemas import TaskResponse
from ..users.schemas import User
from .exception import KnowledgeBaseSourceFileNotFoundException
from .models import KnowledgeBaseModel
from .schemas import (
    ChunkView,
    ConvertedFileView,
    KnowledgeBaseCreate,
    KnowledgeBaseView,
    SourceFileView,
    SourceOption,
)
from .service import (
    create_knowledge_base,
    get_knowledge_base,
    get_knowledge_base_file_chunks,
    get_knowledge_base_file_conversion_data,
    get_knowledge_bases,
    poll_knowledge_base_operation,
    run_conversion_job,
    run_indexing_job,
    start_knowledge_base_operation,
)

router = APIRouter(tags=["knowledge-base-views"])


def _task_view(task: TaskModel | None) -> TaskResponse | None:
    return TaskResponse.model_validate(task) if task is not None else None


def _knowledge_base_view(knowledge_base: KnowledgeBaseModel) -> KnowledgeBaseView:
    return KnowledgeBaseView(
        id=knowledge_base.id,
        name=knowledge_base.name,
        source_id=knowledge_base.source_id,
        source_name=knowledge_base.source.name,
        is_converted=knowledge_base.converted_source_id is not None,
        is_indexed=knowledge_base.index_file_id is not None,
        conversion_task=_task_view(knowledge_base.conversion_task),
        indexing_task=_task_view(knowledge_base.indexing_task),
    )


def _source_file_views(
    knowledge_base: KnowledgeBaseModel,
    converted_by_source: dict[str, list[tuple[FileModel, Document]]],
) -> list[SourceFileView]:
    return [
        SourceFileView(
            id=source.id,
            name=source.name,
            mime_type=source.mime_type,
            is_converted=str(source.id) in converted_by_source,
            converted_files=[
                ConvertedFileView(
                    id=file.id,
                    name=file.name,
                    output_index=int(document.meta.get("output_index", 0)),
                    content=document.content or "",
                )
                for file, document in converted_by_source.get(str(source.id), [])
            ],
        )
        for source in knowledge_base.source.files
    ]


def _chunk_views(chunks: list[Document]) -> list[ChunkView]:
    return [
        ChunkView(
            id=chunk.id,
            preview=" ".join((chunk.content or "").split())[:320],
            output_index=int(chunk.meta.get("output_index") or 0),
            page_number=chunk.meta.get("page_number"),
            split_id=int(chunk.meta.get("split_id") or 0),
            split_idx_start=int(chunk.meta.get("split_idx_start") or 0),
            split_idx_end=int(chunk.meta.get("split_idx_start") or 0)
            + len(chunk.content or ""),
            character_count=len(chunk.content or ""),
            word_count=len((chunk.content or "").split()),
            color_index=index % 8,
        )
        for index, chunk in enumerate(chunks)
    ]


async def _source_options(db: AsyncSession, user: User) -> list[SourceOption]:
    sources, _ = await get_sources(
        db, user, page=1, page_size=100, origin=SourceOrigin.USER
    )
    return [SourceOption(value=str(source.id), label=source.name) for source in sources]


@router.get("/knowledge-bases", response_class=HTMLResponse)
async def knowledge_bases_page(
    catalog: Catalog = Depends(get_catalog_dep),
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    knowledge_bases, _ = await get_knowledge_bases(
        db, user, page=1, page_size=100, include_source=True
    )
    return catalog.render(
        "pages.knowledge_bases.KnowledgeBaseList",
        knowledge_bases=[
            _knowledge_base_view(knowledge_base) for knowledge_base in knowledge_bases
        ],
        current_user=user,
    )


@router.get("/knowledge-bases/new", response_class=HTMLResponse)
async def new_knowledge_base_dialog(
    catalog: Catalog = Depends(get_catalog_dep),
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    return catalog.render(
        "pages.knowledge_bases.CreateDialog", sources=await _source_options(db, user)
    )


@router.post("/knowledge-bases", response_class=HTMLResponse)
async def create_knowledge_base_submit(
    data: KnowledgeBaseCreate,
    catalog: Catalog = Depends(get_catalog_dep),
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    try:
        await create_knowledge_base(db, data, user)
    except Exception as exc:
        return catalog.render(
            "pages.knowledge_bases.CreateDialog",
            sources=await _source_options(db, user),
            error=getattr(exc, "detail", str(exc)),
            name=data.name,
            source_id=str(data.source_id),
        )
    knowledge_bases, _ = await get_knowledge_bases(
        db, user, page=1, page_size=100, include_source=True
    )
    return catalog.render(
        "pages.knowledge_bases.KnowledgeBaseGrid",
        knowledge_bases=[
            _knowledge_base_view(knowledge_base) for knowledge_base in knowledge_bases
        ],
    )


@router.get("/knowledge-bases/{knowledge_base_id}", response_class=HTMLResponse)
async def knowledge_base_detail_page(
    knowledge_base_id: uuid.UUID,
    catalog: Catalog = Depends(get_catalog_dep),
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    knowledge_base = await get_knowledge_base(
        db,
        knowledge_base_id,
        user,
        include_source=True,
        include_tasks=True,
        include_index=True,
    )
    return catalog.render(
        "pages.knowledge_bases.KnowledgeBaseDetail",
        knowledge_base=_knowledge_base_view(knowledge_base),
        current_user=user,
    )


@router.get("/knowledge-bases/{knowledge_base_id}/files", response_class=HTMLResponse)
async def knowledge_base_files_panel(
    knowledge_base_id: uuid.UUID,
    catalog: Catalog = Depends(get_catalog_dep),
    db: AsyncSession = Depends(get_db_session),
    filesystem: FileSystem = Depends(get_filesystem),
    user: User = Depends(get_current_user),
):
    knowledge_base, converted_by_source = await get_knowledge_base_file_conversion_data(
        db, knowledge_base_id, user, filesystem
    )
    return catalog.render(
        "pages.knowledge_bases.FileList",
        knowledge_base_id=knowledge_base_id,
        files=_source_file_views(knowledge_base, converted_by_source),
    )


@router.get(
    "/knowledge-bases/{knowledge_base_id}/files/{source_file_id}",
    response_class=HTMLResponse,
)
async def knowledge_base_file_detail_page(
    knowledge_base_id: uuid.UUID,
    source_file_id: uuid.UUID,
    catalog: Catalog = Depends(get_catalog_dep),
    db: AsyncSession = Depends(get_db_session),
    filesystem: FileSystem = Depends(get_filesystem),
    user: User = Depends(get_current_user),
):
    knowledge_base, converted_by_source = await get_knowledge_base_file_conversion_data(
        db, knowledge_base_id, user, filesystem
    )
    file = next(
        (
            item
            for item in _source_file_views(knowledge_base, converted_by_source)
            if item.id == source_file_id
        ),
        None,
    )
    if file is None:
        raise KnowledgeBaseSourceFileNotFoundException(source_file_id)
    chunks = (
        await get_knowledge_base_file_chunks(
            db, knowledge_base_id, source_file_id, user, filesystem
        )
        if knowledge_base.index_file_id is not None and file.is_converted
        else []
    )
    return catalog.render(
        "pages.knowledge_bases.FileDetail",
        knowledge_base=_knowledge_base_view(knowledge_base),
        file=file,
        chunks=_chunk_views(chunks),
        current_user=user,
    )


@router.get(
    "/knowledge-bases/{knowledge_base_id}/files/{source_file_id}/chunks",
    response_class=HTMLResponse,
)
async def knowledge_base_file_chunks(
    knowledge_base_id: uuid.UUID,
    source_file_id: uuid.UUID,
    catalog: Catalog = Depends(get_catalog_dep),
    db: AsyncSession = Depends(get_db_session),
    filesystem: FileSystem = Depends(get_filesystem),
    user: User = Depends(get_current_user),
):
    return catalog.render(
        "pages.knowledge_bases.ChunkList",
        chunks=_chunk_views(
            await get_knowledge_base_file_chunks(
                db, knowledge_base_id, source_file_id, user, filesystem
            )
        ),
    )


async def _start_operation(
    knowledge_base_id: uuid.UUID,
    operation: Literal["conversion", "indexing"],
    background_tasks: BackgroundTasks,
    catalog: Catalog,
    user: User,
    config: AppConfig,
    filesystem: FileSystem,
    db: AsyncSession,
):
    task = await start_knowledge_base_operation(db, knowledge_base_id, user, operation)
    background_tasks.add_task(
        run_conversion_job if operation == "conversion" else run_indexing_job,
        config.database,
        filesystem,
        task.id,
        knowledge_base_id,
    )
    return catalog.render(
        "pages.knowledge_bases.OperationStatus",
        knowledge_base_id=knowledge_base_id,
        operation="index" if operation == "indexing" else operation,
        task=_task_view(task),
    )


@router.post(
    "/knowledge-bases/{knowledge_base_id}/conversion", response_class=HTMLResponse
)
async def start_knowledge_base_conversion_view(
    knowledge_base_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    catalog: Catalog = Depends(get_catalog_dep),
    user: User = Depends(get_current_user),
    config: AppConfig = Depends(get_app_config),
    filesystem: FileSystem = Depends(get_filesystem),
    db: AsyncSession = Depends(get_db_session, scope="function"),
):
    return await _start_operation(
        knowledge_base_id,
        "conversion",
        background_tasks,
        catalog,
        user,
        config,
        filesystem,
        db,
    )


@router.post("/knowledge-bases/{knowledge_base_id}/index", response_class=HTMLResponse)
async def start_knowledge_base_indexing_view(
    knowledge_base_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    catalog: Catalog = Depends(get_catalog_dep),
    user: User = Depends(get_current_user),
    config: AppConfig = Depends(get_app_config),
    filesystem: FileSystem = Depends(get_filesystem),
    db: AsyncSession = Depends(get_db_session, scope="function"),
):
    return await _start_operation(
        knowledge_base_id,
        "indexing",
        background_tasks,
        catalog,
        user,
        config,
        filesystem,
        db,
    )


@router.get(
    "/knowledge-bases/{knowledge_base_id}/{operation}/status",
    response_class=HTMLResponse,
)
async def poll_knowledge_base_operation_view(
    knowledge_base_id: uuid.UUID,
    operation: Literal["conversion", "index"],
    catalog: Catalog = Depends(get_catalog_dep),
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    task = TaskResponse.model_validate(
        await poll_knowledge_base_operation(
            db,
            knowledge_base_id,
            user,
            "indexing" if operation == "index" else "conversion",
        )
    )
    return catalog.render(
        "pages.knowledge_bases.OperationStatus",
        knowledge_base_id=knowledge_base_id,
        operation=operation,
        task=task,
    )
