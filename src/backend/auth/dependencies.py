import uuid

import jwt
from fastapi import Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import AppConfig, get_app_config
from ..dependencies import get_db_session
from ..db.enums import UserRole
from ..users.models import UserModel
from ..users.schemas import User
from .exceptions import InvalidTokenException, NotAdminException
from .tokens import (
    create_access_token,
    create_refresh_token,
    decode_token,
    set_auth_cookies,
)


def _extract_token(request: Request) -> str | None:
    """Extract a JWT from the Authorization header or the access_token cookie."""
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header.removeprefix("Bearer ").strip()
    cookie_token = request.cookies.get("access_token")
    if cookie_token:
        return cookie_token
    return None


def _has_bearer_header(request: Request) -> bool:
    """Return True if the request carries an explicit Authorization: Bearer header.

    API clients that send an explicit (but expired/invalid) Bearer header
    should get a clean 401 rather than being silently upgraded via an
    unrelated refresh cookie — only the cookie path self-heals.
    """
    auth_header = request.headers.get("Authorization")
    return bool(auth_header and auth_header.startswith("Bearer "))


async def _try_refresh_from_cookie(
    request: Request,
    response: Response,
    db: AsyncSession,
    config: AppConfig,
) -> User | None:
    """Attempt to mint a fresh access+refresh pair from the refresh_token cookie.

    Returns the authenticated ``User`` and sets new auth cookies on
    ``response`` if the refresh cookie is present and valid. Returns
    ``None`` if no refresh cookie is present or it is invalid/expired —
    the caller should then raise ``InvalidTokenException`` as usual.
    """
    refresh_cookie = request.cookies.get("refresh_token")
    if not refresh_cookie:
        return None

    try:
        payload = decode_token(refresh_cookie)
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

    if payload.get("type") != "refresh":
        return None

    try:
        user_id = uuid.UUID(payload["sub"])
    except ValueError, KeyError, TypeError:
        return None
    result = await db.execute(select(UserModel).where(UserModel.id == user_id))
    user_model = result.scalar_one_or_none()
    if user_model is None or not user_model.is_active:
        return None

    new_access = create_access_token(user_model.id, user_model.email, user_model.role)
    new_refresh = create_refresh_token(user_model.id)
    set_auth_cookies(response, new_access, new_refresh, config)
    return User.model_validate(user_model)


async def _try_dev_auto_login(
    response: Response,
    db: AsyncSession,
    config: AppConfig,
) -> User | None:
    """Authenticate the configured development user and issue normal cookies."""
    email = config.auth.dev_auto_login_email if config.auth else None
    if config.env != "dev" or email is None:
        return None

    result = await db.execute(select(UserModel).where(UserModel.email == email))
    user_model = result.scalar_one_or_none()
    if user_model is None or not user_model.is_active:
        return None

    access_token = create_access_token(user_model.id, user_model.email, user_model.role)
    refresh_token = create_refresh_token(user_model.id)
    set_auth_cookies(response, access_token, refresh_token, config)
    return User.model_validate(user_model)


async def _try_browser_auth(
    request: Request,
    response: Response,
    db: AsyncSession,
    config: AppConfig,
) -> User | None:
    user = await _try_refresh_from_cookie(request, response, db, config)
    return user or await _try_dev_auto_login(response, db, config)


async def get_current_user(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db_session),
    config: AppConfig = Depends(get_app_config),
) -> User:
    """Extract and validate the JWT, returning the authenticated user as a Pydantic model.

    Checks both the ``Authorization: Bearer`` header (for API/HTMX clients)
    and the ``access_token`` cookie (for browser page navigation).

    When the access token is missing or expired **and came from the cookie
    path** (no explicit ``Authorization: Bearer`` header present), the
    dependency silently mints a fresh access+refresh pair from the
    ``refresh_token`` cookie and sets them on the response — so plain
    browser navigations self-heal without a JS round trip. In development, a
    configured auto-login user is used when cookie authentication fails. API
    clients sending an explicit expired Bearer header still get a clean 401.

    Raises ``InvalidTokenException`` (401) if no valid token is found and no valid
    refresh cookie is available, the token type is not ``"access"``, or
    the user is missing/inactive.
    """
    token = _extract_token(request)
    bearer_header_present = _has_bearer_header(request)

    if not token:
        # No access token at all. Only attempt cookie-based refresh when the
        # request did not carry an explicit Bearer header (API clients with
        # a missing header still get a clean 401).
        if not bearer_header_present:
            refreshed = await _try_browser_auth(request, response, db, config)
            if refreshed is not None:
                return refreshed
        raise InvalidTokenException("Missing or invalid Authorization header")

    try:
        payload = decode_token(token)
    except jwt.ExpiredSignatureError:
        # Access token expired. Only self-heal from the refresh cookie on the
        # cookie path (no explicit Bearer header) — API clients with an
        # expired Bearer header get a clean 401.
        if not bearer_header_present:
            refreshed = await _try_browser_auth(request, response, db, config)
            if refreshed is not None:
                return refreshed
        raise InvalidTokenException("Token has expired")
    except jwt.InvalidTokenError:
        if not bearer_header_present:
            refreshed = await _try_browser_auth(request, response, db, config)
            if refreshed is not None:
                return refreshed
        raise InvalidTokenException("Invalid token")

    if payload.get("type") != "access":
        raise InvalidTokenException("Not an access token")

    try:
        user_id = uuid.UUID(payload["sub"])
    except ValueError, KeyError, TypeError:
        raise InvalidTokenException("Malformed token subject") from None
    result = await db.execute(select(UserModel).where(UserModel.id == user_id))
    user_model = result.scalar_one_or_none()
    if user_model is None:
        raise InvalidTokenException("User not found")
    if not user_model.is_active:
        raise InvalidTokenException("User is inactive")
    return User.model_validate(user_model)


async def get_current_admin_user(
    user: User = Depends(get_current_user),
) -> User:
    """Require the authenticated user to have the ``admin`` role."""
    if user.role != UserRole.ADMIN:
        raise NotAdminException()
    return user


async def get_optional_user(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db_session),
    config: AppConfig = Depends(get_app_config),
) -> User | None:
    """Like ``get_current_user`` but returns ``None`` instead of raising 401.

    Used by view routes that render pages for both authenticated and
    anonymous visitors (e.g. the home page).
    """
    try:
        return await get_current_user(request, response, db, config)
    except InvalidTokenException:
        return None
