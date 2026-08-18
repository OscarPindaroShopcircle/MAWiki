import os
from functools import lru_cache
from typing import Annotated, Any, List, Protocol, Optional

from dotenv import dotenv_values
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
)
from pydantic_settings import BaseSettings
from pydantic_settings import (
    SettingsConfigDict,
    PydanticBaseSettingsSource,
    YamlConfigSettingsSource,
)


class ConfigException(RuntimeError):
    """Raised when application configuration cannot be parsed or validated."""


class EnvSecret(BaseModel):
    """Reference a secret stored in an environment variable."""

    env_var: str = Field(min_length=1)
    model_config = ConfigDict(extra="forbid")


def _resolve_secret_reference(value: Any) -> Any:
    """Resolve an ``EnvSecret`` mapping before SecretStr validation."""
    if not isinstance(value, dict) or "env_var" not in value:
        return value

    variable_name = EnvSecret.model_validate(value).env_var.strip()
    if not variable_name:
        raise ValueError("Secret environment variable name cannot be empty")

    resolved_value = os.environ.get(variable_name)
    if resolved_value is None:
        resolved_value = dotenv_values(".env").get(variable_name)
    if resolved_value is None:
        raise ValueError(f"Environment variable {variable_name!r} is not set")
    return resolved_value


def secret_preview(value: Any) -> str:
    """Return a masked preview with only the last four characters visible."""
    raw_value = value.get_secret_value() if isinstance(value, SecretStr) else value
    return f"****{raw_value[-4:]}" if isinstance(raw_value, str) else ""


SecretValue = Annotated[SecretStr, BeforeValidator(_resolve_secret_reference)]


class BaseConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        yaml_file="config.yaml",
        extra="ignore",
        env_nested_delimiter="__",
        populate_by_name=True,
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )


class DatabaseSettingsProtocol(Protocol):
    """Protocol that all database settings must satisfy."""

    @property
    def async_url(self) -> str: ...

    @property
    def sync_url(self) -> str: ...


class PostgresConfig(BaseConfig):
    """PostgreSQL database configuration."""

    user: str = Field(description="Database username")
    password: SecretValue = Field(description="Database password")
    host: str = Field(default="localhost", description="Database host")
    port: int = Field(default=5432, description="Database port")
    db: str = Field(description="Database name")

    @property
    def sync_url(self) -> str:
        """Build synchronous PostgreSQL connection URL."""
        return (
            f"postgresql://{self.user}:{self.password.get_secret_value()}"
            f"@{self.host}:{self.port}/{self.db}"
        )

    @property
    def async_url(self) -> str:
        """Build asynchronous PostgreSQL connection URL."""
        return (
            f"postgresql+asyncpg://{self.user}:{self.password.get_secret_value()}"
            f"@{self.host}:{self.port}/{self.db}"
        )


class MigratorConfig(PostgresConfig):
    """PostgreSQL credentials for running Alembic migrations.

    Uses a separate, more-privileged role than the runtime app.
    Only sync_url is meaningful here — Alembic doesn't use async.
    """

    pass


class SQLiteSettings(BaseSettings):
    """SQLite database configuration."""

    db_path: str = Field(default="app.db", description="Path to SQLite database file")

    @property
    def sync_url(self) -> str:
        """Build synchronous SQLite connection URL."""
        return f"sqlite:///{self.db_path}"

    @property
    def async_url(self) -> str:
        """Build asynchronous SQLite connection URL (using aiosqlite)."""
        return f"sqlite+aiosqlite:///{self.db_path}"


class FrontendConfig(BaseModel):
    """Frontend configuration."""

    enabled: bool = Field(default=True, description="Enable frontend rendering")
    templates_dir: Optional[str] = Field(
        default=None, description="Path to Jinja2 templates directory (optional)"
    )
    components_dir: str = Field(
        default="src/frontend/components",
        description="Path to JinjaX components directory",
    )
    static_dir: str = Field(
        default="src/frontend/static",
        description="Path to static files directory",
    )


class LoggingConfig(BaseModel):
    """Application logging configuration.

    All modules use ``logging.getLogger(__name__)`` and inherit from the root
    logger configured in ``log.py`` — no per-module handlers needed.
    """

    level: str = Field(default="INFO", alias="LOGGING__LEVEL")
    dir: str = Field(default="logs", alias="LOGGING__DIR")


class GoogleSSOConfig(BaseModel):
    """Google OAuth/OIDC credentials for fastapi-sso."""

    client_id: str
    client_secret: SecretValue


class AuthConfig(BaseModel):
    """Authentication configuration — JWT tokens, Google SSO, invitations."""

    google: Optional[GoogleSSOConfig] = None
    jwt_secret: SecretValue
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30
    invitation_expire_days: int = 7
    bootstrap_admin_email: Optional[str] = None
    redirect_uri: str = "http://localhost:8000/auth/callback"
    cookie_secure: Optional[bool] = None  # None = auto (True unless env=dev)


class StorageConfig(BaseModel):
    """Local-disk storage settings for uploaded files."""

    storage_root: str = Field(
        default="./data/uploads",
        description="Root directory uploaded files are written under",
    )


class AppConfig(BaseConfig):
    env: str = Field(default="dev")
    database: PostgresConfig = Field(default_factory=PostgresConfig)
    migrator: MigratorConfig = Field(default_factory=MigratorConfig)
    frontend: Optional[FrontendConfig] = Field(default=None)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    auth: Optional[AuthConfig] = Field(default=None)
    storage: StorageConfig = Field(default_factory=StorageConfig)

    # Server configuration
    backend_host: str = Field(
        default="localhost", description="Server host", alias="HOST"
    )
    backend_port: int = Field(default=8000, description="Server port", alias="PORT")

    # CORS configuration
    cors_origins: List[str] = Field(
        default=["*"], description="CORS allowed origins", alias="CORS_ORIGINS"
    )
    cors_allow_credentials: bool = Field(
        default=True,
        description="Allow CORS credentials",
        alias="CORS_ALLOW_CREDENTIALS",
    )
    cors_allow_methods: List[str] = Field(
        default=["*"], description="CORS allowed methods", alias="CORS_ALLOW_METHODS"
    )
    cors_allow_headers: List[str] = Field(
        default=["*"], description="CORS allowed headers", alias="CORS_ALLOW_HEADERS"
    )


@lru_cache(maxsize=1)
def get_app_config() -> AppConfig:
    """Get, validate, and cache the application configuration singleton."""
    try:
        return AppConfig()
    except ValidationError as error:
        details = "\n".join(
            f"  {'.'.join(str(part) for part in issue['loc'])}: {issue['msg']}"
            for issue in error.errors(include_url=False, include_input=False)
        )
        raise ConfigException(f"AppConfig validation failed:\n{details}") from None
