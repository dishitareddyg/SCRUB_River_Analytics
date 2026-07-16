"""SQLAlchemy session factory and FastAPI dependency.

Future API route modules will depend on :func:`get_db` to obtain a
transactional session scoped to a single request, e.g.::

    from fastapi import Depends
    from sqlalchemy.orm import Session
    from app.database.session import get_db

    @router.get("/example")
    def example(db: Session = Depends(get_db)):
        ...
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy.orm import Session, sessionmaker

from app.database.db import get_engine
from app.utils.exceptions import DatabaseError
from app.utils.logger import get_logger

logger = get_logger(__name__)

SessionLocal: sessionmaker[Session] = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=None,  # Bound lazily via get_engine() the first time a session is created.
    future=True,
)


def _bound_session_factory() -> sessionmaker[Session]:
    """Bind ``SessionLocal`` to the engine on first use and return it.

    Binding is deferred until the first session is actually requested
    so that importing this module never has the side effect of
    creating a database engine (or failing if the database is not yet
    reachable, e.g. during unit tests that don't touch the DB).

    Returns:
        The configured :class:`sessionmaker`.
    """
    if SessionLocal.kw.get("bind") is None:
        SessionLocal.configure(bind=get_engine())
    return SessionLocal


def get_db() -> Iterator[Session]:
    """FastAPI dependency that yields a request-scoped database session.

    The session is always closed after the request completes, even if
    an exception is raised while handling the request.

    Yields:
        An active SQLAlchemy :class:`Session`.
    """
    factory = _bound_session_factory()
    session = factory()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context manager providing a committed-or-rolled-back session.

    Intended for code that runs outside of a FastAPI request context
    (e.g. the database repository/service layer, or a background
    ingestion thread consuming packets from the serial module's
    queue), where ``Depends(get_db)`` is not available.

    On successful completion of the ``with`` block, the session is
    committed. If an exception is raised, the session is rolled back
    and the exception is re-raised (wrapped as :class:`DatabaseError`
    if it originated from SQLAlchemy). The session is always closed.

    Yields:
        An active SQLAlchemy :class:`Session`.

    Raises:
        DatabaseError: If committing or rolling back the session
            itself fails.
    """
    factory = _bound_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        try:
            session.rollback()
        except Exception as rollback_exc:  # pragma: no cover - defensive
            logger.error(f"Failed to roll back session after error: {rollback_exc}")
            raise DatabaseError(f"Failed to roll back session: {rollback_exc}") from rollback_exc
        raise
    finally:
        session.close()
