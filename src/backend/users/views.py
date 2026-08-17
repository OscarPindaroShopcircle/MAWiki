from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_current_admin_user
from ..auth.exceptions import InvitationAlreadyExists, InvitationNotFound
from ..auth.schemas import InvitationCreate, InvitationView
from ..auth.service import (
    create_invitation as create_invitation_service,
    get_all_invitations,
    get_invitation,
    get_invitation_by_email,
    revoke_invitation as revoke_invitation_service,
)
from ..config import AppConfig, get_app_config
from ..dependencies import get_catalog_dep, get_db_session
from ..db.enums import UserRole
from ..users.schemas import User
from ..users.service import get_all_users, get_user

router = APIRouter(tags=["users-views"])


def _available_roles() -> list[dict]:
    return [{"value": r.value, "label": r.value.capitalize()} for r in UserRole]


async def _build_invitations(db: AsyncSession) -> list[InvitationView]:
    """Fetch all invitations with inviter names — shared by page + htmx routes."""
    now = datetime.now(UTC)
    invitations_raw = await get_all_invitations(db)
    invitations = []
    for inv in invitations_raw:
        inviter = await get_user(db, inv.invited_by)
        invitations.append(
            InvitationView(
                id=inv.id,
                email=inv.email,
                role=inv.role,
                invited_by_name=inviter.name if inviter else "Unknown",
                expires_at=inv.expires_at,
                accepted_at=inv.accepted_at,
                is_expired=inv.accepted_at is None and inv.expires_at <= now,
            )
        )
    return invitations


@router.get("/admin/users", response_class=HTMLResponse)
async def admin_users(
    catalog=Depends(get_catalog_dep),
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_admin_user),
):
    """Admin users page — users and invitations from DB."""
    users = [User.model_validate(u) for u in await get_all_users(db)]
    invitations = await _build_invitations(db)

    return catalog.render(
        "pages.admin.AdminDashboard",
        users=users,
        invitations=invitations,
        current_user=user,
    )


@router.get("/admin/users/invite", response_class=HTMLResponse)
async def invite_user_form(
    catalog=Depends(get_catalog_dep),
    user: User = Depends(get_current_admin_user),
):
    """Return the invite-user dialog — loaded by htmx into the page."""
    return catalog.render(
        "pages.admin.InviteDialog", current_user=user, roles=_available_roles()
    )


@router.post("/admin/users/invite", response_class=HTMLResponse)
async def invite_user_submit(
    body: InvitationCreate,
    catalog=Depends(get_catalog_dep),
    db: AsyncSession = Depends(get_db_session),
    config: AppConfig = Depends(get_app_config),
    user: User = Depends(get_current_admin_user),
):
    """Create an invitation via htmx JSON submit.

    On success, returns the updated invitations table so htmx can
    swap it in place. On conflict (already invited), returns the
    dialog again with an error alert.
    """
    expire_days = config.auth.invitation_expire_days if config.auth else 7
    try:
        await create_invitation_service(
            db,
            body,
            user.id,
            expire_days=expire_days,
        )
    except InvitationAlreadyExists:
        return catalog.render(
            "pages.admin.InviteDialog",
            current_user=user,
            roles=_available_roles(),
            error=f"An invitation for {body.email} already exists",
            email=body.email,
            role=body.role,
        )

    invitations = await _build_invitations(db)
    return catalog.render(
        "pages.admin.InvitationsTable",
        invitations=invitations,
    )


@router.get(
    "/admin/users/invitations/{invitation_id}/revoke", response_class=HTMLResponse
)
async def revoke_invitation_confirm(
    invitation_id: int,
    catalog=Depends(get_catalog_dep),
    db: AsyncSession = Depends(get_db_session),
    _: User = Depends(get_current_admin_user),
):
    """Return a confirm dialog for revoking an invitation."""
    invitation = await get_invitation(db, invitation_id)
    if invitation is None:
        raise HTTPException(status_code=404, detail="Invitation not found")
    return catalog.render(
        "common.ConfirmDialog",
        title="Revoke invitation",
        message=f"Revoke the invitation for {invitation.email}? They will no longer be able to register.",
        confirm_label="Revoke",
        cancel_label="Cancel",
        confirm_variant="danger",
        hx_delete=f"/admin/users/invitations/{invitation_id}",
    )


@router.delete("/admin/users/invitations/{invitation_id}", response_class=HTMLResponse)
async def revoke_invitation(
    invitation_id: int,
    catalog=Depends(get_catalog_dep),
    db: AsyncSession = Depends(get_db_session),
    _: User = Depends(get_current_admin_user),
):
    """Revoke (delete) an invitation via htmx — returns the updated table."""
    try:
        await revoke_invitation_service(db, invitation_id)
    except InvitationNotFound:
        raise HTTPException(status_code=404, detail="Invitation not found")

    invitations = await _build_invitations(db)
    return catalog.render(
        "pages.admin.InvitationsTable",
        invitations=invitations,
    )
