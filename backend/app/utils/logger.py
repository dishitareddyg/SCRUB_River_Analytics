"""Industrial logging configuration built on Loguru.

Provides:

    * Console logging with color and a consistent format.
    * A rotating, daily-rotated application log file capturing all
      levels at/above the configured minimum level.
    * A dedicated rotating error log file capturing only ``ERROR`` and
      above, to make production triage fast.

Usage::

    from app.utils.logger import get_logger

    logger = get_logger(__name__)
    logger.info("Something happened")
"""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger as _loguru_logger

from app.config.constants import (
    LOG_APPLICATION_FILENAME,
    LOG_ERROR_FILENAME,
    LOG_RETENTION,
    LOG_ROTATION,
)
from app.config.settings import get_settings

_LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)

_configured = False


def configure_logging() -> None:
    """Configure Loguru sinks (console + rotating files).

    This function is idempotent: calling it more than once will not
    duplicate sinks. It is invoked once, automatically, the first
    time :func:`get_logger` is called (typically during application
    startup via ``main.py``).
    """
    global _configured

    if _configured:
        return

    settings = get_settings()

    log_folder = Path(settings.log_folder)
    log_folder.mkdir(parents=True, exist_ok=True)

    _loguru_logger.remove()  # Remove Loguru's default handler.

    # Console sink.
    _loguru_logger.add(
        sys.stderr,
        level=settings.log_level,
        format=_LOG_FORMAT,
        colorize=True,
        backtrace=settings.debug,
        diagnose=settings.debug,
    )

    # Rotating application log (all levels >= configured level).
    _loguru_logger.add(
        log_folder / LOG_APPLICATION_FILENAME,
        level=settings.log_level,
        format=_LOG_FORMAT,
        rotation=LOG_ROTATION,
        retention=LOG_RETENTION,
        enqueue=True,
        backtrace=False,
        diagnose=False,
        encoding="utf-8",
    )

    # Rotating error-only log.
    _loguru_logger.add(
        log_folder / LOG_ERROR_FILENAME,
        level="ERROR",
        format=_LOG_FORMAT,
        rotation=LOG_ROTATION,
        retention=LOG_RETENTION,
        enqueue=True,
        backtrace=True,
        diagnose=False,
        encoding="utf-8",
    )

    _configured = True
    _loguru_logger.info(
        f"Logging configured. level={settings.log_level} folder={log_folder.resolve()}"
    )


def get_logger(name: str) -> "_loguru_logger.__class__":  # type: ignore[name-defined]
    """Return a Loguru logger bound with a module name.

    Args:
        name: Typically ``__name__`` of the calling module, used to
            tag log lines with their origin.

    Returns:
        A Loguru logger instance bound with the ``name`` context.
    """
    configure_logging()
    return _loguru_logger.bind(module_name=name)
