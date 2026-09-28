"""
monitoring/logger.py

Structured logging helper — thin wrapper around the standard logging
module.  Every module calls get_logger(__name__) exactly once and uses
the returned logger; the root level is set once from settings.
"""

from __future__ import annotations

import logging

from config.settings import settings


def get_logger(name: str) -> logging.Logger:
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    return logging.getLogger(name)
