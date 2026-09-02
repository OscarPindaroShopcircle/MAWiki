from typing import Annotated

from pydantic import Field

from ..files.schemas import FileResponse
from ..schemas import AppBaseModel, TimestampMixin, UUIDField
from ..users.schemas import UserResponse
from .models import SourceOrigin


class SourceCreate(AppBaseModel):
    name: Annotated[
        str,
        Field(
            min_length=1,
            max_length=255,
            examples=["Engineering Docs"],
            description="Data source name",
        ),
    ]
    shared_with: Annotated[
        list[UUIDField],
        Field(
            default_factory=list,
            examples=[["01J5KQ3X-user-example"]],
            description="User IDs allowed to view the data source",
        ),
    ]


class SourceUpdate(AppBaseModel):
    name: Annotated[
        str | None,
        Field(
            default=None,
            min_length=1,
            max_length=255,
            examples=["Updated Engineering Docs"],
            description="Replacement data source name",
        ),
    ]
    shared_with: Annotated[
        list[UUIDField] | None,
        Field(
            default=None,
            examples=[["01J5KQ3X-user-example"]],
            description="Replacement list of user IDs allowed to view",
        ),
    ]


class SourceResponse(AppBaseModel, TimestampMixin):
    id: Annotated[
        UUIDField,
        Field(
            description="Data source ID",
            examples=["01J5KQ3X-source-example"],
        ),
    ]
    name: Annotated[
        str,
        Field(
            max_length=255,
            examples=["Engineering Docs"],
            description="Data source name",
        ),
    ]
    origin: Annotated[
        SourceOrigin,
        Field(description="Whether the source was created by a user or the system"),
    ]
    created_by: Annotated[
        UserResponse,
        Field(description="User who owns the data source"),
    ]
    files: Annotated[
        list[FileResponse] | None,
        Field(
            default=None,
            description="Files in the data source, when requested",
        ),
    ]
    shared_with: Annotated[
        list[UserResponse] | None,
        Field(
            default=None,
            description="Users allowed to view the data source, when requested",
        ),
    ]
