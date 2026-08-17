from collections.abc import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from pydantic_settings import SettingsConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.config import AppConfig
from src.backend.db.db import DatabaseManager
from src.backend.dependencies import get_db_session
from src.backend.server import create_app


class TestAppConfig(AppConfig):
    model_config = SettingsConfigDict(
        env_file=".env.test",
        yaml_file="config.test.yaml",
        extra="ignore",
        env_nested_delimiter="__",
        populate_by_name=True,
    )


@pytest.fixture(scope="session")
def app_config() -> AppConfig:
    return TestAppConfig()


@pytest_asyncio.fixture(scope="session")
async def db_manager(app_config: AppConfig) -> AsyncGenerator[DatabaseManager, None]:
    manager = DatabaseManager(app_config.database)
    yield manager
    await manager.close()


@pytest.fixture(scope="session")
def app(app_config: AppConfig, db_manager: DatabaseManager) -> FastAPI:
    test_app = create_app(app_config)

    async def _override_get_db_session() -> AsyncGenerator[AsyncSession, None]:
        """Test override: always rollback so tests never persist data."""
        session = db_manager.async_session_maker()
        try:
            yield session
        finally:
            await session.rollback()
            await session.close()

    test_app.dependency_overrides[get_db_session] = _override_get_db_session
    return test_app


@pytest.fixture
def client(app: FastAPI) -> Generator[TestClient, None, None]:
    """Synchronous test client for simple endpoint tests."""
    with TestClient(app) as test_client:
        yield test_client


@pytest_asyncio.fixture
async def async_client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Async test client for testing async endpoints."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def db_session(db_manager: DatabaseManager) -> AsyncGenerator[AsyncSession, None]:
    """Standalone session for direct repository/service testing.

    Always rolls back — no data persists between tests.
    """
    session = db_manager.async_session_maker()
    try:
        yield session
    finally:
        await session.rollback()
        await session.close()
