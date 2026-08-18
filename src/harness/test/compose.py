"""Docker Compose orchestration for the test harness."""

import os
import subprocess
from pathlib import Path

from pydantic_settings import SettingsConfigDict

from backend.config import AppConfig

_COMPOSE_FILE = Path(__file__).resolve().parent / "compose.test.yml"
_REPO_ROOT = Path(__file__).resolve().parents[3]


class ComposeError(RuntimeError):
    """Raised when a docker compose operation fails."""


def _run(*args: str, env: dict[str, str] | None = None) -> str:
    """Run docker compose and return stdout. Raises ComposeError on failure."""
    cmd = ["docker", "compose", "-f", str(_COMPOSE_FILE), *args]
    result = subprocess.run(
        cmd,
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode != 0:
        raise ComposeError(
            f"docker compose {' '.join(args)} failed:\n{result.stderr.strip()}"
        )
    return result.stdout.strip()


def up(port: int) -> None:
    """Start the test database container."""
    env = {"HARNESS_PORT": str(port)}
    _run("up", "--detach", "--wait", env=env)


def _build_test_config() -> AppConfig:
    """Build an AppConfig that reads from .env.test and config.test.yaml."""

    class TestAppConfig(AppConfig):
        model_config = SettingsConfigDict(
            env_file=".env.test",
            yaml_file="config.test.yaml",
            extra="ignore",
            env_nested_delimiter="__",
            populate_by_name=True,
        )

    return TestAppConfig()


def run_migrations() -> None:
    """Run Alembic migrations against the test database."""
    test_config = _build_test_config()
    url = test_config.migrator.sync_url

    result = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        env={**os.environ, "HARNESS_DB_URL": url},
    )
    if result.returncode != 0:
        raise ComposeError(f"Migration failed:\n{result.stderr.strip()}")


def down() -> None:
    """Stop and remove the test database container and its volumes."""
    _run("down", "--volumes", "--remove-orphans")


def is_healthy() -> bool:
    """Return True if the test db container is healthy."""
    result = subprocess.run(
        ["docker", "compose", "-f", str(_COMPOSE_FILE), "ps", "--format", "json"],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False
    # docker compose ps --format json outputs one JSON object per line
    for line in result.stdout.strip().splitlines():
        if '"healthy"' in line:
            return True
    return False


def status_text() -> str:
    """Return a human-readable status of the test containers."""
    try:
        return _run("ps")
    except ComposeError:
        return "No test containers running."
