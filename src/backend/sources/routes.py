import mimetypes
import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_current_user
from ..dependencies import get_db_session
from ..filesystem.base import FileSystem
from ..filesystem.dependencies import get_filesystem
from ..schemas import PagedResponse
from ..users.schemas import User
from .models import SourceModel, SourceOrigin
from .schemas import SourceCreate, SourceResponse, SourceUpdate
from .service import (
    create_source,
    delete_source,
    get_source,
    get_sources,
    read_source_file,
    update_source,
    upload_files_to_source,
)

router = APIRouter(prefix="/api/sources", tags=["sources"])


def _to_response(source: SourceModel) -> SourceResponse:
    return SourceResponse.model_validate(source)


@router.post("/", response_model=SourceResponse, status_code=status.HTTP_201_CREATED)
async def create_source_route(
    data: SourceCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SourceResponse:
    return _to_response(await create_source(db, data, user))


@router.get("/", response_model=PagedResponse[SourceResponse])
async def list_sources(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    include_files: bool = Query(False),
    include_shared_with: bool = Query(False),
    origin: SourceOrigin = Query(SourceOrigin.USER),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> PagedResponse[SourceResponse]:
    data, total = await get_sources(
        db, user, page, page_size, include_files, include_shared_with, origin
    )
    return PagedResponse(
        data=[_to_response(source) for source in data],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/{source_id}/files", response_model=SourceResponse)
async def upload_source_files(
    source_id: uuid.UUID,
    files: list[UploadFile] = File(...),
    user: User = Depends(get_current_user),
    filesystem: FileSystem = Depends(get_filesystem),
    db: AsyncSession = Depends(get_db_session),
) -> SourceResponse:
    return _to_response(
        await upload_files_to_source(db, source_id, files, user, filesystem)
    )


@router.get("/{source_id}/files/{file_id}/download", response_class=Response)
async def download_source_file(
    source_id: uuid.UUID,
    file_id: uuid.UUID,
    user: User = Depends(get_current_user),
    filesystem: FileSystem = Depends(get_filesystem),
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    file, content = await read_source_file(db, source_id, file_id, user, filesystem)
    media_type = file.mime_type or mimetypes.guess_type(file.name)[0]
    return Response(
        content,
        media_type=media_type or "application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(file.name, safe='')}",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{source_id}", response_model=SourceResponse)
async def get_source_route(
    source_id: uuid.UUID,
    include_files: bool = Query(False),
    include_shared_with: bool = Query(False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SourceResponse:
    return _to_response(
        await get_source(db, source_id, user, include_files, include_shared_with)
    )


@router.patch("/{source_id}", response_model=SourceResponse)
async def update_source_route(
    source_id: uuid.UUID,
    data: SourceUpdate,
    include_files: bool = Query(False),
    include_shared_with: bool = Query(False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SourceResponse:
    return _to_response(
        await update_source(
            db, source_id, data, user, include_files, include_shared_with
        )
    )


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source_route(
    source_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    await delete_source(db, source_id, user)
