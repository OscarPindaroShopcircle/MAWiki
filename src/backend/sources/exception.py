import uuid

from fastapi import HTTPException, status


class SourceNotFoundException(HTTPException):
    def __init__(self, source_id: uuid.UUID):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source with id {source_id} not found",
        )


class SourceAccessDeniedException(HTTPException):
    def __init__(self, source_id: uuid.UUID):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"You do not have access to source {source_id}",
        )


class SystemSourceMutationException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="System-generated sources cannot be modified",
        )


class SharedUserNotFoundException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="One or more shared users do not exist",
        )


class SourceFileNotFoundException(HTTPException):
    def __init__(self, file_id: uuid.UUID):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File with id {file_id} not found in this source",
        )


class FileUploadException(HTTPException):
    def __init__(self, detail: str = "Unable to store one or more uploaded files"):
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
