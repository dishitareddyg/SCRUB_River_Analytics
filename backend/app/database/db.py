"""Database engine and connection management.

This module is responsible for creating and owning the single
SQLAlchemy :class:`~sqlalchemy.engine.Engine` instance used by the
application, and for exposing a small connection-manager style API
that ``main.py`` uses during application startup/shutdown to verify
connectivity to PostgreSQL/TimescaleDB.

No ORM models or tables are defined here - see
:mod:`app.database.base` for the declarative base that future models
will inherit from.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.config.settings import get_settings
from app.utils.exceptions import DatabaseError
from app.utils.logger import get_logger

logger = get_logger(__name__)

_engine: Engine | None = None


def get_engine() -> Engine:
    """Return the process-wide SQLAlchemy engine, creating it if needed.

    The engine is created lazily (on first use) and cached for the
    lifetime of the process. Connection pool sizing is driven entirely
    by :class:`app.config.settings.Settings`.

    Returns:
        The shared SQLAlchemy :class:`Engine` instance.

    Raises:
        DatabaseError: If the engine cannot be constructed (e.g. an
            invalid database URL).
    """
    global _engine

    if _engine is not None:
        return _engine

    settings = get_settings()

    try:
        _engine = create_engine(
            settings.database_url,
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            echo=settings.database_echo,
            pool_pre_ping=True,
            future=True,
        )
        logger.info("Database engine created successfully.")
        return _engine
    except SQLAlchemyError as exc:  # pragma: no cover - defensive
        logger.error(f"Failed to create database engine: {exc}")
        raise DatabaseError(f"Failed to create database engine: {exc}") from exc


@contextmanager
def get_connection() -> Iterator[object]:
    """Context manager yielding a raw database connection.

    Intended for low-level operations (e.g. connectivity checks)
    outside of the ORM session lifecycle.

    Yields:
        A SQLAlchemy :class:`~sqlalchemy.engine.Connection`.

    Raises:
        DatabaseError: If a connection cannot be established.
    """
    engine = get_engine()
    try:
        with engine.connect() as connection:
            yield connection
    except SQLAlchemyError as exc:
        logger.error(f"Database connection error: {exc}")
        raise DatabaseError(f"Database connection error: {exc}") from exc


def check_database_connection() -> bool:
    """Verify that the configured database is reachable.

    Executes a trivial ``SELECT 1`` to confirm connectivity. This is
    used by the application startup routine and the ``/health``
    endpoint; it never raises - failures are logged and reported as
    ``False`` so the API can report a degraded health status instead
    of crashing the whole process.

    Returns:
        ``True`` if the database responded successfully, ``False``
        otherwise.
    """
    try:
        with get_connection() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except DatabaseError:
        return False


def dispose_engine() -> None:
    """Dispose of the SQLAlchemy engine and release pooled connections.

    Intended to be called during application shutdown.
    """
    global _engine

    if _engine is not None:
        _engine.dispose()
        logger.info("Database engine disposed.")
        _engine = None
