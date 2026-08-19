import uuid

from fastapi import HTTPException, status


class RagNotFoundException(HTTPException):
    def __init__(self, rag_id: uuid.UUID):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"RAG model with id {rag_id} not found",
        )
