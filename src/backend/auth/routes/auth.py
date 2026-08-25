import json
from datetime import UTC, datetime

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import AppConfig, get_app_config
from ...db.enums import UserRole
from ...dependencies import get_db_session
from ...log import get_logger
from ...users.models import UserModel
from ..exceptions import (
    AuthException,
    InvalidCredentialsException,
    InvalidTokenException,
)
from ..schemas import LoginRequest, RefreshRequest, RegisterRequest, TokenResponse
from ..service import (
    find_pending_invitation,
    login_with_password,
    login_with_provider,
    register_with_password,
)
from ..sso import build_google_sso
from ..tokens import (
    create_access_token,
    create_refresh_token,
    decode_token,
    set_auth_cookies,
)

logger = get_logger(__name__)
router = APIRouter(tags=["auth"])


@router.get(
    "/auth/google",
    responses={
        302: {"description": "Redirect to Google OAuth consent screen"},
        503: {"description": "Google SSO is not configured"},
    },
)
async def auth_google(config: AppConfig = Depends(get_app_config)):
    """Redirect the user to Google's OAuth consent screen."""
    sso = build_google_sso(config)
    if sso is None:
        raise AuthException("Google SSO is not configured")
    async with sso:
        return await sso.get_login_redirect(params={"prompt": "consent"})


@router.post(
    "/auth/refresh",
    response_model=TokenResponse,
    responses={
        200: {"description": "New access + refresh token pair"},
        401: {"description": "Invalid or expired refresh token"},
    },
)
async def auth_refresh(
    body: RefreshRequest,
    response: Response,
    db: AsyncSession = Depends(get_db_session),
    config: AppConfig = Depends(get_app_config),
):
    """Exchange a valid refresh token for a new access + refresh token pair.

    The refresh token is rotated — the old one should be discarded by the client.
    The user is looked up from the DB so the new access token carries the
    current email and role (which may have changed since the refresh token
    was issued). The fresh pair is also set as cookies so browser clients
    stay authenticated on plain navigations.
    """
    try:
        payload = decode_token(body.refresh_token)
    except jwt.ExpiredSignatureError:
        logger.error("Token refresh failed: expired")
        raise InvalidTokenException("Refresh token has expired")
    except jwt.InvalidTokenError:
        logger.error("Token refresh failed: invalid token")
        raise InvalidTokenException("Invalid refresh token")

    if payload.get("type") != "refresh":
        logger.error(
            "Token refresh failed: wrong token type", token_type=payload.get("type")
        )
        raise InvalidTokenException("Not a refresh token")

    user_id = int(payload["sub"])
    result = await db.execute(select(UserModel).where(UserModel.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        logger.error("Token refresh failed: user not found", user_id=user_id)
        raise InvalidTokenException("User not found")
    if not user.is_active:
        logger.error("Token refresh failed: user inactive", user_id=user_id)
        raise InvalidTokenException("User is inactive")

    new_access = create_access_token(user.id, user.email, user.role)
    new_refresh = create_refresh_token(user.id)
    set_auth_cookies(response, new_access, new_refresh, config)
    return TokenResponse(
        access_token=new_access,
        refresh_token=new_refresh,
        token_type="bearer",
    )


@router.get(
    "/auth/callback",
    responses={
        200: {"description": "Login successful — JSON tokens or HTML redirect"},
        401: {"description": "Login failed or user not invited"},
        503: {"description": "Google SSO is not configured"},
    },
)
async def auth_callback(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db_session),
    config: AppConfig = Depends(get_app_config),
):
    """Google OAuth callback — verify the code, issue JWT tokens.

    Content-negotiated: returns JSON ``TokenResponse`` for API clients
    (``Accept: application/json``) or an HTML page that stores tokens in
    localStorage and redirects for browsers (``Accept: text/html``).
    """
    sso = build_google_sso(config)
    if sso is None:
        raise AuthException("Google SSO is not configured")
    async with sso:
        openid = await sso.verify_and_process(request)
    if openid is None:
        logger.error("Google callback: no OpenID payload returned")
        raise AuthException("Login failed — no OpenID payload returned")

    user = await login_with_provider(db, "google", openid, config)
    logger.info("Google callback: login complete", user_id=str(user.id))
    access_token = create_access_token(user.id, user.email, user.role)
    refresh_token = create_refresh_token(user.id)

    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        html_response = HTMLResponse(
            content=f"""<!DOCTYPE html>
<html>
<head><meta http-equiv="refresh" content="0; url=/"></head>
<body>
<script>
  localStorage.setItem("access_token", "{access_token}");
  localStorage.setItem("refresh_token", "{refresh_token}");
  window.location.href = "/";
</script>
<p>Login successful. <a href="/">Click here if you are not redirected.</a></p>
</body>
</html>""",
            status_code=200,
        )
        set_auth_cookies(html_response, access_token, refresh_token, config)
        return html_response

    # JSON response for API clients — also set cookies in case they're a browser.
    # Cookies are set on the injected Response (FastAPI merges them onto the
    # returned pydantic model); the HTML branch above sets them on the
    # HTMLResponse directly because a returned Response object is used as-is.
    set_auth_cookies(response, access_token, refresh_token, config)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
    )


