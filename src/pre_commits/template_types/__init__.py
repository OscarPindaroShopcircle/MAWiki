"""Static checker: Jinja template attribute access vs. Pydantic context models."""

from .hook import app, cli, run_check

__all__ = ["app", "cli", "run_check"]
