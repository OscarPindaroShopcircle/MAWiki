from enum import Enum

from sqlalchemy import CheckConstraint, Enum as SAEnum, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db.db import Base
from ..db.mixins import TimestampMixin, UUIDv7PrimaryKeyMixin


class TaskStatus(str, Enum):
    """Lifecycle status of an async Task.

    WAITING     → created but blocked on something else before it can start
    IN_PROGRESS → currently running
    FAILED      → terminated with an error
    SUCCESS     → completed successfully
    """

    WAITING = "WAITING"
    IN_PROGRESS = "IN_PROGRESS"
    FAILED = "FAILED"
    SUCCESS = "SUCCESS"


class TaskModel(Base, UUIDv7PrimaryKeyMixin, TimestampMixin):
    """A unit of async work the frontend can poll instead of blocking on.

    Fully generic — knows nothing about what created it. A ``TaskModel`` row
    can back a project ingestion, or any other future async job; features
    that need to know "which task belongs to which X" own that link
    themselves (see ``ProjectTaskModel``), rather than this table growing an
    FK per feature.

    uuid7 PK → time-sortable and index-friendly for a high-insert table.
    """

    __table_args__ = (
        CheckConstraint(
            "completion >= 0 AND completion <= 100",
            name="completion_between_0_and_100",
        ),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[TaskStatus] = mapped_column(
        SAEnum(TaskStatus),
        nullable=False,
        default=TaskStatus.WAITING,
    )
    completion: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
    )
    message: Mapped[str | None] = mapped_column(String(1024), nullable=True)
