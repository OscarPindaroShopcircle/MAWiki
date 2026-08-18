import uuid

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_current_user
from ..config import AppConfig, get_app_config
from ..dependencies import get_db_session
from ..schemas import PagedResponse
from ..users.schemas import User
from .models import KnowledgeBaseModel
from .schemas import KnowledgeBaseCreate, KnowledgeBaseResponse, KnowledgeBaseUpdate
from .service import (
    create_knowledge_base,
    delete_knowledge_base,
    get_knowledge_base,
    get_knowledge_bases,
    update_knowledge_base,
    upload_files_to_knowledge_base,
)


router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])


def _to_response(knowledge_base: KnowledgeBaseModel) -> KnowledgeBaseResponse:
    return KnowledgeBaseResponse.model_validate(knowledge_base)


@router.post(
    "/",
    response_model=KnowledgeBaseResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_knowledge_base_route(
    data: KnowledgeBaseCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> KnowledgeBaseResponse:
    knowledge_base = await create_knowledge_base(db, data, user)
    return _to_response(knowledge_base)


@router.get(
    "/",
    response_model=PagedResponse[KnowledgeBaseResponse],
)
async def list_knowledge_bases(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    include_files: bool = Query(False),
    include_shared_with: bool = Query(False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> PagedResponse[KnowledgeBaseResponse]:
    data, total = await get_knowledge_bases(
        db, user, page, page_size, include_files, include_shared_with
    )
    return PagedResponse(
        data=[_to_response(knowledge_base) for knowledge_base in data],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/{knowledge_base_id}/files",
    response_model=KnowledgeBaseResponse,
)
async def upload_knowledge_base_files(
    knowledge_base_id: uuid.UUID,
    files: list[UploadFile] = File(...),
    user: User = Depends(get_current_user),
    config: AppConfig = Depends(get_app_config),
    db: AsyncSession = Depends(get_db_session),
) -> KnowledgeBaseResponse:
    knowledge_base = await upload_files_to_knowledge_base(
        db, knowledge_base_id, files, user, config
    )
    return _to_response(knowledge_base)


@router.get(
    "/{knowledge_base_id}",
    response_model=KnowledgeBaseResponse,
)
async def get_knowledge_base_route(
    knowledge_base_id: uuid.UUID,
    include_files: bool = Query(False),
    include_shared_with: bool = Query(False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> KnowledgeBaseResponse:
    knowledge_base = await get_knowledge_base(
        db, knowledge_base_id, user, include_files, include_shared_with
    )
    return _to_response(knowledge_base)


@router.patch(
    "/{knowledge_base_id}",
    response_model=KnowledgeBaseResponse,
)
async def update_knowledge_base_route(
    knowledge_base_id: uuid.UUID,
    data: KnowledgeBaseUpdate,
    include_files: bool = Query(False),
    include_shared_with: bool = Query(False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> KnowledgeBaseResponse:
    knowledge_base = await update_knowledge_base(
        db,
        knowledge_base_id,
        data,
        user,
        include_files,
        include_shared_with,
    )
    return _to_response(knowledge_base)


@router.delete(
    "/{knowledge_base_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_knowledge_base_route(
    knowledge_base_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    await delete_knowledge_base(db, knowledge_base_id, user)
