"""Sanity-check that AppConfig can be built from the current env/YAML.

Builds the same config object the app and Alembic use at startup, without
importing the rest of the app (routes, DB engine, etc). Catches
misconfigured/missing env vars and YAML fast, with a clear error instead of
a stack trace buried in a uvicorn or alembic import chain.

Usage:
    uv run python -m cli.config.check
    YAML_CONFIG_FILE=deploy/railway/config.yaml ENV_FILE=.env.railway uv run python -m cli.config.check
"""

import os
import sys


def main() -> int:
    yaml_file = os.environ.get("YAML_CONFIG_FILE", "config.yaml")
    env_file = os.environ.get("ENV_FILE", ".env")
    print(f"YAML_CONFIG_FILE = {yaml_file}")
    print(f"ENV_FILE         = {env_file}")
    print()

    from backend.config import ConfigException, get_app_config, secret_preview  # noqa: PLC0415

    try:
        config = get_app_config()
    except ConfigException as error:
        print("AppConfig FAILED to build:\n")
        print(str(error).removeprefix("AppConfig validation failed:\n"))
        return 1

    print("AppConfig built successfully:\n")
    print(f"  env                = {config.env}")
    print(f"  backend_host:port  = {config.backend_host}:{config.backend_port}")
    print()
    print(f"  database.host:port = {config.database.host}:{config.database.port}")
    print(f"  database.db/user   = {config.database.db} / {config.database.user}")
    print()
    print(f"  migrator.host:port = {config.migrator.host}:{config.migrator.port}")
    print(f"  migrator.db/user   = {config.migrator.db} / {config.migrator.user}")
    print()
    print(f"  storage.storage_root = {config.storage.storage_root}")
    print()
    print(f"  frontend = {config.frontend}")
    print()
    if config.auth is None:
        print("  auth = None (auth-protected routes will not work)")
    else:
        print(f"  auth.jwt_secret       = {secret_preview(config.auth.jwt_secret)}")
        print(f"  auth.google enabled   = {config.auth.google is not None}")
        print(f"  auth.redirect_uri     = {config.auth.redirect_uri}")
        print(f"  auth.bootstrap_admin  = {config.auth.bootstrap_admin_email}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
