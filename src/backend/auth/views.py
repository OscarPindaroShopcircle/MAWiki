import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import AppConfig, get_app_config
from ..db.enums import UserRole
from ..dependencies import get_catalog_dep, get_db_session
from ..log import get_logger
from ..users.models import UserModel
from .dependencies import get_current_user
from .exceptions import AuthException, InvalidCredentialsException, NotInvitedException
from .schemas import LoginRequest, RegisterRequest
from .service import (
    find_pending_invitation,
    login_with_password,
    register_with_password,
)
from .sso import build_google_sso
from .tokens import create_access_token, create_refresh_token, set_auth_cookies

logger = get_logger(__name__)
router = APIRouter(tags=["auth-views"])


def _htmx_redirect(url: str) -> Response:
    location = RedirectResponse(url).headers["location"]
    return Response(status_code=204, headers={"HX-Redirect": location})


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    mode: str = Query("login", pattern="^(login|register)$"),
    error: str | None = Query(None),
    catalog=Depends(get_catalog_dep),
    config: AppConfig = Depends(get_app_config),
):
    """Login / register page — standalone (no sidebar layout)."""
    google_enabled = build_google_sso(config) is not None
    return catalog.render(
        "pages.login.Login",
        mode=mode,
        error=error,
        google_enabled=google_enabled,
        dev_login_email=config.auth.bootstrap_admin_email if config.auth else "",
    )


@router.post("/auth/login-form")
async def login_form(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db_session),
    config: AppConfig = Depends(get_app_config),
):
    """Browser form-based login (JSON body) — sets cookies and redirects to /."""
    try:
        user = await login_with_password(db, body.email, body.password)
    except InvalidCredentialsException:
        return RedirectResponse(
            url="/login?error=Invalid email or password", status_code=303
        )
    logger.info("Form login successful", user_id=str(user.id), role=user.role.value)
    access_token = create_access_token(user.id, user.email, user.role)
    refresh_token = create_refresh_token(user.id)
    response = RedirectResponse(url="/", status_code=303)
    set_auth_cookies(response, access_token, refresh_token, config)
    return response


@router.post("/auth/register-form")
async def register_form(
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db_session),
    config: AppConfig = Depends(get_app_config),
):
    """Browser form-based registration (JSON body) — sets cookies and redirects to /."""
    try:
        user = await register_with_password(db, body, config)
    except NotInvitedException:
        return RedirectResponse(
            url="/login?mode=register&error=This email is not invited",
            status_code=303,
        )
    except AuthException as e:
        return RedirectResponse(
            url=f"/login?mode=register&error={e.detail}", status_code=303
        )
    logger.info(
        "Form registration successful", user_id=str(user.id), role=user.role.value
    )
    access_token = create_access_token(user.id, user.email, user.role)
    refresh_token = create_refresh_token(user.id)
    response = RedirectResponse(url="/", status_code=303)
    set_auth_cookies(response, access_token, refresh_token, config)
    return response


@router.post("/auth/dev-login-form")
async def dev_login_form(
    request: Request,
    db: AsyncSession = Depends(get_db_session, scope="function"),
    config: AppConfig = Depends(get_app_config),
):
    """Sign in an invited or bootstrap user without a password in development."""
    if config.env != "dev":
        return _htmx_redirect("/login?error=Dev login is disabled")

    try:
        email = json.loads(await request.body()).get("email", "").strip()
    except AttributeError, json.JSONDecodeError:
        email = ""
    if not email:
        return _htmx_redirect("/login?error=Email is required")

    user = await db.scalar(select(UserModel).where(UserModel.email == email))
    if user is None:
        invitation = await find_pending_invitation(db, email)
        if invitation is None:
            bootstrap_email = config.auth.bootstrap_admin_email if config.auth else None
            if email != bootstrap_email:
                return _htmx_redirect(
                    f"/login?error=No user or invitation found for {email}"
                )
            role = UserRole.ADMIN
        else:
            role = invitation.role
            invitation.accepted_at = datetime.now(UTC)
        user = UserModel(name=email, email=email, role=role)
        db.add(user)
        await db.flush()

    access_token = create_access_token(user.id, user.email, user.role)
    refresh_token = create_refresh_token(user.id)
    response = _htmx_redirect("/")
    set_auth_cookies(response, access_token, refresh_token, config)
    return response


@router.get("/auth/logout-view")
async def logout_view():
    """Redirect-based logout — clears cookies and sends to /login."""
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(key="access_token", path="/")
    response.delete_cookie(key="refresh_token", path="/")
    return response
