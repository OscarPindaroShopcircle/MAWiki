from fastapi import APIRouter


router = APIRouter(prefix="/rag", tags=["rag"])


@router.get("/sample")
async def rag_sample() -> dict[str, str]:
    """ """
    return {"status": "ok"}
