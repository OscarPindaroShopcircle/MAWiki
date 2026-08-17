import uuid
from datetime import datetime
from typing import Annotated, Generic, List, TypeVar
from zoneinfo import ZoneInfo

from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_serializer
from pydantic.alias_generators import to_camel


def datetime_to_gmt_str(dt: datetime) -> str:
    if not dt.tzinfo:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.strftime("%Y-%m-%dT%H:%M:%S%z")


_base_config = dict(
    populate_by_name=True,
    alias_generator=to_camel,
    validate_default=True,
    validate_assignment=True,
    use_enum_values=True,
    str_strip_whitespace=True,
)

UUIDField = Annotated[
    uuid.UUID,
    BeforeValidator(lambda v: v if isinstance(v, uuid.UUID) else uuid.UUID(str(v))),
]


class AppBaseModel(BaseModel):
    """Base model for all app schemas.

    Strips leading/trailing whitespace from string fields, camel-cases
    aliases, and validates defaults and assignments.
    """

    model_config = ConfigDict(**_base_config, from_attributes=True)

    @field_serializer("created_at", "updated_at", mode="plain", check_fields=False)
    @classmethod
    def _serialize_datetime(cls, v: datetime | None) -> str | None:
        if v is None:
            return None
        return datetime_to_gmt_str(v)

    def serializable_dict(self, **kwargs):
        """Return a dict which contains only serializable fields."""
        return jsonable_encoder(self.model_dump())


class AppBaseModelStripped(BaseModel):
    """Base model that keeps snake_case JSON keys (no camelCase alias).

    Same validation/whitespace-stripping as ``AppBaseModel`` but without the
    ``to_camel`` alias generator — use this for schemas whose field names are
    already the exact JSON keys clients expect (e.g. ``access_token``,
    ``refresh_token``).
    """

    model_config = ConfigDict(
        populate_by_name=True,
        validate_default=True,
        validate_assignment=True,
        use_enum_values=True,
        str_strip_whitespace=True,
        from_attributes=True,
    )

    @field_serializer("created_at", "updated_at", mode="plain", check_fields=False)
    @classmethod
    def _serialize_datetime(cls, v: datetime | None) -> str | None:
        if v is None:
            return None
        return datetime_to_gmt_str(v)


class TimestampMixin(BaseModel):
    """Pydantic mixin mirroring the SQLAlchemy ``TimestampMixin``.

    Inherit on response schemas that expose ``created_at`` / ``updated_at``
    so the fields and their annotations are declared once.
    """

    created_at: Annotated[datetime, Field(description="Creation timestamp")]
    updated_at: Annotated[datetime, Field(description="Last update timestamp")]


T = TypeVar("T")


class ListResponse(AppBaseModel, Generic[T]):
    """Generic wrapper for list responses to allow future metadata extension."""

    data: List[T]


class PagedResponse(AppBaseModel, Generic[T]):
    """Generic wrapper for paginated list responses.

    ``total`` is the full count of matching rows (not just the page slice),
    so clients can render total pages. ``page`` is 1-indexed.
    """

    data: List[T]
    total: int
    page: int
    page_size: int
