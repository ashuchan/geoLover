"""Alembic environment — async migrations with SQLAlchemy 2.0."""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.database import Base

# Import all models so Alembic can detect schema changes via autogenerate.
# Each phase adds its models here as they are implemented.
import app.modules  # noqa: F401  — registers all ORM models

config = context.config
fileConfig(config.config_file_name)  # type: ignore[arg-type]

target_metadata = Base.metadata


def _get_url() -> str:
    return os.environ.get("DATABASE_URL") or config.get_main_option("sqlalchemy.url", "")


def run_migrations_offline() -> None:
    context.configure(
        url=_get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(_get_url(), poolclass=pool.NullPool)
    async with engine.connect() as conn:
        await conn.run_sync(do_run_migrations)
    await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
