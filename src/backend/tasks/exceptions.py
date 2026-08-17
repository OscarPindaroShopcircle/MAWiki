import uuid

from fastapi import HTTPException, status


class TaskNotFound(HTTPException):
    def __init__(self, task_id: uuid.UUID):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with id {task_id} not found",
        )
