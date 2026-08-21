import hashlib
import shutil
import subprocess
import tempfile
from datetime import datetime
from enum import Enum
from pathlib import Path

import yaml
from platformdirs import user_cache_path
from pydantic import BaseModel, Field


class EnvironmentMode(str, Enum):
    LOCAL = "local"
    DOCKER = "docker"


class PortState(BaseModel):
    database: int = Field(ge=1, le=65535)
    backend: int | None = Field(default=None, ge=1, le=65535)
    openwebui: int | None = Field(default=None, ge=1, le=65535)


class ConfigState(BaseModel):
    backup: Path
    local: Path
    docker: Path
    env: Path


class EnvironmentState(BaseModel):
    version: int = 1
    worktree: Path
    mode: EnvironmentMode
    status: str
    created_at: datetime
    compose_project: str
    ports: PortState
    config: ConfigState


def worktree_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return Path(result.stdout.strip()).resolve()
    return Path.cwd().resolve()


def state_dir(root: Path | None = None) -> Path:
    root = root or worktree_root()
    digest = hashlib.blake2s(str(root).encode(), digest_size=5).hexdigest()
    return user_cache_path("menelao") / "harness" / f"{root.name}_{digest}"


def project_name(root: Path | None = None) -> str:
    return f"menelao_harness_{state_dir(root).name.rsplit('_', 1)[1]}"


def state_path(root: Path | None = None) -> Path:
    return state_dir(root) / "state.yaml"


def read(root: Path | None = None) -> EnvironmentState | None:
    path = state_path(root)
    if not path.exists():
        return None
    return EnvironmentState.model_validate(yaml.safe_load(path.read_text()))


def write(environment_state: EnvironmentState, root: Path | None = None) -> None:
    path = state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as file:
        yaml.safe_dump(environment_state.model_dump(mode="json"), file, sort_keys=False)
        temporary = Path(file.name)
    temporary.replace(path)


def clear(root: Path | None = None) -> None:
    directory = state_dir(root)
    if directory.exists():
        shutil.rmtree(directory)
