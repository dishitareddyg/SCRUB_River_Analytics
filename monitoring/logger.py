"""
monitoring/logger.py

Central logging configuration. Logs go to stdout, which systemd/journald
captures automatically (see systemd/lake-bot-backend.service) -- no extra
logging dependencies are needed.

Per spec section 46: do not spam logs (e.g. raw 100ms motor debug lines)
unless DEBUG logging is explicitly enabled via LOG_LEVEL=DEBUG.
"""

from __future__ import annotations

import logging
import sys

_CONFIGURED = False


def _configure_root() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    from config.settings import settings  # local import to avoid circular import at module load

    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    handler = logging.StreamHandler(stream=sys.stdout)
    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    _configure_root()
    return logging.getLogger(name)
