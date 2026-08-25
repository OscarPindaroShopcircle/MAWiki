"""Application-wide logging setup.

Called once from ``create_app`` so every module's ``getLogger(__name__)``
inherits the same handlers and level — no per-module configuration needed.

Two output modes:
- **text** (default): human-readable ``TIME [LEVEL] name: message`` on stdout.
- **json** (``json_mode: true``): one JSON object per line on stdout, easy to
  ingest in Railway, Datadog, etc.

Structured logging
------------------
Use ``get_logger(__name__)`` instead of ``logging.getLogger(__name__)`` to
get a logger that accepts arbitrary keyword arguments. Pydantic models are
auto-serialized via ``.model_dump(mode="json")``::

    from src.backend.log import get_logger

    logger = get_logger(__name__)
    logger.info("User logged in", user_id="abc", user=user_model)

Extra fields appear in the JSON output (or appended in text mode).

Uvicorn manages its own ``uvicorn.access`` and ``uvicorn.error`` loggers — we
don't touch them. Access logs appear as uvicorn's native format.
"""

from __future__ import annotations

import json
import logging
from typing import Any

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _serialize(value: Any) -> Any:
    """Convert a value for logging — Pydantic models → dict, else identity."""
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


_STANDARD_RECORD_ATTRS = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__
)

# ``logging.Formatter.format()`` mutates the record in-place, adding these.
# They must be excluded so they don't leak into the "extra fields" output.
_FORMATTER_SIDE_EFFECTS = frozenset({"message", "asctime"})

_EXCLUDE_FROM_EXTRAS = _STANDARD_RECORD_ATTRS | _FORMATTER_SIDE_EFFECTS


def _extra_fields(record: logging.LogRecord) -> dict[str, Any]:
    """Return any user-supplied keys on *record* that aren't stdlib or formatter attrs."""
    return {k: v for k, v in record.__dict__.items() if k not in _EXCLUDE_FROM_EXTRAS}


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------


class _JsonFormatter(logging.Formatter):
    """Emit each record as a single-line JSON object, including extra fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(_extra_fields(record))
        return json.dumps(payload, default=str)


class _TextFormatter(logging.Formatter):
    """Like the default, but appends extra fields as ``key=value`` pairs."""

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = _extra_fields(record)
        if not extras:
            return base
        parts = [f"{k}={_serialize(v)!r}" for k, v in extras.items()]
        return f"{base} | {' '.join(parts)}"


_TEXT_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT = "%d-%m-%Y %H:%M:%S"


# ---------------------------------------------------------------------------
# Structured logger
# ---------------------------------------------------------------------------


class StructuredLogger:
    """Thin wrapper around a stdlib ``Logger`` that accepts ``**kwargs``.

    Pydantic models are auto-serialized. All kwargs end up in the log record's
    ``extra`` dict and appear in both JSON and text output.
    """

    __slots__ = ("_logger",)

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def _log(self, level: int, msg: str, **kwargs: Any) -> None:
        extra = {k: _serialize(v) for k, v in kwargs.items()}
        self._logger.log(level, msg, extra=extra)

    def debug(self, msg: str, **kwargs: Any) -> None:
        self._log(logging.DEBUG, msg, **kwargs)

    def info(self, msg: str, **kwargs: Any) -> None:
        self._log(logging.INFO, msg, **kwargs)

    def warning(self, msg: str, **kwargs: Any) -> None:
        self._log(logging.WARNING, msg, **kwargs)

    def error(self, msg: str, **kwargs: Any) -> None:
        self._log(logging.ERROR, msg, **kwargs)

    def exception(self, msg: str, **kwargs: Any) -> None:
        self._log(logging.ERROR, msg, **kwargs, exc_info=True)


def get_logger(name: str) -> StructuredLogger:
    """Return a structured logger for *name*.

    Use this instead of ``logging.getLogger(name)`` when you want to pass
    extra fields as keyword arguments.
    """
    return StructuredLogger(logging.getLogger(name))


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


def setup_logging(
    level: str = "INFO",
    *,
    json_mode: bool = False,
) -> None:
    """Configure the root logger with a console handler.

    Idempotent — safe to call multiple times (e.g. tests creating the app
    more than once). Subsequent calls replace handlers on the root logger.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(log_level)

    # Remove any existing handlers we added so re-configuring doesn't
    # duplicate lines (e.g. when tests create the app twice).
    for handler in list(root.handlers):
        if getattr(handler, "_app_handler", False):
            root.removeHandler(handler)

    if json_mode:
        formatter = _JsonFormatter()
    else:
        formatter = _TextFormatter(_TEXT_FORMAT, datefmt=_DATE_FORMAT)

    console = logging.StreamHandler()
    console.setLevel(log_level)
    console.setFormatter(formatter)
    console._app_handler = True  # type: ignore[attr-defined]
    root.addHandler(console)

    # Quiet down noisy third-party loggers that aren't useful at INFO.
    # uvicorn.access is NOT silenced — HTTP access logs are useful in production.
    _NOISY = (
        "httpx",
        "httpcore",
        "watchfiles",
    )
    for name in _NOISY:
        logging.getLogger(name).setLevel(logging.WARNING)
