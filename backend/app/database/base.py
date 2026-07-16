"""Declarative ORM base class.

All future SQLAlchemy models (e.g. sensor readings, analytics
results, prediction outputs) must inherit from :class:`Base` so that
Alembic autogeneration and metadata-driven table creation work
consistently across the project.

No models are defined in this backend foundation module.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models in the platform."""
