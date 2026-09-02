import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.auth.schemas import InvitationCreate
from src.backend.auth.service import create_invitation
from src.backend.db.enums import UserRole
from src.backend.users.models import UserModel


@pytest.mark.integration
async def test_create_invitation_accepts_schema_role(db_session: AsyncSession):
    admin = UserModel(
        name="Admin",
        email="admin-invitation@example.com",
        role=UserRole.ADMIN,
    )
    db_session.add(admin)
    await db_session.flush()

    invitation = await create_invitation(
        db_session,
        InvitationCreate(email="invitee@example.com", role=UserRole.MEMBER),
        admin.id,
    )

    assert invitation.email == "invitee@example.com"
    assert invitation.role == UserRole.MEMBER
