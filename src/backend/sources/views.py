import uuid

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status
from fastapi.responses import HTMLResponse
from jinjax.catalog import Catalog
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_current_user
from ..dependencies import get_catalog_dep, get_db_session
from ..files.schemas import FileResponse
from ..filesystem.base import FileSystem
from ..filesystem.dependencies import get_filesystem
from ..users.schemas import User
from .exception import SharedUserNotFoundException
from .models import SourceModel, SourceOrigin
from .schemas import SourceCreate, SourceResponse
from .service import (
    create_source,
    get_source,
    get_source_files,
    get_sources,
    upload_files_to_source,
)

router = APIRouter(tags=["source-views"])


def _to_response(source: SourceModel) -> SourceResponse:
    return SourceResponse.model_validate(source)


@router.get("/sources", response_class=HTMLResponse)
async def sources_page(
    origin: SourceOrigin = Query(SourceOrigin.USER),
    catalog: Catalog = Depends(get_catalog_dep),
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    sources, _ = await get_sources(
        db, user, page=1, page_size=100, include_files=True, origin=origin
    )
    return catalog.render(
        "pages.sources.SourceList",
        sources=[_to_response(source) for source in sources],
        origin=origin.value,
        current_user=user,
    )


@router.get("/sources/new", response_class=HTMLResponse)
async def new_source_dialog(
    catalog: Catalog = Depends(get_catalog_dep), _: User = Depends(get_current_user)
):
    return catalog.render("pages.sources.CreateDialog")


@router.post("/sources", response_class=HTMLResponse)
async def create_source_submit(
    data: SourceCreate,
    catalog: Catalog = Depends(get_catalog_dep),
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    try:
        await create_source(db, data, user)
    except SharedUserNotFoundException:
        return catalog.render(
            "pages.sources.CreateDialog",
            error="One or more shared users do not exist",
            name=data.name,
        )
    sources, _ = await get_sources(db, user, page=1, page_size=100, include_files=True)
    return catalog.render(
        "pages.sources.SourceGrid", sources=[_to_response(source) for source in sources]
    )


@router.get("/sources/{source_id}", response_class=HTMLResponse)
async def source_detail_page(
    source_id: uuid.UUID,
    catalog: Catalog = Depends(get_catalog_dep),
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    source = await get_source(db, source_id, user)
    files, has_more = await get_source_files(db, source_id, user, page=1, page_size=50)
    return catalog.render(
        "pages.sources.SourceDetail",
        source=_to_response(source),
        files=[FileResponse.model_validate(file) for file in files],
        has_more=has_more,
        current_user=user,
    )


@router.get("/sources/{source_id}/files", response_class=HTMLResponse)
async def source_files_view(
    source_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    catalog: Catalog = Depends(get_catalog_dep),
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    files, has_more = await get_source_files(db, source_id, user, page, page_size)
    return catalog.render(
        "pages.sources.FileRows",
        source_id=source_id,
        files=[FileResponse.model_validate(file) for file in files],
        page=page,
        page_size=page_size,
        has_more=has_more,
    )


@router.post("/sources/{source_id}/files", status_code=status.HTTP_204_NO_CONTENT)
async def upload_source_files_view(
    source_id: uuid.UUID,
    files: list[UploadFile] = File(...),
    file_ids: list[uuid.UUID] = Form(...),
    db: AsyncSession = Depends(get_db_session),
    filesystem: FileSystem = Depends(get_filesystem),
    user: User = Depends(get_current_user),
) -> Response:
    await upload_files_to_source(
        db,
        source_id,
        files,
        user,
        filesystem,
        include_existing_files=False,
        file_ids=file_ids,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
