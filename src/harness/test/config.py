"""Validate and patch test configuration."""

import shutil
from pathlib import Path

import yaml
from platformdirs import user_cache_path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CONFIG_TEST = _REPO_ROOT / "config.test.yaml"
_CONFIG_TEST_BAK = (
    user_cache_path("menelao") / "harness" / _REPO_ROOT.name / "config.test.yaml.bak"
)
_ENV_TEST = _REPO_ROOT / ".env.test"


class ConfigError(RuntimeError):
    """Raised when test configuration is missing or invalid."""


def validate() -> None:
    """Check that .env.test and config.test.yaml exist and are readable."""
    missing = []
    for path, label in ((_ENV_TEST, ".env.test"), (_CONFIG_TEST, "config.test.yaml")):
        if not path.exists():
            missing.append(f"  {label} not found at {path}")
    if missing:
        raise ConfigError(
            "Test configuration is incomplete:\n" + "\n".join(missing) + "\n\n"
            "Copy .env.test.example → .env.test and ensure config.test.yaml exists."
        )

    try:
        data = yaml.safe_load(_CONFIG_TEST.read_text())
    except yaml.YAMLError as e:
        raise ConfigError(f"config.test.yaml is not valid YAML: {e}") from e

    if not isinstance(data, dict):
        raise ConfigError("config.test.yaml must be a YAML mapping.")

    for key in ("database", "migrator"):
        if key not in data or not isinstance(data[key], dict):
            raise ConfigError(f"config.test.yaml: missing or invalid '{key}' section.")
        if "port" not in data[key]:
            raise ConfigError(f"config.test.yaml: missing '{key}.port'.")


def backup() -> None:
    """Create a backup of config.test.yaml."""
    _CONFIG_TEST_BAK.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_CONFIG_TEST, _CONFIG_TEST_BAK)


def patch_port(port: int) -> None:
    """Write `port` into config.test.yaml for both database and migrator sections."""
    data = yaml.safe_load(_CONFIG_TEST.read_text())
    data["database"]["port"] = port
    data["migrator"]["port"] = port
    _CONFIG_TEST.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))


def restore() -> None:
    """Restore config.test.yaml from backup and remove the backup file."""
    if _CONFIG_TEST_BAK.exists():
        shutil.move(str(_CONFIG_TEST_BAK), str(_CONFIG_TEST))
