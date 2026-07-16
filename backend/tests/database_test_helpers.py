"""Shared helpers for the database layer test suite.

Tests run against an in-memory SQLite database rather than a live
PostgreSQL/TimescaleDB instance, for speed and isolation. This is
possible because:

    - :class:`app.database.types.GUID` transparently falls back to a
      portable ``CHAR(32)`` representation on non-PostgreSQL dialects.
    - ``sensor_readings.raw_value`` / ``system_events.context`` use
      the generic, cross-dialect ``sqlalchemy.JSON`` type.

TimescaleDB-specific behavior (``create_hypertable()``) is exercised
separately via the Alembic migration's offline SQL dry run, not via
these unit tests, since SQLite has no TimescaleDB equivalent.

Not a pytest ``conftest.py`` on purpose (imported explicitly by the
database test modules) so it does not interfere with the top-level
``tests/conftest.py`` FastAPI fixtures.
"""

from __future__ import annotations

from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database import models  # noqa: F401  (ensures models are registered on Base.metadata)


def build_test_session_factory() -> sessionmaker[Session]:
    """Create a fresh in-memory SQLite engine/schema and session factory.

    Uses ``StaticPool`` with ``check_same_thread=False`` so that the
    single underlying in-memory SQLite connection is shared across
    threads. Without this, SQLAlchemy's default per-thread pooling for
    ``:memory:`` databases gives each thread its own, separate, empty
    database - which would silently break any test that touches the
    database from a background thread (e.g. the serial ingestion
    worker tests).

    Returns:
        A :class:`sessionmaker` bound to a brand-new in-memory SQLite
        database with all tables created.
    """
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def make_session() -> Session:
    """Create a single, ready-to-use session against a fresh SQLite database.

    Returns:
        A new :class:`Session` bound to a fresh in-memory database.
    """
    factory = build_test_session_factory()
    return factory()


def session_scope_factory_for(factory: sessionmaker[Session]):
    """Build a ``session_scope``-compatible callable bound to a test factory.

    Mirrors the commit/rollback/close semantics of
    :func:`app.database.session.session_scope` so
    :class:`app.database.service.DatabaseService` can be tested
    end-to-end against SQLite without touching the real (PostgreSQL)
    engine at all.

    Args:
        factory: The test :class:`sessionmaker` to wrap.

    Returns:
        A zero-argument callable returning a context manager that
        yields a :class:`Session`.
    """
    from contextlib import contextmanager

    @contextmanager
    def _session_scope() -> Iterator[Session]:
        session = factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    return _session_scope
