import uuid

from fastapi import HTTPException, status


class RagNotFoundException(HTTPException):
    def __init__(self, rag_id: uuid.UUID):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"RAG model with id {rag_id} not found",
        )


class RagOperationInProgressException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail="A conversion or indexing operation is already running",
        )


class RagNotConvertedException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail="The RAG model has not been converted",
        )


class RagNotIndexedException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail="The RAG model has not been indexed",
        )


class RagOperationNotStartedException(HTTPException):
    def __init__(self, operation: str):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{operation.capitalize()} has not been started",
        )
