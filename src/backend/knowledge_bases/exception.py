import uuid

from fastapi import HTTPException, status


class KnowledgeBaseNotFoundException(HTTPException):
    def __init__(self, knowledge_base_id: uuid.UUID):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Knowledge base with id {knowledge_base_id} not found",
        )


class KnowledgeBaseSourceFileNotFoundException(HTTPException):
    def __init__(self, file_id: uuid.UUID):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source file with id {file_id} not found in this knowledge base",
        )


class KnowledgeBaseOperationInProgressException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail="A conversion or indexing operation is already running",
        )


class KnowledgeBaseNotConvertedException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail="The knowledge base has not been converted",
        )


class KnowledgeBaseNotIndexedException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail="The knowledge base has not been indexed",
        )


class KnowledgeBaseOperationNotStartedException(HTTPException):
    def __init__(self, operation: str):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{operation.capitalize()} has not been started",
        )
