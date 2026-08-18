from fastapi import APIRouter
from fastapi.responses import HTMLResponse


router = APIRouter(tags=["kb-views"])


@router.get("/kb", response_class=HTMLResponse)
async def kb_page() -> str:
    """ """
    return "<h1>Kb</h1>"
