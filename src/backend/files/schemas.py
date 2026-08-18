from typing import Annotated

from pydantic import Field

from .models import StorageType
from ..schemas import AppBaseModel, TimestampMixin, UUIDField


class FileCreate(AppBaseModel):
    name: Annotated[str, Field(min_length=1, max_length=255, examples=["report.csv"])]
    location: Annotated[str, Field(min_length=1, examples=["uploads/report.csv"])]
    storage_type: Annotated[StorageType | None, Field(default=None)]


class FileUpdate(AppBaseModel):
    name: Annotated[str | None, Field(default=None, min_length=1, max_length=255)]
    location: Annotated[str | None, Field(default=None, min_length=1)]
    storage_type: Annotated[StorageType | None, Field(default=None)]


class FileResponse(AppBaseModel, TimestampMixin):
    # NOTE: deliberately omits ``storage_type`` and ``location`` — where/how a
    # file is physically stored is internal and must never be exposed to the UI.
    id: Annotated[
        UUIDField,
        Field(description="File ID", examples=["01J5KQ3X-file-example"]),
    ]
    name: Annotated[
        str,
        Field(
            max_length=255,
            examples=["report.pdf"],
            description="Original file name",
        ),
    ]
