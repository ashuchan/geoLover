"""Root test fixtures shared across all test modules.

PostgreSQL and Redis are provided via testcontainers so tests are fully
hermetic — no external services required.

The ``db_session`` fixture wires up a fresh schema per test (via DDL rollback
at the transaction level) and injects tenant RLS variables so ORM queries work.
"""

from __future__ import annotations

import asyncio
import base64
import os
import uuid
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base, RequestContext, _inject_rls_variables, build_session_factory
from app.core.events import EventBus


# ── Encryption test key ───────────────────────────────────────────────────────

TEST_MASTER_KEY_B64 = base64.b64encode(os.urandom(32)).decode()

# ── Default test tenant/user IDs ──────────────────────────────────────────────

DEFAULT_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
DEFAULT_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")


@pytest.fixture(scope="session")
def default_tenant_id() -> uuid.UUID:
    return DEFAULT_TENANT_ID


@pytest.fixture(scope="session")
def default_user_id() -> uuid.UUID:
    return DEFAULT_USER_ID


@pytest.fixture
def default_ctx() -> RequestContext:
    return RequestContext(
        tenant_id=DEFAULT_TENANT_ID,
        user_id=DEFAULT_USER_ID,
        is_platform_admin=False,
    )


@pytest.fixture
def admin_ctx() -> RequestContext:
    return RequestContext(
        tenant_id=DEFAULT_TENANT_ID,
        user_id=DEFAULT_USER_ID,
        is_platform_admin=True,
    )


# ── In-memory SQLite engine for unit tests ────────────────────────────────────
# Avoids testcontainers overhead for pure unit tests that just need an ORM session.


@pytest_asyncio.fixture
async def sqlite_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def sqlite_session(sqlite_engine) -> AsyncGenerator[AsyncSession, None]:
    factory = build_session_factory(sqlite_engine)
    async with factory() as session:
        yield session


# ── Testcontainers PostgreSQL (integration tests) ─────────────────────────────


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: marks tests as integration tests (require Docker)",
    )


@pytest.fixture(scope="session")
def postgres_container():
    """Start a PostgreSQL 16 container for the test session."""
    try:
        from testcontainers.postgres import PostgresContainer

        with PostgresContainer("postgres:16-alpine") as pg:
            yield pg
    except ImportError:
        pytest.skip("testcontainers not installed")


@pytest.fixture(scope="session")
def postgres_url(postgres_container) -> str:
    return postgres_container.get_connection_url().replace(
        "postgresql://", "postgresql+asyncpg://"
    )


@pytest_asyncio.fixture(scope="session")
async def pg_engine(postgres_url):
    engine = create_async_engine(postgres_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def pg_session(pg_engine, default_ctx: RequestContext) -> AsyncGenerator[AsyncSession, None]:
    """Provide a transaction-rolled-back session so each test is isolated."""
    async with pg_engine.connect() as conn:
        await conn.begin()
        session = AsyncSession(bind=conn, expire_on_commit=False)
        try:
            # Inject RLS variables so tenant-filtered queries work
            await _inject_rls_variables(conn, default_ctx)
            yield session
        finally:
            await session.close()
            await conn.rollback()


# ── Isolated EventBus fixture ─────────────────────────────────────────────────


@pytest.fixture
def event_bus() -> EventBus:
    bus = EventBus()
    yield bus
    bus.clear()


# ── Encryption key fixture ────────────────────────────────────────────────────


@pytest.fixture
def master_key_b64() -> str:
    return TEST_MASTER_KEY_B64
