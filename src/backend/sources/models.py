import uuid
from enum import Enum

from sqlalchemy import Column, Enum as SAEnum, ForeignKey, String, Table
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.db import Base
from ..db.mixins import TimestampMixin, UUIDv7PrimaryKeyMixin
from ..files.models import FileModel
from ..users.models import UserModel


class SourceOrigin(str, Enum):
    USER = "USER"
    SYSTEM = "SYSTEM"


source_files = Table(
    "source_files",
    Base.metadata,
    Column("source_id", ForeignKey("sources.id", ondelete="CASCADE"), primary_key=True),
    Column("file_id", ForeignKey("files.id", ondelete="CASCADE"), primary_key=True),
)

source_shared_users = Table(
    "source_shared_users",
    Base.metadata,
    Column("source_id", ForeignKey("sources.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
)


class SourceModel(Base, UUIDv7PrimaryKeyMixin, TimestampMixin):
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    origin: Mapped[SourceOrigin] = mapped_column(
        SAEnum(SourceOrigin, name="source_origin"),
        nullable=False,
        default=SourceOrigin.USER,
    )
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    created_by: Mapped[UserModel] = relationship(
        foreign_keys=[created_by_id], lazy="select"
    )
    files: Mapped[list[FileModel]] = relationship(secondary=source_files, lazy="select")
    shared_with: Mapped[list[UserModel]] = relationship(
        secondary=source_shared_users, lazy="select"
    )
