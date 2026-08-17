from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import AppConfig, get_app_config
from ...dependencies import get_db_session
from ...schemas import ListResponse
from ...users.schemas import User
from ..dependencies import get_current_admin_user
from ..schemas import InvitationCreate, InvitationCreateResponse, InvitationResponse
from ..service import (
    create_invitation as create_invitation_service,
    get_all_invitations,
    revoke_invitation as revoke_invitation_service,
)

router = APIRouter(
    prefix="/api/invitations",
    tags=["invitations"],
    dependencies=[Depends(get_current_admin_user)],
)


def _to_response(invitation) -> InvitationResponse:
    return InvitationResponse(
        id=invitation.id,
        email=invitation.email,
        role=invitation.role,
        invited_by=invitation.invited_by,
        created_at=invitation.created_at,
        accepted_at=invitation.accepted_at,
        expires_at=invitation.expires_at,
    )


@router.post(
    "/",
    response_model=InvitationCreateResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "Invitation successfully created"},
        409: {"description": "An invitation for this email already exists"},
    },
)
async def create_invitation(
    body: InvitationCreate,
    db: AsyncSession = Depends(get_db_session),
    config: AppConfig = Depends(get_app_config),
    admin: User = Depends(get_current_admin_user),
):
    """Invite a user by email. Returns the invitation and the login link."""
    expire_days = config.auth.invitation_expire_days if config.auth else 7
    invitation = await create_invitation_service(
        db, body, admin.id, expire_days=expire_days
    )
    return InvitationCreateResponse(
        invitation=_to_response(invitation),
        invite_link="/auth/login",
    )


@router.get(
    "/",
    response_model=ListResponse[InvitationResponse],
    responses={
        200: {"description": "List of all invitations returned"},
    },
)
async def list_invitations(
    db: AsyncSession = Depends(get_db_session),
    admin: User = Depends(get_current_admin_user),
):
    """List all invitations (pending and accepted)."""
    invitations = await get_all_invitations(db)
    return ListResponse(data=[_to_response(i) for i in invitations])


@router.delete(
    "/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        204: {"description": "Invitation successfully revoked"},
        404: {"description": "Invitation not found"},
    },
)
async def revoke_invitation(
    invitation_id: int,
    db: AsyncSession = Depends(get_db_session),
    admin: User = Depends(get_current_admin_user),
):
    """Revoke (delete) an invitation by ID."""
    await revoke_invitation_service(db, invitation_id)
