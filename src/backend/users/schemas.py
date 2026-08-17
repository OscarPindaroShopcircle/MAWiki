from typing import Annotated

from pydantic import EmailStr, Field

from ..db.enums import UserRole
from ..schemas import AppBaseModel, TimestampMixin, UUIDField


class UserCreate(AppBaseModel):
    name: Annotated[
        str,
        Field(
            min_length=1,
            max_length=255,
            examples=["John Doe"],
            description="User's full name",
        ),
    ]
    email: Annotated[
        EmailStr,
        Field(
            examples=["john@example.com"],
            description="User's email address",
        ),
    ]


class User(AppBaseModel, TimestampMixin):
    id: Annotated[
        UUIDField, Field(examples=["01J5KQ3X-uuid-example"], description="User ID")
    ]
    name: Annotated[
        str,
        Field(
            min_length=1,
            max_length=255,
            examples=["John Doe"],
            description="User's full name",
        ),
    ]
    email: Annotated[
        EmailStr,
        Field(
            examples=["john@example.com"],
            description="User's email address",
        ),
    ]
    role: Annotated[
        UserRole,
        Field(default=UserRole.MEMBER, description="User role"),
    ]
    is_active: Annotated[
        bool, Field(default=True, description="Whether the user is active")
    ]


class UserResponse(AppBaseModel, TimestampMixin):
    id: Annotated[
        UUIDField, Field(examples=["01J5KQ3X-uuid-example"], description="User ID")
    ]
    name: Annotated[
        str,
        Field(
            min_length=1,
            max_length=255,
            examples=["John Doe"],
            description="User's full name",
        ),
    ]
    email: Annotated[
        EmailStr,
        Field(
            examples=["john@example.com"],
            description="User's email address",
        ),
    ]
    role: Annotated[
        UserRole,
        Field(default=UserRole.MEMBER, description="User role"),
    ]
    is_active: Annotated[
        bool, Field(default=True, description="Whether the user is active")
    ]


class UserUpdate(AppBaseModel):
    name: Annotated[
        str,
        Field(
            min_length=1,
            max_length=255,
            examples=["Jane Smith"],
            description="Updated user name",
        ),
    ]


class UserDelete(AppBaseModel):
    pass
