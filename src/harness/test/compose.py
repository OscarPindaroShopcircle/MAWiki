import os
import subprocess
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from dotenv import dotenv_values

from .state import EnvironmentMode, EnvironmentState

_REPO_ROOT = Path(__file__).resolve().parents[3]
_COMPOSE_FILES = {
    EnvironmentMode.LOCAL: Path(__file__).with_name("compose.test.yml"),
    EnvironmentMode.DOCKER: Path(__file__).with_name("compose.docker.test.yml"),
}


class ComposeError(RuntimeError):
    """Raised when a Docker Compose operation fails."""


def _environment(environment_state: EnvironmentState) -> dict[str, str]:
    values = {
        key: value
        for key, value in dotenv_values(environment_state.config.env).items()
        if value is not None
    }
    values.update(
        HARNESS_DB_PORT=str(environment_state.ports.database),
        HARNESS_BACKEND_PORT=str(environment_state.ports.backend or ""),
        HARNESS_OPENWEBUI_PORT=str(environment_state.ports.openwebui or ""),
        HARNESS_ENV_FILE=str(environment_state.config.env),
        HARNESS_CONFIG_FILE=str(environment_state.config.docker),
        HARNESS_PROJECT=environment_state.compose_project,
    )
    return {**os.environ, **values}


def _run(environment_state: EnvironmentState, *args: str) -> str:
    command = [
        "docker",
        "compose",
        "--project-name",
        environment_state.compose_project,
        "-f",
        str(_COMPOSE_FILES[environment_state.mode]),
        *args,
    ]
    result = subprocess.run(
        command,
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        env=_environment(environment_state),
    )
    if result.returncode != 0:
        raise ComposeError(
            f"docker compose {' '.join(args)} failed:\n{result.stderr.strip()}"
        )
    return result.stdout.strip()


def up(environment_state: EnvironmentState) -> None:
    if environment_state.mode == EnvironmentMode.LOCAL:
        _run(environment_state, "up", "--detach", "--wait")
        return
    _run(environment_state, "up", "--detach")
    assert environment_state.ports.backend is not None
    assert environment_state.ports.openwebui is not None
    _wait_for_http(
        f"http://127.0.0.1:{environment_state.ports.backend}/ping",
        attempts=30,
    )
    _wait_for_http(
        f"http://127.0.0.1:{environment_state.ports.openwebui}/health",
        attempts=180,
    )


def down(environment_state: EnvironmentState) -> None:
    _run(environment_state, "down", "--volumes", "--remove-orphans")


def status_text(environment_state: EnvironmentState) -> str:
    return _run(environment_state, "ps")


def _wait_for_http(url: str, attempts: int = 30) -> None:
    for _ in range(attempts):
        try:
            with urlopen(url, timeout=1) as response:
                if 200 <= response.status < 400:
                    return
        except URLError, OSError:
            time.sleep(1)
    raise ComposeError(f"Timed out waiting for {url}")