@router.post(
    "/auth/login",
    response_model=TokenResponse,
    responses={
        200: {"description": "Login successful — JWT tokens returned"},
        401: {"description": "Invalid email or password"},
    },
)
async def auth_login(
    body: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db_session),
    config: AppConfig = Depends(get_app_config),
):
    """Password-based login — verify credentials, issue JWT tokens."""
    user = await login_with_password(db, body.email, body.password)
    access_token = create_access_token(user.id, user.email, user.role)
    refresh_token = create_refresh_token(user.id)
    set_auth_cookies(response, access_token, refresh_token, config)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
    )


@router.post(
    "/auth/register",
    response_model=TokenResponse,
    responses={
        200: {"description": "Registration successful — JWT tokens returned"},
        401: {"description": "Email is not invited"},
        409: {"description": "A user with that email already exists"},
    },
)
async def auth_register(
    body: RegisterRequest,
    response: Response,
    db: AsyncSession = Depends(get_db_session),
    config: AppConfig = Depends(get_app_config),
):
    """Password-based registration — create a user, issue JWT tokens.

    Gated by a pending invitation or the bootstrap admin email.
    """
    user = await register_with_password(db, body, config)
    access_token = create_access_token(user.id, user.email, user.role)
    refresh_token = create_refresh_token(user.id)
    set_auth_cookies(response, access_token, refresh_token, config)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
    )


@router.post("/auth/logout")
async def auth_logout():
    """Clear the access_token and refresh_token cookies and return 200.

    The client should also clear localStorage tokens.
    """
    response = Response(status_code=200)
    response.delete_cookie(key="access_token", path="/")
    response.delete_cookie(key="refresh_token", path="/")
    return response


@router.post(
    "/auth/dev-login",
    response_model=TokenResponse,
    responses={
        200: {"description": "Dev login successful — JWT tokens returned"},
        403: {"description": "Dev login is disabled in non-dev environments"},
        404: {"description": "No user or invitation found for that email"},
    },
)
async def auth_dev_login(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db_session),
    config: AppConfig = Depends(get_app_config),
):
    """Dev-only login: mint JWTs for an existing user or pending invitation
    without going through Google SSO.

    Only available when ``config.env == "dev"``. Accepts ``email`` as a
    JSON body field or query parameter.
    """
    if config.env != "dev":
        raise HTTPException(status_code=403, detail="Dev login is disabled")

    body = await request.body()
    email = None
    if body:
        try:
            email = json.loads(body).get("email")
        except Exception:
            pass
    if not email:
        email = request.query_params.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="email is required")

    # Look for an existing user first
    result = await db.execute(select(UserModel).where(UserModel.email == email))
    user = result.scalar_one_or_none()

    if user is None:
        # Check for a pending invitation or bootstrap admin
        invitation = await find_pending_invitation(db, email)
        if invitation is None:
            bootstrap_email = config.auth.bootstrap_admin_email if config.auth else None
            if bootstrap_email and email == bootstrap_email:
                role = UserRole.ADMIN
                logger.info("Dev login: bootstrap admin auto-created", email=email)
            else:
                logger.error("Dev login failed: no user or invitation", email=email)
                raise HTTPException(
                    status_code=404,
                    detail=f"No user or invitation found for {email}",
                )
        else:
            role = invitation.role
            invitation.accepted_at = datetime.now(UTC)
            logger.info("Dev login: accepted invitation", email=email, role=role.value)

        user = UserModel(name=email, email=email, role=role)
        db.add(user)
        await db.flush()
        logger.info(
            "Dev login: user created",
            email=email,
            user_id=str(user.id),
            role=role.value,
        )

    access_token = create_access_token(user.id, user.email, user.role)
    refresh_token = create_refresh_token(user.id)

    set_auth_cookies(response, access_token, refresh_token, config)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
    )
