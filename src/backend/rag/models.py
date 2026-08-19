import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.db import Base
from ..db.mixins import TimestampMixin, UUIDv7PrimaryKeyMixin
from ..kb.models import KnowledgeBaseModel
from ..users.models import UserModel


class RagModel(Base, UUIDv7PrimaryKeyMixin, TimestampMixin):
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    source_knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_bases.id"), nullable=False
    )
    converted_knowledge_base_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("knowledge_bases.id"), nullable=True, unique=True
    )
    owner: Mapped[UserModel] = relationship(foreign_keys=[owner_id], lazy="select")
    source_knowledge_base: Mapped[KnowledgeBaseModel] = relationship(
        foreign_keys=[source_knowledge_base_id], lazy="select"
    )
    converted_knowledge_base: Mapped[KnowledgeBaseModel | None] = relationship(
        foreign_keys=[converted_knowledge_base_id], lazy="select"
    )
