"""Cross-dialect UUID column type.

Production runs on PostgreSQL (where UUIDs are stored natively), but
the test suite runs against an in-memory SQLite database for speed
and isolation. This module provides a single :class:`GUID` type that
compiles to the native ``UUID`` type on PostgreSQL and to a
``CHAR(32)`` hex string on every other dialect, so ORM models never
need to know which database they are running against.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy import CHAR
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


class GUID(TypeDecorator):
    """Platform-independent UUID column type.

    Uses PostgreSQL's native ``UUID`` type when available, otherwise
    stores the UUID as a 32-character hex string (no dashes).
    """

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> Any:
        """Choose the underlying column implementation for the dialect.

        Args:
            dialect: The active SQLAlchemy dialect.

        Returns:
            A native ``UUID`` type descriptor on PostgreSQL, otherwise
            a ``CHAR(32)`` type descriptor.
        """
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PostgresUUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(32))

    def process_bind_param(self, value: Optional[Any], dialect: Dialect) -> Optional[Any]:
        """Convert a Python value into the form stored in the database.

        Args:
            value: A :class:`uuid.UUID`, a UUID string, or ``None``.
            dialect: The active SQLAlchemy dialect.

        Returns:
            The value to bind into the SQL statement.
        """
        if value is None:
            return None
        if dialect.name == "postgresql":
            return str(value)
        if not isinstance(value, uuid.UUID):
            value = uuid.UUID(str(value))
        return value.hex

    def process_result_value(self, value: Optional[Any], dialect: Dialect) -> Optional[uuid.UUID]:
        """Convert a stored database value back into a Python UUID.

        Args:
            value: The raw value read from the database.
            dialect: The active SQLAlchemy dialect.

        Returns:
            A :class:`uuid.UUID`, or ``None``.
        """
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(value)
