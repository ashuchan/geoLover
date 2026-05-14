"""Async SQLAlchemy engine factory with Row-Level Security (RLS) injection.

Every connection acquired through :func:`get_db_session` will have four
session-local Postgres variables set before any application query runs:

    app.current_tenant      — UUID of the active tenant
    app.current_user_id     — UUID of the authenticated user
    app.current_business_scope — comma-separated UUID list (empty = all)
    app.is_platform_admin   — 'true' | 'false'

Using ``set_config(..., true)`` makes the variable transaction-local: it is
automatically cleared when the connection is returned to the pool, so there
is zero risk of one tenant's context leaking to the next request.

Two separate engine pools are supported:
  - ``main`` pool  — connects as ``citedby_app`` (full CRUD within RLS)
  - ``public_audit`` pool — connects as ``citedby_public_audit`` (SELECT-only,
    for the free-audit public endpoints; no RLS variables required)
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import AsyncGenerator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.exceptions import TenantContextMissingError


# ── ORM base ──────────────────────────────────────────────────────────────────


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


# ── Request context ───────────────────────────────────────────────────────────


@dataclass(slots=True, frozen=True)
class RequestContext:
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    is_platform_admin: bool = False
    business_scope_ids: list[uuid.UUID] = field(default_factory=list)

    @property
    def business_scope_str(self) -> str:
        return ",".join(str(bid) for bid in self.business_scope_ids)


# ── Engine factory ────────────────────────────────────────────────────────────


def build_engine(
    dsn: str,
    *,
    pool_min_size: int = 5,
    pool_max_size: int = 20,
    pool_max_inactive_connection_lifetime: float = 300.0,
    echo: bool = False,
) -> AsyncEngine:
    return create_async_engine(
        dsn,
        echo=echo,
        pool_pre_ping=True,
        pool_size=pool_min_size,
        max_overflow=pool_max_size - pool_min_size,
        pool_recycle=int(pool_max_inactive_connection_lifetime),
    )


# ── RLS session variable injection ───────────────────────────────────────────


_SET_RLS_SQL = text(
    "SELECT set_config('app.current_tenant',        :tenant_id,      true),"
    "       set_config('app.current_user_id',       :user_id,        true),"
    "       set_config('app.current_business_scope',:business_scope, true),"
    "       set_config('app.is_platform_admin',     :is_admin,       true)"
)


async def _inject_rls_variables(conn: AsyncConnection, ctx: RequestContext) -> None:
    await conn.execute(
        _SET_RLS_SQL,
        {
            "tenant_id": str(ctx.tenant_id),
            "user_id": str(ctx.user_id),
            "business_scope": ctx.business_scope_str,
            "is_admin": "true" if ctx.is_platform_admin else "false",
        },
    )


# ── Session factories ─────────────────────────────────────────────────────────


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )


@asynccontextmanager
async def get_db_session(
    session_factory: async_sessionmaker[AsyncSession],
    ctx: RequestContext,
) -> AsyncGenerator[AsyncSession, None]:
    """Yield a session with RLS variables set for *ctx*.

    Commits on clean exit; rolls back on exception.
    """
    async with session_factory() as session:
        try:
            await _inject_rls_variables(await session.connection(), ctx)
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def get_public_audit_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    """Yield a read-only session for the public-audit pool (no RLS variables needed)."""
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ── Singleton engine holders (wired up by lifespan) ──────────────────────────


class DatabaseManager:
    """Holds engine references; initialised once at application startup."""

    def __init__(self) -> None:
        self._main_engine: AsyncEngine | None = None
        self._public_audit_engine: AsyncEngine | None = None
        self._main_factory: async_sessionmaker[AsyncSession] | None = None
        self._public_audit_factory: async_sessionmaker[AsyncSession] | None = None

    def init(
        self,
        main_dsn: str,
        *,
        public_audit_dsn: str | None = None,
        echo: bool = False,
        main_pool_min: int = 5,
        main_pool_max: int = 20,
        audit_pool_min: int = 2,
        audit_pool_max: int = 5,
    ) -> None:
        self._main_engine = build_engine(
            main_dsn,
            pool_min_size=main_pool_min,
            pool_max_size=main_pool_max,
            echo=echo,
        )
        self._main_factory = build_session_factory(self._main_engine)

        if public_audit_dsn:
            self._public_audit_engine = build_engine(
                public_audit_dsn,
                pool_min_size=audit_pool_min,
                pool_max_size=audit_pool_max,
                echo=echo,
            )
            self._public_audit_factory = build_session_factory(self._public_audit_engine)

    async def close(self) -> None:
        if self._main_engine:
            await self._main_engine.dispose()
        if self._public_audit_engine:
            await self._public_audit_engine.dispose()

    @asynccontextmanager
    async def session(self, ctx: RequestContext) -> AsyncGenerator[AsyncSession, None]:
        if self._main_factory is None:
            raise RuntimeError("DatabaseManager not initialised; call .init() first")
        async with get_db_session(self._main_factory, ctx) as s:
            yield s

    @asynccontextmanager
    async def public_audit_session(self) -> AsyncGenerator[AsyncSession, None]:
        if self._public_audit_factory is None:
            raise RuntimeError(
                "Public audit pool not configured; set PUBLIC_AUDIT_DATABASE_URL. "
                "The public audit session must use the restricted citedby_public_audit role."
            )
        async with get_public_audit_session(self._public_audit_factory) as s:
            yield s

    @property
    def main_engine(self) -> AsyncEngine:
        if self._main_engine is None:
            raise RuntimeError("DatabaseManager not initialised")
        return self._main_engine


db_manager = DatabaseManager()
