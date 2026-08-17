import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..db.db import Base
from ..db.enums import UserRole
from ..db.mixins import IntegerPrimaryKeyMixin, TimestampMixin


class InvitationModel(Base, IntegerPrimaryKeyMixin, TimestampMixin):
    """An email-based invitation to join the platform.

    Matching is by email only — on Google callback, ``openid.email`` is matched
    against pending (``accepted_at IS NULL``, not expired) invitations. No token
    column is needed because the OAuth flow itself is the proof of email
    ownership.
    """

    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, name="user_role"), nullable=False, default=UserRole.MEMBER
    )
    invited_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class UserPasswordModel(Base, IntegerPrimaryKeyMixin, TimestampMixin):
    """Password hash for test/admin users who authenticate without an OAuth provider.

    One row per user (enforced by the unique FK column). Storing the hash in a
    separate table keeps ``UserModel`` provider-agnostic — a user with only
    Google SSO has no row here at all.
    """

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, unique=True
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)


class UserAuthProviderModel(Base, IntegerPrimaryKeyMixin, TimestampMixin):
    """Links a user to an external auth provider (Google, GitHub, …) or password.

    One row per provider per user — a user who has logged in via both Google
    and GitHub has two rows here. ``provider_sub`` is the provider's own unique
    identifier for the user (the ``sub`` claim in OIDC).
    """

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_sub: Mapped[str] = mapped_column(String(255), nullable=False)

    __table_args__ = (
        UniqueConstraint("provider", "provider_sub", name="uq_provider_sub"),
    )
