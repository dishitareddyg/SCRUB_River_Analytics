"""Alembic migration environment.

This file wires Alembic into the application's centralized settings
(`app.config.settings.get_settings`) and declarative base
(`app.database.base.Base`) so that:

    * The database URL never needs to be duplicated in `alembic.ini`.
    * `alembic revision --autogenerate` can detect model changes as
      soon as future modules add ORM models under
      `app/database/models.py` (imported below once it exists).
"""

import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# Make the `app` package importable when Alembic is invoked from the
# `backend/` directory.
sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.config.settings import get_settings  # noqa: E402
from app.database.base import Base  # noqa: E402

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Override the sqlalchemy.url from alembic.ini with the URL from our
# centralized application settings, so there is a single source of
# truth for the database connection string.
config.set_main_option("sqlalchemy.url", get_settings().database_url)

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import ORM models so Base.metadata is populated before autogenerate
# runs. Future modules should add their own model imports here.
from app.database import models  # noqa: E402,F401

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emits SQL without a live DB)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (connects to the live database)."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
