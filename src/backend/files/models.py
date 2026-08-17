from enum import Enum

from sqlalchemy import Enum as SAEnum, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db.db import Base
from ..db.mixins import TimestampMixin, UUIDv7PrimaryKeyMixin


class StorageType(str, Enum):
    """Where a File physically lives.

    Only LOCAL is wired up for now; the rest are placeholders for the
    filesystem backends we'll add later (S3, Azure Blob, Railway volumes).
    """

    LOCAL = "LOCAL"
    S3 = "S3"


class FileModel(Base, UUIDv7PrimaryKeyMixin, TimestampMixin):
    """A storage-agnostic reference to a file.

    Fully generic — a file can belong to a project, a user profile, or
    anything else later; whoever owns that link manages it (see
    ``ProjectFileModel``) rather than this table growing an FK per owner type.
    Ownership (who uploaded it) will likely be its own join table later too.

    ``location`` is the path/key of the file *within* its storage backend; the
    concrete FileSystem (local, s3, ...) knows how to resolve it. ``storage_type``
    records where it lives so we know which backend to hand it to.
    """

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    location: Mapped[str] = mapped_column(Text, nullable=False)
    storage_type: Mapped[StorageType | None] = mapped_column(
        SAEnum(StorageType),
        nullable=True,
        default=None,
    )
