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
from .models import KnowledgeBaseModel
from .schemas import (
    KnowledgeBaseCreate,
    KnowledgeBaseResponse,
    KnowledgeBaseSearchRequest,
    KnowledgeBaseSearchResponse,
    KnowledgeBaseUpdate,
)
from .service import (
    create_knowledge_base,
    delete_knowledge_base,
    get_knowledge_base,
    get_knowledge_bases,
    poll_knowledge_base_operation,
    run_conversion_job,
    run_indexing_job,
    search_knowledge_base,
    start_knowledge_base_operation,
    update_knowledge_base,
)

router = APIRouter(prefix="/api/knowledge-bases", tags=["knowledge-bases"])


def _to_response(knowledge_base: KnowledgeBaseModel) -> KnowledgeBaseResponse:
    return KnowledgeBaseResponse.model_validate(knowledge_base)


@router.post(
    "/", response_model=KnowledgeBaseResponse, status_code=status.HTTP_201_CREATED
)
async def create_knowledge_base_route(
    data: KnowledgeBaseCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> KnowledgeBaseResponse:
    return _to_response(await create_knowledge_base(db, data, user))


@router.get("/", response_model=PagedResponse[KnowledgeBaseResponse])
async def list_knowledge_bases(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> PagedResponse[KnowledgeBaseResponse]:
    data, total = await get_knowledge_bases(db, user, page, page_size)
    return PagedResponse(
        data=[_to_response(knowledge_base) for knowledge_base in data],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{knowledge_base_id}", response_model=KnowledgeBaseResponse)
async def get_knowledge_base_route(
    knowledge_base_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> KnowledgeBaseResponse:
    return _to_response(await get_knowledge_base(db, knowledge_base_id, user))


@router.patch("/{knowledge_base_id}", response_model=KnowledgeBaseResponse)
async def update_knowledge_base_route(
    knowledge_base_id: uuid.UUID,
    data: KnowledgeBaseUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> KnowledgeBaseResponse:
    return _to_response(await update_knowledge_base(db, knowledge_base_id, data, user))


@router.delete("/{knowledge_base_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_knowledge_base_route(
    knowledge_base_id: uuid.UUID,
    user: User = Depends(get_current_user),
    filesystem: FileSystem = Depends(get_filesystem),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    await delete_knowledge_base(db, knowledge_base_id, user, filesystem)


@router.post(
    "/{knowledge_base_id}/conversion",
    response_model=TaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_knowledge_base_conversion(
    knowledge_base_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    config: AppConfig = Depends(get_app_config),
    filesystem: FileSystem = Depends(get_filesystem),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> TaskResponse:
    task = await start_knowledge_base_operation(
        db, knowledge_base_id, user, "conversion"
    )
    background_tasks.add_task(
        run_conversion_job, config.database, filesystem, task.id, knowledge_base_id
    )
    return TaskResponse.model_validate(task)


@router.get("/{knowledge_base_id}/conversion", response_model=TaskResponse)
async def poll_knowledge_base_conversion(
    knowledge_base_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> TaskResponse:
    return TaskResponse.model_validate(
        await poll_knowledge_base_operation(db, knowledge_base_id, user, "conversion")
    )


@router.post(
    "/{knowledge_base_id}/index",
    response_model=TaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_knowledge_base_indexing(
    knowledge_base_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    config: AppConfig = Depends(get_app_config),
    filesystem: FileSystem = Depends(get_filesystem),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> TaskResponse:
    task = await start_knowledge_base_operation(db, knowledge_base_id, user, "indexing")
    background_tasks.add_task(
        run_indexing_job, config.database, filesystem, task.id, knowledge_base_id
    )
    return TaskResponse.model_validate(task)


@router.get("/{knowledge_base_id}/index", response_model=TaskResponse)
async def poll_knowledge_base_indexing(
    knowledge_base_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> TaskResponse:
    return TaskResponse.model_validate(
        await poll_knowledge_base_operation(db, knowledge_base_id, user, "indexing")
    )


@router.post("/{knowledge_base_id}/search", response_model=KnowledgeBaseSearchResponse)
async def search_knowledge_base_route(
    knowledge_base_id: uuid.UUID,
    data: KnowledgeBaseSearchRequest,
    user: User = Depends(get_current_user),
    filesystem: FileSystem = Depends(get_filesystem),
    db: AsyncSession = Depends(get_db_session),
) -> KnowledgeBaseSearchResponse:
    await get_knowledge_base(db, knowledge_base_id, user)
    return KnowledgeBaseSearchResponse(
        results=await search_knowledge_base(db, knowledge_base_id, data, filesystem)
    )
