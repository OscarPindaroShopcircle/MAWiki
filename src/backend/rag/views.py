from fastapi import APIRouter
from fastapi.responses import HTMLResponse


router = APIRouter(tags=["rag-views"])


@router.get("/rag", response_class=HTMLResponse)
async def rag_page() -> str:
    """ """
    return "<h1>Rag</h1>"
