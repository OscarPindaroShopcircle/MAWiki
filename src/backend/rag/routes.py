import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_current_user
from ..dependencies import get_db_session
from ..schemas import PagedResponse
from ..users.schemas import User
from .models import RagModel
from .schemas import RagCreate, RagResponse, RagUpdate
from .service import (
    create_rag_model,
    delete_rag_model,
    get_rag_model,
    get_rag_models,
    update_rag_model,
)


router = APIRouter(prefix="/api/rag-models", tags=["rag-models"])


# take inspiration from the routes in kb
def _to_response(rag: RagModel) -> RagResponse:
    return RagResponse.model_validate(rag)


@router.post("/", response_model=RagResponse, status_code=status.HTTP_201_CREATED)
async def create_rag_model_route(
    data: RagCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> RagResponse:
    return _to_response(await create_rag_model(db, data, user))


@router.get("/", response_model=PagedResponse[RagResponse])
async def list_rag_models(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> PagedResponse[RagResponse]:
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
    return _to_response(await get_rag_model(db, rag_id, user))


@router.patch("/{rag_id}", response_model=RagResponse)
async def update_rag_model_route(
    rag_id: uuid.UUID,
    data: RagUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> RagResponse:
    return _to_response(await update_rag_model(db, rag_id, data, user))


@router.delete("/{rag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rag_model_route(
    rag_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    await delete_rag_model(db, rag_id, user)


# convert all the files that it can into a textual representation.
# converrsion gets a knowledge base and creates a NEW knowledge base that contains the converted files.#
# some files can not be converted, generally for two reasons:
# 1. file not supported by the pipeline
# 2. conversion failed. it should be clear.
# this knowledge base will be linked automatically to this model, i guess with a converted_kb
# conversion are something that is pooled, done with an asyncio gather (very blocking)
# therefore use a Task, and keep the status. a convertion can be triggered to finish with the missing files
# can also be forcefully retriggered to recompute everything
# in src/ai there is an indexing pipeline that does conversion + indexing. let's create two other components
# one for conversion and one for indexing,

# indexing is a Task and therefore needs to be pooled
# for now let's do something simple with faiss. use a smal static model model2vec/ whatever. probaly in ma_wiki, my prototype, there is already a draft of this
# keep in mind that that was a super hasty prototype, but contains all the ideas

# search uses FAISS for now
# for now no bm25, just for ease of use
