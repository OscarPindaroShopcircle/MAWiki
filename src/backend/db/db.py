from sqlalchemy import inspect
import re
from contextlib import asynccontextmanager, contextmanager
from sqlalchemy import Engine, create_engine
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker, DeclarativeBase, declared_attr

from ..config import DatabaseSettingsProtocol

from sqlalchemy import MetaData

NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    def __repr__(self) -> str:
        cols = {c.key: getattr(self, c.key) for c in inspect(self).mapper.column_attrs}
        return f"<{self.__class__.__name__} {cols}>"

    def to_dict(self) -> dict:
        return {c.key: getattr(self, c.key) for c in inspect(self).mapper.column_attrs}

    @declared_attr.directive
    def __tablename__(cls) -> str:
        # Converts CamelCase → snake_case plural: UserProfile → user_profiles
        # Also strips "Model" suffix if present: UserModel → users
        name = cls.__name__
        if name.endswith("Model"):
            name = name[:-5]
        name = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
        return f"{name}s"


class DatabaseManager:
    """Manages database engines and session makers."""

    def __init__(self, db_settings: DatabaseSettingsProtocol):
        self.postgres_settings = db_settings
        self._async_engine: AsyncEngine | None = None
        self._sync_engine: Engine | None = None
        self._async_session_maker: async_sessionmaker[AsyncSession] | None = None
        self._sync_session_maker: sessionmaker[Session] | None = None

    @property
    def async_engine(self) -> AsyncEngine:
        """Get or create async engine."""
        if self._async_engine is None:
            self._async_engine = create_async_engine(
                self.postgres_settings.async_url,
                echo=True,
            )
        return self._async_engine

    @property
    def sync_engine(self) -> Engine:
        """Get or create sync engine."""
        if self._sync_engine is None:
            self._sync_engine = create_engine(
                self.postgres_settings.sync_url,
                echo=True,
            )
        return self._sync_engine

    @property
    def async_session_maker(self) -> async_sessionmaker[AsyncSession]:
        """Get or create async session maker."""
        if self._async_session_maker is None:
            self._async_session_maker = async_sessionmaker(
                self.async_engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )
        return self._async_session_maker

    @property
    def sync_session_maker(self) -> sessionmaker[Session]:
        """Get or create sync session maker."""
        if self._sync_session_maker is None:
            self._sync_session_maker = sessionmaker(
                self.sync_engine,
                expire_on_commit=False,
            )
        return self._sync_session_maker

    async def initialize_tables(self) -> None:
        """Create all database tables."""
        async with self.async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        """Close all database connections."""
        if self._async_engine:
            await self._async_engine.dispose()
        if self._sync_engine:
            self._sync_engine.dispose()

    @asynccontextmanager
    async def async_session(self):
        """Async context manager for database sessions.

        Creates a session, yields it, commits on success, rolls back on error,
        and closes the session in the finally block.
        """
        session = self.async_session_maker()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    @contextmanager
    def sync_session(self):
        """Sync context manager for database sessions.

        Creates a session, yields it, commits on success, rolls back on error,
        and closes the session in the finally block.
        """
        session = self.sync_session_maker()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
