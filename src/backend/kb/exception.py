import uuid

from fastapi import HTTPException, status


class KnowledgeBaseNotFoundException(HTTPException):
    def __init__(self, knowledge_base_id: uuid.UUID):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Knowledge base with id {knowledge_base_id} not found",
        )


class KnowledgeBaseAccessDeniedException(HTTPException):
    def __init__(self, knowledge_base_id: uuid.UUID):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"You do not have access to knowledge base {knowledge_base_id}",
        )


class SharedUserNotFoundException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="One or more shared users do not exist",
        )


class FileUploadException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to store one or more uploaded files",
        )
