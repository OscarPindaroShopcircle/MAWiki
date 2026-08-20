import uuid
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import HTMLResponse
from jinjax.catalog import Catalog
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_current_user
from ..config import AppConfig, get_app_config
from ..dependencies import get_catalog_dep, get_db_session
from ..filesystem.base import FileSystem
from ..filesystem.dependencies import get_filesystem
from ..kb.exception import (
    KnowledgeBaseAccessDeniedException,
    KnowledgeBaseNotFoundException,
)
from ..kb.service import get_knowledge_bases
from ..tasks.models import TaskModel, TaskStatus
from ..tasks.schemas import TaskResponse
from ..users.schemas import User
from .models import RagModel
from .schemas import RagCreate, RagKnowledgeBaseOption, RagView
from .service import (
    create_rag_model,
    get_rag_model,
    get_rag_models,
    poll_rag_operation,
    run_conversion_job,
    run_indexing_job,
    start_rag_operation,
)


router = APIRouter(tags=["rag-views"])


def _task_view(task: TaskModel | None) -> TaskResponse | None:
    return TaskResponse.model_validate(task) if task is not None else None


def _rag_view(rag: RagModel) -> RagView:
    return RagView(
        id=rag.id,
        name=rag.name,
        source_knowledge_base_id=rag.source_knowledge_base_id,
        source_knowledge_base_name=rag.source_knowledge_base.name,
        is_converted=rag.converted_knowledge_base_id is not None,
        is_indexed=rag.index_file_id is not None,
        conversion_task=_task_view(rag.conversion_task),
        indexing_task=_task_view(rag.indexing_task),
    )


async def _knowledge_base_options(
    db: AsyncSession, user: User
) -> list[RagKnowledgeBaseOption]:
    knowledge_bases, _ = await get_knowledge_bases(db, user, page=1, page_size=100)
    return [
        RagKnowledgeBaseOption(value=str(knowledge_base.id), label=knowledge_base.name)
        for knowledge_base in knowledge_bases
    ]


@router.get("/rag", response_class=HTMLResponse)
async def rag_models_page(
    catalog: Catalog = Depends(get_catalog_dep),
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """List RAG models visible to the current user."""
    rag_models, _ = await get_rag_models(
        db, user, page=1, page_size=100, include_source=True
    )
    return catalog.render(
        "pages.rag.RagList",
        rag_models=[_rag_view(rag) for rag in rag_models],
        current_user=user,
    )


@router.get("/rag/new", response_class=HTMLResponse)
async def new_rag_model_dialog(
    catalog: Catalog = Depends(get_catalog_dep),
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Return the create-RAG-model dialog."""
    return catalog.render(
        "pages.rag.CreateDialog",
        knowledge_bases=await _knowledge_base_options(db, user),
    )


@router.post("/rag", response_class=HTMLResponse)
async def create_rag_model_submit(
    data: RagCreate,
    catalog: Catalog = Depends(get_catalog_dep),
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Create a RAG model and return the refreshed card grid."""
    try:
        await create_rag_model(db, data, user)
    except (KnowledgeBaseAccessDeniedException, KnowledgeBaseNotFoundException) as exc:
        return catalog.render(
            "pages.rag.CreateDialog",
            knowledge_bases=await _knowledge_base_options(db, user),
            error=exc.detail,
            name=data.name,
            source_knowledge_base_id=str(data.source_knowledge_base_id),
        )
    rag_models, _ = await get_rag_models(
        db, user, page=1, page_size=100, include_source=True
    )
    return catalog.render(
        "pages.rag.RagGrid", rag_models=[_rag_view(rag) for rag in rag_models]
    )


@router.get("/rag/{rag_id}", response_class=HTMLResponse)
async def rag_model_detail_page(
    rag_id: uuid.UUID,
    catalog: Catalog = Depends(get_catalog_dep),
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Show one RAG model and its available operations."""
    rag = await get_rag_model(
        db,
        rag_id,
        user,
        include_source=True,
        include_tasks=True,
        include_index=True,
    )
    return catalog.render("pages.rag.RagDetail", rag=_rag_view(rag), current_user=user)


@router.post("/rag/{rag_id}/conversion", response_class=HTMLResponse)
async def start_rag_conversion_view(
    rag_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    catalog: Catalog = Depends(get_catalog_dep),
    user: User = Depends(get_current_user),
    config: AppConfig = Depends(get_app_config),
    filesystem: FileSystem = Depends(get_filesystem),
    db: AsyncSession = Depends(get_db_session, scope="function"),
):
    """Start conversion and return its pollable status fragment."""
    task = await start_rag_operation(db, rag_id, user, "conversion")
    background_tasks.add_task(
        run_conversion_job, config.database, filesystem, task.id, rag_id
    )
    return catalog.render(
        "pages.rag.OperationStatus",
        rag_id=rag_id,
        operation="conversion",
        task=_task_view(task),
    )


@router.post("/rag/{rag_id}/index", response_class=HTMLResponse)
async def start_rag_indexing_view(
    rag_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    catalog: Catalog = Depends(get_catalog_dep),
    user: User = Depends(get_current_user),
    config: AppConfig = Depends(get_app_config),
    filesystem: FileSystem = Depends(get_filesystem),
    db: AsyncSession = Depends(get_db_session, scope="function"),
):
    """Start indexing and return its pollable status fragment."""
    task = await start_rag_operation(db, rag_id, user, "indexing")
    background_tasks.add_task(
        run_indexing_job, config.database, filesystem, task.id, rag_id
    )
    return catalog.render(
        "pages.rag.OperationStatus",
        rag_id=rag_id,
        operation="index",
        task=_task_view(task),
    )


@router.get("/rag/{rag_id}/{operation}/status", response_class=HTMLResponse)
async def poll_rag_operation_view(
    rag_id: uuid.UUID,
    operation: Literal["conversion", "index"],
    catalog: Catalog = Depends(get_catalog_dep),
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Poll conversion or indexing status as an HTML fragment."""
    service_operation = "indexing" if operation == "index" else "conversion"
    task = TaskResponse.model_validate(
        await poll_rag_operation(db, rag_id, user, service_operation)
    )
    html = catalog.render(
        "pages.rag.OperationStatus",
        rag_id=rag_id,
        operation=operation,
        task=task,
    )
    if operation == "conversion" and task.status == TaskStatus.SUCCESS:
        html += catalog.render(
            "pages.rag.IndexAction",
            rag_id=rag_id,
            is_converted=True,
            is_indexed=False,
            task=None,
            oob=True,
        )
    return html
