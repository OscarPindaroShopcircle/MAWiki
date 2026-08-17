from datetime import datetime
from typing import Annotated, Optional

from pydantic import ConfigDict, Field

from ..db.enums import UserRole
from ..schemas import AppBaseModelStripped, UUIDField


class TokenResponse(AppBaseModelStripped):
    """JWT access + refresh token pair returned after login or refresh.

    Overrides the camelCase alias generator so the JSON keys are snake_case
    (``access_token``, ``refresh_token``, ``token_type``) — the frontend JS
    and htmx interceptor read these exact keys from the response body.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        validate_default=True,
        validate_assignment=True,
        use_enum_values=True,
        str_strip_whitespace=True,
        from_attributes=True,
        alias_generator=None,
    )

    access_token: Annotated[str, Field(description="Short-lived JWT access token")]
    refresh_token: Annotated[str, Field(description="Long-lived JWT refresh token")]
    token_type: Annotated[str, Field(default="bearer", description="Token type")]


class RefreshRequest(AppBaseModelStripped):
    """Request body for ``POST /auth/refresh``."""

    refresh_token: Annotated[str, Field(description="A valid refresh token")]


class LoginRequest(AppBaseModelStripped):
    """Request body for ``POST /auth/login`` (password-based)."""

    email: Annotated[str, Field(description="User email address")]
    password: Annotated[str, Field(description="User password")]


class RegisterRequest(AppBaseModelStripped):
    """Request body for ``POST /auth/register`` (password-based).

    Registration is gated by a pending invitation or the bootstrap admin
    email — no open self-registration.
    """

    name: Annotated[
        str,
        Field(min_length=1, max_length=255, description="User's display name"),
    ]
    email: Annotated[str, Field(description="User email address")]
    password: Annotated[
        str,
        Field(min_length=8, description="User password (min 8 chars)"),
    ]


class InvitationCreate(AppBaseModelStripped):
    """Input for creating an invitation."""

    email: Annotated[str, Field(description="Email address to invite")]
    role: Annotated[
        UserRole,
        Field(default=UserRole.MEMBER, description="Role to assign"),
    ]


class InvitationResponse(AppBaseModelStripped):
    """API response for an invitation."""

    id: Annotated[int, Field(description="Invitation ID")]
    email: Annotated[str, Field(description="Invited email address")]
    role: Annotated[UserRole, Field(description="Role assigned to the invitee")]
    invited_by: Annotated[UUIDField, Field(description="User ID of the inviter")]
    created_at: Annotated[
        datetime, Field(description="When the invitation was created")
    ]
    accepted_at: Annotated[
        Optional[datetime],
        Field(description="When the invitation was accepted, if ever"),
    ]
    expires_at: Annotated[datetime, Field(description="When the invitation expires")]


class InvitationView(AppBaseModelStripped):
    """View-layer invitation — includes the inviter's display name."""

    id: Annotated[int, Field(description="Invitation ID")]
    email: Annotated[str, Field(description="Invited email address")]
    role: Annotated[UserRole, Field(description="Role assigned to the invitee")]
    invited_by_name: Annotated[str, Field(description="Name of the inviter")]
    expires_at: Annotated[datetime, Field(description="When the invitation expires")]
    accepted_at: Annotated[
        Optional[datetime],
        Field(description="When the invitation was accepted, if ever"),
    ]
    is_expired: Annotated[
        bool, Field(default=False, description="Whether the invitation has expired")
    ]


class InvitationCreateResponse(AppBaseModelStripped):
    """Response for ``POST /api/invitations`` — invitation plus the login link."""

    invitation: Annotated[
        InvitationResponse, Field(description="The created invitation")
    ]
    invite_link: Annotated[str, Field(description="Login link for the invitee")]
