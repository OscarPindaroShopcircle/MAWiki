import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..db.db import Base
from ..db.mixins import TimestampMixin, UUIDv7PrimaryKeyMixin


class McpToolName(str, Enum):
    LIST_RAGS = "list_rags"
    SEARCH = "search"
    FETCH_FILE = "fetch_file"


class McpUserModel(Base, UUIDv7PrimaryKeyMixin, TimestampMixin):
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "provider", "provider_subject", name="uq_mcp_user_provider_subject"
        ),
    )


class McpSessionModel(Base, UUIDv7PrimaryKeyMixin, TimestampMixin):
    mcp_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mcp_users.id"), nullable=True
    )


class McpToolCallModel(Base, UUIDv7PrimaryKeyMixin, TimestampMixin):
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mcp_sessions.id"), nullable=False
    )
    tool: Mapped[McpToolName] = mapped_column(
        SAEnum(McpToolName, name="mcp_tool_name"), nullable=False
    )
    rag_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rags.id", ondelete="SET NULL"), nullable=True
    )
    source_file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("files.id", ondelete="SET NULL"), nullable=True
    )
    query: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_mcp_tool_calls_session_created_at", "session_id", "created_at"),
    )
