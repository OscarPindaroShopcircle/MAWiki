import shutil
from copy import deepcopy
from pathlib import Path

import yaml
from pydantic_settings import SettingsConfigDict

from backend.config import AppConfig

from . import state


class ConfigError(RuntimeError):
    """Raised when test configuration is missing or invalid."""


def _paths(root: Path) -> tuple[Path, Path]:
    return root / ".env.test", root / "config.test.yaml"


def validate(root: Path | None = None) -> None:
    root = root or state.worktree_root()
    env_file, config_file = _paths(root)
    missing = [
        f"  {label} not found at {path}"
        for path, label in ((env_file, ".env.test"), (config_file, "config.test.yaml"))
        if not path.exists()
    ]
    if missing:
        raise ConfigError(
            "Test configuration is incomplete:\n"
            + "\n".join(missing)
            + "\n\nCopy .env.test.example → .env.test and ensure config.test.yaml exists."
        )
    try:
        data = yaml.safe_load(config_file.read_text())
    except yaml.YAMLError as error:
        raise ConfigError(f"config.test.yaml is not valid YAML: {error}") from error
    if not isinstance(data, dict):
        raise ConfigError("config.test.yaml must be a YAML mapping.")
    for key in ("database", "migrator"):
        if not isinstance(data.get(key), dict):
            raise ConfigError(f"config.test.yaml: missing or invalid '{key}' section.")


def _load(path: Path, env_file: Path) -> None:
    class TestAppConfig(AppConfig):
        model_config = SettingsConfigDict(
            env_file=env_file,
            yaml_file=path,
            extra="ignore",
            env_nested_delimiter="__",
            populate_by_name=True,
        )

    try:
        TestAppConfig()
    except Exception as error:
        raise ConfigError(f"Test configuration is invalid:\n{error}") from error


def prepare(root: Path, database_port: int) -> state.ConfigState:
    validate(root)
    if state.read(root) is not None:
        raise ConfigError("An environment is already active for this worktree.")
    env_file, config_file = _paths(root)
    source = yaml.safe_load(config_file.read_text())
    local = deepcopy(source)
    docker = deepcopy(source)
    for key in ("database", "migrator"):
        local[key].update(host="localhost", port=database_port)
        docker[key].update(host="db", port=5432)

    directory = state.state_dir(root)
    backup = directory / "config.test.yaml.backup"
    local_active = directory / "config.test.local.active.yaml"
    docker_active = directory / "config.test.docker.active.yaml"
    directory.mkdir(parents=True, exist_ok=True)
    local_active.write_text(yaml.safe_dump(local, sort_keys=False))
    docker_active.write_text(yaml.safe_dump(docker, sort_keys=False))
    _load(local_active, env_file)
    _load(docker_active, env_file)
    shutil.copy2(config_file, backup)
    try:
        shutil.copy2(local_active, config_file)
    except Exception:
        shutil.copy2(backup, config_file)
        raise
    return state.ConfigState(
        backup=backup,
        local=local_active,
        docker=docker_active,
        env=env_file,
    )


def restore(environment_state: state.EnvironmentState) -> None:
    if environment_state.config.backup.exists():
        shutil.copy2(
            environment_state.config.backup,
            environment_state.worktree / "config.test.yaml",
        )
