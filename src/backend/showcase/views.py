from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_optional_user
from ..dependencies import get_catalog_dep, get_db_session
from ..users.schemas import User
from ..users.service import get_all_users

router = APIRouter(tags=["showcase"])


@router.get("/components", response_class=HTMLResponse)
async def showcase(
    catalog=Depends(get_catalog_dep),
    db: AsyncSession = Depends(get_db_session),
    user: User | None = Depends(get_optional_user),
):
    """Component showcase — living style guide."""
    users = [User.model_validate(u) for u in await get_all_users(db)]
    return catalog.render(
        "pages.showcase.Showcase",
        users=users,
        current_user=user,
    )
