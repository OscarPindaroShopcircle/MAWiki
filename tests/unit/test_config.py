import pytest

from pydantic import SecretStr

from backend import config as config_module
from backend.config import (
    AppConfig,
    AuthConfig,
    ConfigException,
    EnvSecret,
    GoogleSSOConfig,
    PostgresConfig,
    secret_preview,
)


def test_secret_fields_can_reference_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JWT_SECRET_TEST", "jwt-from-environment")
    monkeypatch.setenv("GOOGLE_SECRET_TEST", "google-from-environment")
    monkeypatch.setenv("DATABASE_PASSWORD_TEST", "database-from-environment")

    auth = AuthConfig(
        jwt_secret={"env_var": "JWT_SECRET_TEST"},
        google=GoogleSSOConfig(
            client_id="client-id",
            client_secret={"env_var": "GOOGLE_SECRET_TEST"},
        ),
    )
    database = PostgresConfig(
        user="app",
        password={"env_var": "DATABASE_PASSWORD_TEST"},
        db="backend",
    )

    assert isinstance(auth.jwt_secret, SecretStr)
    assert auth.jwt_secret.get_secret_value() == "jwt-from-environment"
    assert auth.google is not None
    assert auth.google.client_secret.get_secret_value() == "google-from-environment"
    assert database.password.get_secret_value() == "database-from-environment"


def test_env_secret_is_a_strict_reference_model() -> None:
    reference = EnvSecret.model_validate({"env_var": "JWT_SECRET_TEST"})

    assert reference.env_var == "JWT_SECRET_TEST"
    with pytest.raises(ValueError):
        EnvSecret.model_validate({"env_var": "JWT_SECRET_TEST", "value": "secret"})


def test_secret_references_can_use_dotenv_values(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("JWT_SECRET_DOTENV_TEST=jwt-from-dotenv\n")

    config = AuthConfig(jwt_secret={"env_var": "JWT_SECRET_DOTENV_TEST"})

    assert config.jwt_secret.get_secret_value() == "jwt-from-dotenv"


def test_missing_secret_environment_variable_is_rejected() -> None:
    with pytest.raises(
        ValueError, match="Environment variable 'MISSING_SECRET_TEST' is not set"
    ):
        AuthConfig(jwt_secret={"env_var": "MISSING_SECRET_TEST"})


def test_secret_values_without_references_are_unchanged() -> None:
    config = AuthConfig(jwt_secret="literal-secret")

    assert config.jwt_secret.get_secret_value() == "literal-secret"


def test_secret_preview_only_returns_last_four_string_characters() -> None:
    config = AuthConfig(jwt_secret="literal-secret")

    assert secret_preview(config.jwt_secret) == "****cret"
    assert secret_preview(1234) == ""


def test_dev_auto_login_is_rejected_outside_development() -> None:
    values = {
        "database": {"user": "app", "password": "secret", "db": "app"},
        "migrator": {"user": "migrator", "password": "secret", "db": "app"},
        "auth": {
            "jwt_secret": "secret",
            "dev_auto_login_email": "developer@example.com",
        },
    }

    assert (
        AppConfig(env="dev", **values).auth.dev_auto_login_email
        == "developer@example.com"
    )
    with pytest.raises(ValueError, match="may only be set when env is 'dev'"):
        AppConfig(env="production", **values)


def test_enabled_mcp_requires_secure_google_configuration() -> None:
    values = {
        "database": {"user": "app", "password": "secret", "db": "app"},
        "migrator": {"user": "migrator", "password": "secret", "db": "app"},
        "auth": {"jwt_secret": "secret", "dev_auto_login_email": None},
    }

    with pytest.raises(ValueError, match="requires public_url and google"):
        AppConfig(env="dev", mcp={"enabled": True, "auth_enabled": True}, **values)
    with pytest.raises(ValueError, match="requires jwt_signing_key"):
        AppConfig(
            env="dev",
            mcp={
                "enabled": True,
                "auth_enabled": True,
                "public_url": "http://localhost:8000",
                "google": {
                    "client_id": "client",
                    "client_secret": "secret",
                    "workspace_domain": "example.com",
                },
            },
            **values,
        )
    with pytest.raises(ValueError, match="requires an HTTPS"):
        AppConfig(
            env="production",
            mcp={
                "enabled": True,
                "auth_enabled": True,
                "public_url": "http://localhost:8000",
                "google": {
                    "client_id": "client",
                    "client_secret": "secret",
                    "workspace_domain": "example.com",
                },
                "jwt_signing_key": "signing-secret",
            },
            **values,
        )


def test_get_app_config_hides_invalid_input(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError) as error:
        AuthConfig.model_validate({"jwt_secret": {"env_var": ""}})

    def raise_validation_error():
        raise error.value

    monkeypatch.setattr(config_module, "AppConfig", raise_validation_error)
    config_module.get_app_config.cache_clear()

    with pytest.raises(
        ConfigException, match="AppConfig validation failed"
    ) as startup_error:
        config_module.get_app_config()

    assert "input_value" not in str(startup_error.value)
