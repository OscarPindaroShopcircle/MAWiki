from datetime import UTC, datetime, timedelta
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import AppConfig
from ..db.enums import UserRole
from ..users.models import UserModel
from .models import (
    InvitationModel,
    UserAuthProviderModel,
    UserPasswordModel,
)
from .exceptions import (
    AuthError,
    InvalidCredentials,
    InvitationAlreadyExists,
    InvitationNotFound,
    NotInvited,
)
from .password import hash_password, verify_password
from .schemas import InvitationCreate, RegisterRequest


async def find_by_provider(
    db: AsyncSession, provider: str, provider_sub: str
) -> UserModel | None:
    """Find a user by their provider link (already linked)."""
    stmt = (
        select(UserModel)
        .join(
            UserAuthProviderModel,
            UserAuthProviderModel.user_id == UserModel.id,
        )
        .where(
            UserAuthProviderModel.provider == provider,
            UserAuthProviderModel.provider_sub == provider_sub,
        )
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def find_by_email(db: AsyncSession, email: str) -> UserModel | None:
    """Find a user by email (may exist from another provider)."""
    result = await db.execute(select(UserModel).where(UserModel.email == email))
    return result.scalar_one_or_none()


async def find_pending_invitation(
    db: AsyncSession, email: str
) -> InvitationModel | None:
    """Find a non-expired, non-accepted invitation for ``email``."""
    now = datetime.now(UTC)
    result = await db.execute(
        select(InvitationModel).where(
            InvitationModel.email == email,
            InvitationModel.accepted_at.is_(None),
            InvitationModel.expires_at > now,
        )
    )
    return result.scalar_one_or_none()


async def get_all_invitations(db: AsyncSession) -> list[InvitationModel]:
    """Return all invitations, newest first."""
    result = await db.execute(
        select(InvitationModel).order_by(InvitationModel.created_at.desc())
    )
    return list(result.scalars().all())


async def get_invitation(
    db: AsyncSession, invitation_id: int
) -> InvitationModel | None:
    """Return a single invitation by ID, or None."""
    result = await db.execute(
        select(InvitationModel).where(InvitationModel.id == invitation_id)
    )
    return result.scalar_one_or_none()


async def get_invitation_by_email(
    db: AsyncSession, email: str
) -> InvitationModel | None:
    """Return the invitation for ``email``, or None."""
    result = await db.execute(
        select(InvitationModel).where(InvitationModel.email == email)
    )
    return result.scalar_one_or_none()


async def create_invitation(
    db: AsyncSession,
    body: InvitationCreate,
    invited_by: uuid.UUID,
    expire_days: int = 7,
) -> InvitationModel:
    """Create an invitation. Raises ``InvitationAlreadyExists`` on conflict."""
    existing = await get_invitation_by_email(db, body.email)
    if existing is not None:
        raise InvitationAlreadyExists(body.email)

    invitation = InvitationModel(
        email=body.email,
        role=body.role,
        invited_by=invited_by,
        expires_at=datetime.now(UTC) + timedelta(days=expire_days),
    )
    db.add(invitation)
    await db.flush()
    await db.refresh(invitation)
    return invitation


async def revoke_invitation(db: AsyncSession, invitation_id: int) -> None:
    """Delete an invitation by ID. Raises ``InvitationNotFound`` if missing."""
    invitation = await get_invitation(db, invitation_id)
    if invitation is None:
        raise InvitationNotFound(invitation_id)
    await db.delete(invitation)
    await db.flush()


async def login_with_provider(
    db: AsyncSession, provider: str, openid, config: AppConfig
) -> UserModel:
    """Core login logic — link or create a user from a provider OpenID payload.

    1. If the provider link already exists, return that user.
    2. If the email matches an existing user (from another provider), link the
       new provider and return the user.
    3. Otherwise, check for a pending invitation or the bootstrap admin email.
       If neither, raise ``NotInvited``.
    4. Create the user + provider link.
    """
    # 1. Already linked?
    user = await find_by_provider(db, provider, openid.id)
    if user:
        return user

    # 2. Existing user via email from another provider?
    user = await find_by_email(db, openid.email)
    if user:
        db.add(
            UserAuthProviderModel(
                user_id=user.id, provider=provider, provider_sub=openid.id
            )
        )
        await db.flush()
        return user

    # 3. No user — check invitation or bootstrap admin
    invitation = await find_pending_invitation(db, openid.email)
    if invitation is None:
        bootstrap_email = config.auth.bootstrap_admin_email if config.auth else None
        if bootstrap_email and openid.email == bootstrap_email:
            role = UserRole.ADMIN
        else:
            raise NotInvited(openid.email)
    else:
        role = invitation.role
        invitation.accepted_at = datetime.now(UTC)

    # 4. Create user
    user = UserModel(
        name=openid.display_name or openid.email,
        email=openid.email,
        role=role,
    )
    db.add(user)
    await db.flush()

    # 5. Link provider
    db.add(
        UserAuthProviderModel(
            user_id=user.id, provider=provider, provider_sub=openid.id
        )
    )
    await db.flush()
    return user


async def register_with_password(
    db: AsyncSession, body: RegisterRequest, config: AppConfig
) -> UserModel:
    """Create a new user with a password.

    Gated by a pending invitation or the bootstrap admin email — no open
    self-registration. If the email already has a user, raises ``AuthError``.
    """
    existing = await find_by_email(db, body.email)
    if existing is not None:
        raise AuthError("A user with that email already exists")

    invitation = await find_pending_invitation(db, body.email)
    if invitation is None:
        bootstrap_email = config.auth.bootstrap_admin_email if config.auth else None
        if bootstrap_email and body.email == bootstrap_email:
            role = UserRole.ADMIN
        else:
            raise NotInvited(body.email)
    else:
        role = invitation.role
        invitation.accepted_at = datetime.now(UTC)

    user = UserModel(name=body.name, email=body.email, role=role)
    db.add(user)
    await db.flush()

    db.add(
        UserPasswordModel(
            user_id=user.id,
            password_hash=hash_password(body.password),
        )
    )
    await db.flush()
    return user


async def login_with_password(db: AsyncSession, email: str, password: str) -> UserModel:
    """Verify email + password and return the user.

    Raises ``InvalidCredentials`` if the user doesn't exist, has no password
    set, or the password doesn't match.
    """
    user = await find_by_email(db, email)
    if user is None:
        raise InvalidCredentials()
    if not user.is_active:
        raise InvalidCredentials("User is inactive")

    result = await db.execute(
        select(UserPasswordModel).where(UserPasswordModel.user_id == user.id)
    )
    pwd = result.scalar_one_or_none()
    if pwd is None or not verify_password(password, pwd.password_hash):
        raise InvalidCredentials()
    return user
