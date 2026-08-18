import uuid

from sqlalchemy import Column, ForeignKey, String, Table
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.db import Base
from ..db.mixins import TimestampMixin, UUIDv7PrimaryKeyMixin
from ..files.models import FileModel
from ..users.models import UserModel


knowledge_base_files = Table(
    "knowledge_base_files",
    Base.metadata,
    Column(
        "knowledge_base_id",
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "file_id",
        ForeignKey("files.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)

knowledge_base_shared_users = Table(
    "knowledge_base_shared_users",
    Base.metadata,
    Column(
        "knowledge_base_id",
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "user_id",
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class KnowledgeBaseModel(Base, UUIDv7PrimaryKeyMixin, TimestampMixin):
    """Knowledge Base Model.
    A knowledge Base is currently a collection of files, grouped logically under it.
    """

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    created_by: Mapped[UserModel] = relationship(
        foreign_keys=[created_by_id],
        lazy="select",
    )
    files: Mapped[list[FileModel]] = relationship(
        secondary=knowledge_base_files,
        lazy="select",
    )
    shared_with: Mapped[list[UserModel]] = relationship(
        secondary=knowledge_base_shared_users,
        lazy="select",
    )
