from sqlalchemy import BigInteger
import uuid
from datetime import UTC, datetime

import uuid_utils
from sqlalchemy import DateTime, Float, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import MappedColumn, mapped_column


class IntegerPrimaryKeyMixin:
    id: MappedColumn[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )


class BigIntPrimaryKeyMixin:
    id: MappedColumn[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )


class UUIDv4PrimaryKeyMixin:
    """Random UUID primary key.

    Best for: security-sensitive IDs, external-facing resources.
    Downside: random inserts fragment the B-tree index at scale.
    """

    id: MappedColumn[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )


class UUIDv7PrimaryKeyMixin:
    """Time-sortable UUID primary key (RFC 9562).

    Best for: internal PKs and high-insert tables.
    Benefit: monotonically increasing → sequential B-tree inserts → better
    index locality and fewer page splits compared to UUID4.
    """

    id: MappedColumn[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid_utils.uuid7,  # Rust-backed, negligible overhead
    )


class TimestampMixin:
    """Adds created_at / updated_at columns to any model.

    * server_default=func.now() → the DB sets the value on INSERT,
      even if you bypass the ORM (migrations, raw SQL, etc.).
    * onupdate=func.now() → SQLAlchemy sets updated_at on every UPDATE
      issued through the ORM session.

    Note: onupdate is a *client-side* hook. If you UPDATE rows directly
    in the DB (e.g. via psql or a migration script) updated_at won't
    change automatically — add a DB trigger for that if needed.
    """

    created_at: MappedColumn[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: MappedColumn[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SoftDeleteMixin:
    """Marks rows as deleted without physically removing them.

    Pattern:
        - deleted_at IS NULL  → active row
        - deleted_at NOT NULL → soft-deleted row

    Tip: add a partial index in your migration so active-row queries stay fast:
        CREATE INDEX ix_<table>_active ON <table> (id) WHERE deleted_at IS NULL;
    """

    deleted_at: MappedColumn[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def soft_delete(self) -> None:
        """Mark this row as deleted (call session.flush/commit after)."""
        self.deleted_at = datetime.now(UTC)

    def restore(self) -> None:
        """Undo a soft delete."""
        self.deleted_at = None


class OptimisticLockMixin:
    """Prevents lost updates when multiple sessions modify the same row.

    How it works:
        SQLAlchemy adds `WHERE version = <current>` to every UPDATE.
        If another session already incremented the version, the WHERE clause
        matches 0 rows and SQLAlchemy raises `StaleDataError` — you catch that
        and retry / surface a 409 to the caller.

    Do YOU need to increment it?
        No. SQLAlchemy manages version automatically:
            session.add(obj)   # reads version = 1
            obj.name = "new"
            session.commit()   # issues UPDATE … WHERE version = 1 SET version = 2

        You never touch `version` directly. Just commit as usual.

    When to use:
        High-contention rows (shopping carts, inventory counts, account balances)
        where you want to detect conflicts instead of silently overwriting data.
    """

    version: MappedColumn[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )

    __mapper_args__ = {"version_id_col": version}


class AuditMixin:
    """Tracks which user created / last updated a row.

    These are plain nullable string columns — populate them in your service
    layer or via a SQLAlchemy event listener, e.g.:

        from sqlalchemy import event

        @event.listens_for(Session, "before_flush")
        def set_audit_fields(session, flush_context, instances):
            user_id = current_user_id()   # pull from context var / request scope
            for obj in session.new:
                if isinstance(obj, AuditMixin):
                    obj.created_by = user_id
                    obj.updated_by = user_id
            for obj in session.dirty:
                if isinstance(obj, AuditMixin):
                    obj.updated_by = user_id
    """

    created_by: MappedColumn[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    updated_by: MappedColumn[str | None] = mapped_column(
        String(255),
        nullable=True,
    )


# ---------------------------------------------------------------------------
# General-purpose observability mixins
#
# Not AI-specific — useful for anything whose runtime cost/latency we want to
# track (jobs, API calls, model inferences, ...).
# ---------------------------------------------------------------------------


class ExecutionTimeMixin:
    """Tracks how long an operation took.

    Stored as a single duration in milliseconds for simplicity. If you need
    absolute wall-clock timing instead, swap this for started_at / completed_at
    timestamp columns and compute the delta on read.
    """

    duration_ms: MappedColumn[float | None] = mapped_column(
        Float,
        nullable=True,
        default=None,
    )


class ComputeCostMixin:
    """Tracks the monetary cost of producing a row (e.g. LLM token spend).

    Numeric (not Float) to avoid floating-point rounding on money. Currency is
    a plain ISO-4217-ish string; keep it explicit rather than assuming USD.
    """

    cost: MappedColumn[float | None] = mapped_column(
        Numeric(12, 6),
        nullable=True,
        default=None,
    )
    currency: MappedColumn[str | None] = mapped_column(
        String(3),
        nullable=True,
        default=None,
    )


class TypeMixin:
    """Generic free-string 'type' discriminator column.

    NOTE: this is a fallback only. Prefer a dedicated SQLAlchemy ``Enum``
    column on the concrete model (as FileModel does with StorageType) so the
    valid values are enforced at the DB level. This mixin exists for cases
    where the set of types is genuinely open-ended / unknown up front.

    Capped at 32 chars (not 255) — short discriminator values, kept tight for
    fast filtering and a low memory footprint.
    """

    type: MappedColumn[str] = mapped_column(
        String(32),
        nullable=False,
    )
