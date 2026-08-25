from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import AppConfig, get_app_config
from ..dependencies import get_catalog_dep, get_db_session
from ..log import get_logger
from .dependencies import get_current_user
from .exceptions import AuthException, InvalidCredentialsException, NotInvitedException
from .schemas import LoginRequest, RegisterRequest
from .service import login_with_password, register_with_password
from .sso import build_google_sso
from .tokens import create_access_token, create_refresh_token, set_auth_cookies

logger = get_logger(__name__)
router = APIRouter(tags=["auth-views"])


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


@router.get("/auth/logout-view")
async def logout_view():
    """Redirect-based logout — clears cookies and sends to /login."""
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(key="access_token", path="/")
    response.delete_cookie(key="refresh_token", path="/")
    return response
