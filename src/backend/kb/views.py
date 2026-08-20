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
from .models import KnowledgeBaseModel
from .schemas import KnowledgeBaseCreate, KnowledgeBaseResponse
from .service import (
    create_knowledge_base,
    get_knowledge_base,
    get_knowledge_base_files,
    get_knowledge_bases,
    upload_files_to_knowledge_base,
)

router = APIRouter(tags=["kb-views"])


def _to_response(knowledge_base: KnowledgeBaseModel) -> KnowledgeBaseResponse:
    return KnowledgeBaseResponse.model_validate(knowledge_base)


@router.get("/knowledge-bases", response_class=HTMLResponse)
async def knowledge_bases_page(
    catalog: Catalog = Depends(get_catalog_dep),
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Knowledge bases list page — cards for every KB visible to the user."""
    knowledge_bases, _ = await get_knowledge_bases(
        db, user, page=1, page_size=100, include_files=True
    )
    return catalog.render(
        "pages.kb.KnowledgeBaseList",
        knowledge_bases=[
            _to_response(knowledge_base) for knowledge_base in knowledge_bases
        ],
        current_user=user,
    )


@router.get("/knowledge-bases/new", response_class=HTMLResponse)
async def new_knowledge_base_dialog(
    catalog: Catalog = Depends(get_catalog_dep),
    _: User = Depends(get_current_user),
):
    """Return the create-knowledge-base dialog — loaded by htmx into the page."""
    return catalog.render("pages.kb.CreateDialog")


@router.post("/knowledge-bases", response_class=HTMLResponse)
async def create_knowledge_base_submit(
    data: KnowledgeBaseCreate,
    catalog: Catalog = Depends(get_catalog_dep),
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Create a knowledge base via htmx JSON submit, then return the refreshed grid."""
    try:
        await create_knowledge_base(db, data, user)
    except SharedUserNotFoundException:
        return catalog.render(
            "pages.kb.CreateDialog",
            error="One or more shared users do not exist",
            name=data.name,
        )

    knowledge_bases, _ = await get_knowledge_bases(
        db, user, page=1, page_size=100, include_files=True
    )
    return catalog.render(
        "pages.kb.KnowledgeBaseGrid",
        knowledge_bases=[
            _to_response(knowledge_base) for knowledge_base in knowledge_bases
        ],
    )


@router.get("/knowledge-bases/{knowledge_base_id}", response_class=HTMLResponse)
async def knowledge_base_detail_page(
    knowledge_base_id: uuid.UUID,
    catalog: Catalog = Depends(get_catalog_dep),
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Knowledge base detail page — file list and upload entry point."""
    knowledge_base = await get_knowledge_base(db, knowledge_base_id, user)
    files, has_more = await get_knowledge_base_files(
        db, knowledge_base_id, user, page=1, page_size=50
    )
    return catalog.render(
        "pages.kb.KnowledgeBaseDetail",
        knowledge_base=_to_response(knowledge_base),
        files=[FileResponse.model_validate(file) for file in files],
        has_more=has_more,
        current_user=user,
    )


@router.get("/knowledge-bases/{knowledge_base_id}/files", response_class=HTMLResponse)
async def knowledge_base_files_view(
    knowledge_base_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    catalog: Catalog = Depends(get_catalog_dep),
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    files, has_more = await get_knowledge_base_files(
        db, knowledge_base_id, user, page, page_size
    )
    return catalog.render(
        "pages.kb.FileRows",
        knowledge_base_id=knowledge_base_id,
        files=[FileResponse.model_validate(file) for file in files],
        page=page,
        page_size=page_size,
        has_more=has_more,
    )


@router.post(
    "/knowledge-bases/{knowledge_base_id}/files",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def upload_knowledge_base_files_view(
    knowledge_base_id: uuid.UUID,
    files: list[UploadFile] = File(...),
    file_ids: list[uuid.UUID] = Form(...),
    db: AsyncSession = Depends(get_db_session),
    filesystem: FileSystem = Depends(get_filesystem),
    user: User = Depends(get_current_user),
) -> Response:
    """Upload one file batch without rendering the file table."""
    await upload_files_to_knowledge_base(
        db,
        knowledge_base_id,
        files,
        user,
        filesystem,
        include_existing_files=False,
        file_ids=file_ids,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
