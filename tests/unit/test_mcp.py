from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.config import AppConfig
from backend.mcp.auth import workspace_auth_check
from backend.server import create_app


def test_workspace_auth_requires_verified_hosted_domain() -> None:
    check = workspace_auth_check("example.com")
    context = SimpleNamespace(
        token=SimpleNamespace(
            claims={
                "sub": "google-subject",
                "email": "employee@example.com",
                "email_verified": True,
                "google_user_data": {"hd": "example.com"},
            }
        )
    )

    assert check(context)
    context.token.claims["google_user_data"]["hd"] = "other.example"
    assert not check(context)
    context.token.claims["google_user_data"]["hd"] = "example.com"
    context.token.claims["email_verified"] = False
    assert not check(context)


def test_enabled_mcp_serves_oauth_discovery_routes() -> None:
    config = AppConfig.model_validate(
        {
            "env": "dev",
            "database": {"user": "app", "password": "secret", "db": "app"},
            "migrator": {"user": "migrator", "password": "secret", "db": "app"},
            "frontend": {"enabled": False},
            "mcp": {
                "enabled": True,
                "auth_enabled": True,
                "public_url": "https://testserver",
                "google": {
                    "client_id": "client",
                    "client_secret": "secret",
                    "workspace_domain": "example.com",
                },
                "jwt_signing_key": "test-signing-key",
            },
        }
    )

    with TestClient(create_app(config)) as client:
        assert client.get("/ping").status_code == 200
        assert client.get("/.well-known/oauth-authorization-server").status_code == 200
        assert (
            client.get("/.well-known/oauth-protected-resource/mcp").status_code == 200
        )
