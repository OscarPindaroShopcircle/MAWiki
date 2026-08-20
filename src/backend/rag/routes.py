import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_current_user
from ..config import AppConfig, get_app_config
from ..dependencies import get_db_session
from ..filesystem.base import FileSystem
from ..filesystem.dependencies import get_filesystem
from ..schemas import PagedResponse
from ..tasks.schemas import TaskResponse
from ..users.schemas import User
from .models import RagModel
from .schemas import (
    RagCreate,
    RagResponse,
    RagSearchRequest,
    RagSearchResponse,
    RagUpdate,
)
from .service import (
    create_rag_model,
    delete_rag_model,
    get_rag_model,
    get_rag_models,
    poll_rag_operation,
    run_conversion_job,
    run_indexing_job,
    search_rag_model,
    start_rag_operation,
    update_rag_model,
)


router = APIRouter(prefix="/api/rag-models", tags=["rag-models"])


def _to_response(rag: RagModel) -> RagResponse:
    return RagResponse.model_validate(rag)


@router.post("/", response_model=RagResponse, status_code=status.HTTP_201_CREATED)
async def create_rag_model_route(
    data: RagCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> RagResponse:
    """Create a RAG model for a knowledge base owned by the current user."""
    return _to_response(await create_rag_model(db, data, user))


@router.get("/", response_model=PagedResponse[RagResponse])
async def list_rag_models(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> PagedResponse[RagResponse]:
    """List RAG models visible to the current user."""
    data, total = await get_rag_models(db, user, page, page_size)
    return PagedResponse(
        data=[_to_response(rag) for rag in data],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{rag_id}", response_model=RagResponse)
async def get_rag_model_route(
    rag_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> RagResponse:
    """Return one RAG model visible to the current user."""
    return _to_response(await get_rag_model(db, rag_id, user))


@router.patch("/{rag_id}", response_model=RagResponse)
async def update_rag_model_route(
    rag_id: uuid.UUID,
    data: RagUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> RagResponse:
    """Rename a RAG model owned by the current user."""
    return _to_response(await update_rag_model(db, rag_id, data, user))


@router.delete("/{rag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rag_model_route(
    rag_id: uuid.UUID,
    user: User = Depends(get_current_user),
    filesystem: FileSystem = Depends(get_filesystem),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """Delete a RAG model without deleting either knowledge base."""
    await delete_rag_model(db, rag_id, user, filesystem)


@router.post(
    "/{rag_id}/conversion",
    response_model=TaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_rag_conversion(
    rag_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    config: AppConfig = Depends(get_app_config),
    filesystem: FileSystem = Depends(get_filesystem),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> TaskResponse:
    """Start conversion in the background and return a pollable task.

    Every run converts all supported source files into text. A successful rerun
    replaces the converted knowledge base's previous files and invalidates its
    FAISS index; unsupported and failed filenames are reported in the task.
    """
    task = await start_rag_operation(db, rag_id, user, "conversion")
    background_tasks.add_task(
        run_conversion_job, config.database, filesystem, task.id, rag_id
    )
    return TaskResponse.model_validate(task)


@router.get("/{rag_id}/conversion", response_model=TaskResponse)
async def poll_rag_conversion(
    rag_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> TaskResponse:
    """Poll the latest conversion task for a RAG model."""
    return TaskResponse.model_validate(
        await poll_rag_operation(db, rag_id, user, "conversion")
    )


@router.post(
    "/{rag_id}/index",
    response_model=TaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_rag_indexing(
    rag_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    config: AppConfig = Depends(get_app_config),
    filesystem: FileSystem = Depends(get_filesystem),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> TaskResponse:
    """Build a FAISS index in the background and return a pollable task.

    Text files in the converted knowledge base are split, embedded with the
    fixed Model2Vec model, and stored through Haystack's FAISS document store
    as one replaceable artifact. Conversion must complete before indexing.
    """
    task = await start_rag_operation(db, rag_id, user, "indexing")
    background_tasks.add_task(
        run_indexing_job, config.database, filesystem, task.id, rag_id
    )
    return TaskResponse.model_validate(task)


@router.get("/{rag_id}/index", response_model=TaskResponse)
async def poll_rag_indexing(
    rag_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> TaskResponse:
    """Poll the latest indexing task for a RAG model."""
    return TaskResponse.model_validate(
        await poll_rag_operation(db, rag_id, user, "indexing")
    )


@router.post("/{rag_id}/search", response_model=RagSearchResponse)
async def search_rag_model_route(
    rag_id: uuid.UUID,
    data: RagSearchRequest,
    user: User = Depends(get_current_user),
    filesystem: FileSystem = Depends(get_filesystem),
    db: AsyncSession = Depends(get_db_session),
) -> RagSearchResponse:
    """Search the persisted Haystack FAISS document store.

    The query uses the same fixed Model2Vec model as indexing and returns the
    best matching text chunks with scores and converted-file provenance. The
    model must be converted and indexed before it can be searched.
    """
    await get_rag_model(db, rag_id, user)
    return RagSearchResponse(
        results=await search_rag_model(db, rag_id, data, filesystem)
    )
