"""Pre-commit hook: keep ``db/registry.py`` in sync with model classes."""

from .hook import app, cli, generate_registry, run_check

__all__ = ["app", "cli", "generate_registry", "run_check"]
