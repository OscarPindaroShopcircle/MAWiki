from typing import Optional

from fastapi_sso.sso.google import GoogleSSO

from ..config import AppConfig


def build_google_sso(config: AppConfig) -> Optional[GoogleSSO]:
    """Build a ``GoogleSSO`` instance from ``AuthConfig``.

    Returns ``None`` when Google SSO is not configured (no ``auth.google``
    block), so callers can gate the login flow on its presence.
    """
    if config.auth is None or config.auth.google is None:
        return None
    return GoogleSSO(
        client_id=config.auth.google.client_id,
        client_secret=config.auth.google.client_secret.get_secret_value(),
        redirect_uri=config.auth.redirect_uri,
    )
