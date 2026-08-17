"""Application-wide logging setup.

Called once from ``create_app`` so every module's ``getLogger(__name__)``
inherits the same handlers and level — no per-module configuration needed.

Console handler only for now. File logging (rotation, multi-worker safety)
is a separate concern — when needed, prefer delegating to external tools
(``logrotate``, Docker log drivers, systemd journal) rather than in-process
handlers like ``RotatingFileHandler`` which corrupt when multiple workers
rotate simultaneously.

Uvicorn's own access logs are left untouched (it configures its own loggers).
"""

from __future__ import annotations

import logging

from .config import LoggingConfig

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT = "%d-%m-%Y %H:%M:%S"


def setup_logging(config: LoggingConfig) -> None:
    """Configure the root logger with a console handler.

    Idempotent — safe to call multiple times (e.g. tests creating the app
    more than once). Subsequent calls replace handlers on the root logger.
    """
    level = getattr(logging, config.level.upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)

    # Remove any existing handlers we added so re-configuring doesn't
    # duplicate lines (e.g. when tests create the app twice).
    for handler in list(root.handlers):
        if getattr(handler, "_app_handler", False):
            root.removeHandler(handler)

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(formatter)
    console._app_handler = True  # type: ignore[attr-defined]
    root.addHandler(console)

    # Quiet down noisy third-party loggers that aren't useful at INFO.
    for noisy in ("httpx", "httpcore", "watchfiles"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
