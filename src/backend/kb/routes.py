from fastapi import APIRouter


router = APIRouter(prefix="/kb", tags=["kb"])


@router.get("/sample")
async def kb_sample() -> dict[str, str]:
    """ """
    return {"status": "ok"}
