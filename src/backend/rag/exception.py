from fastapi import HTTPException, status


class RagException(HTTPException):
    """ """

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Rag error.",
        )
