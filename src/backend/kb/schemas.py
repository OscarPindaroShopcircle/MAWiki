from typing import Annotated

from pydantic import Field

from ..files.schemas import FileResponse
from ..schemas import AppBaseModel, TimestampMixin, UUIDField
from ..users.schemas import UserResponse


class KnowledgeBaseCreate(AppBaseModel):
    name: Annotated[
        str,
        Field(
            min_length=1,
            max_length=255,
            examples=["Engineering Docs"],
            description="Knowledge base name",
        ),
    ]
    shared_with: Annotated[
        list[UUIDField],
        Field(
            default_factory=list,
            examples=[["01J5KQ3X-user-example"]],
            description="User IDs allowed to view the knowledge base",
        ),
    ]


class KnowledgeBaseUpdate(AppBaseModel):
    name: Annotated[
        str | None,
        Field(
            default=None,
            min_length=1,
            max_length=255,
            examples=["Updated Engineering Docs"],
            description="New knowledge base name",
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


class KnowledgeBaseResponse(AppBaseModel, TimestampMixin):
    id: Annotated[
        UUIDField,
        Field(
            description="Knowledge base ID",
            examples=["01J5KQ3X-kb-example"],
        ),
    ]
    name: Annotated[
        str,
        Field(
            max_length=255,
            examples=["Engineering Docs"],
            description="Knowledge base name",
        ),
    ]
    created_by: Annotated[
        UserResponse,
        Field(description="User who created the knowledge base"),
    ]
    files: Annotated[
        list[FileResponse] | None,
        Field(
            default=None,
            description="Files in the knowledge base, when requested",
        ),
    ]
    shared_with: Annotated[
        list[UserResponse] | None,
        Field(
            default=None,
            description="Users allowed to view the knowledge base, when requested",
        ),
    ]
