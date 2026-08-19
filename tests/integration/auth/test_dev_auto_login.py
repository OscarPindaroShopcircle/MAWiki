import pytest
from fastapi import Response
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from src.backend.auth import tokens
from src.backend.auth.dependencies import get_current_user, get_optional_user
from src.backend.config import AppConfig
from src.backend.db.enums import UserRole
from src.backend.users.models import UserModel


@pytest.mark.integration
async def test_dev_auto_login_authenticates_configured_user(
    db_session: AsyncSession,
    app_config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = UserModel(
        name="Developer",
        email="developer@example.com",
        role=UserRole.MEMBER,
    )
    db_session.add(user)
    await db_session.flush()

    config = app_config.model_copy(deep=True)
    assert config.auth is not None
    config.env = "dev"
    config.auth.dev_auto_login_email = user.email
    monkeypatch.setattr(tokens, "_get_auth_config", lambda: config.auth)

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "query_string": b"",
            "headers": [],
        }
    )
    response = Response()

    authenticated = await get_current_user(request, response, db_session, config)

    assert str(authenticated.id) == str(user.id)
    cookies = [
        value.decode() for key, value in response.raw_headers if key == b"set-cookie"
    ]
    assert any(cookie.startswith("access_token=") for cookie in cookies)
    assert any(cookie.startswith("refresh_token=") for cookie in cookies)


@pytest.mark.integration
async def test_optional_user_ignores_refresh_cookie_without_auth_config(
    db_session: AsyncSession,
    app_config: AppConfig,
) -> None:
    config = app_config.model_copy(deep=True)
    config.auth = None
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "query_string": b"",
            "headers": [(b"cookie", b"refresh_token=stale-token")],
        }
    )

    assert await get_optional_user(request, Response(), db_session, config) is None
