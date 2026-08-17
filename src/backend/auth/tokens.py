from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import jwt
from fastapi import Response
from pydantic import BaseModel, Field

from ..config import AppConfig, AuthConfig, get_app_config


class AccessTokenPayload(BaseModel):
    """JWT claims for a short-lived access token."""

    sub: str = Field(description="Subject — the user ID as a string")
    email: str = Field(description="User email at issue time")
    role: str = Field(description="User role at issue time")
    type: str = Field(default="access", description="Token type claim")
    iat: datetime = Field(description="Issued-at timestamp (UTC)")
    exp: datetime = Field(description="Expiry timestamp (UTC)")


class RefreshTokenPayload(BaseModel):
    """JWT claims for a long-lived refresh token."""

    sub: str = Field(description="Subject — the user ID as a string")
    type: str = Field(default="refresh", description="Token type claim")
    iat: datetime = Field(description="Issued-at timestamp (UTC)")
    exp: datetime = Field(description="Expiry timestamp (UTC)")


def _get_auth_config() -> AuthConfig:
    """Return the auth config, raising clearly if it is not set."""
    config = get_app_config()
    if config.auth is None:
        raise RuntimeError(
            "Auth is not configured — add an `auth:` block with a jwt_secret to config.yaml."
        )
    return config.auth


def _encode_payload(payload: BaseModel) -> str:
    """Encode a pydantic JWT-payload model into a signed JWT string."""
    auth_config = _get_auth_config()
    return jwt.encode(
        payload.model_dump(),
        auth_config.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )


def create_access_token(user_id: UUID, email: str, role: str) -> str:
    """Issue a short-lived JWT access token (default 15 min)."""
    auth_config = _get_auth_config()
    now = datetime.now(timezone.utc)
    payload = AccessTokenPayload(
        sub=str(user_id),
        email=email,
        role=role,
        iat=now,
        exp=now + timedelta(minutes=auth_config.access_token_expire_minutes),
    )
    return _encode_payload(payload)


def create_refresh_token(user_id: UUID) -> str:
    """Issue a long-lived JWT refresh token (default 30 days)."""
    auth_config = _get_auth_config()
    now = datetime.now(timezone.utc)
    payload = RefreshTokenPayload(
        sub=str(user_id),
        iat=now,
        exp=now + timedelta(days=auth_config.refresh_token_expire_days),
    )
    return _encode_payload(payload)


def decode_token(token: str) -> dict[str, Any]:
    """Decode and verify a JWT.

    Raises:
        jwt.ExpiredSignatureError: token has expired.
        jwt.InvalidTokenError: token is malformed or signature is invalid.
    """
    auth_config = _get_auth_config()
    return jwt.decode(
        token,
        auth_config.jwt_secret.get_secret_value(),
        algorithms=["HS256"],
    )


def _cookie_secure(config: AppConfig) -> bool:
    """Resolve the secure flag for auth cookies (auto = not dev)."""
    assert config.auth is not None
    secure = config.auth.cookie_secure
    if secure is None:
        secure = config.env != "dev"
    return secure


def set_auth_cookies(
    response: Response,
    access_token: str,
    refresh_token: str,
    config: AppConfig,
) -> None:
    """Set both the access_token and refresh_token cookies on a response.

    Both are httponly, samesite=lax, secure per config, scoped to path="/"
    so they are visible to every route (``get_current_user`` runs on all of
    them). The access cookie lives ``access_token_expire_minutes`` and the
    refresh cookie lives ``refresh_token_expire_days``.
    """
    assert config.auth is not None
    secure = _cookie_secure(config)
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        samesite="lax",
        secure=secure,
        max_age=config.auth.access_token_expire_minutes * 60,
        path="/",
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        samesite="lax",
        secure=secure,
        max_age=config.auth.refresh_token_expire_days * 86400,
        path="/",
    )
