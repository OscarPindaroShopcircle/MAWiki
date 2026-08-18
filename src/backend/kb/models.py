from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from ..db.db import Base


class KnowledgeBaseModel(Base):
    """ """

    __tablename__ = "kb"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
