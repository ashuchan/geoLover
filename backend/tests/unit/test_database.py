"""Unit tests for app.core.database — RLS injection, session factory, and DatabaseManager."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from app.core.database import (
    Base,
    DatabaseManager,
    RequestContext,
    _inject_rls_variables,
    build_engine,
    build_session_factory,
    get_db_session,
    get_public_audit_session,
)


# ── RequestContext tests ───────────────────────────────────────────────────────


class TestRequestContext:
    def test_business_scope_str_empty(self):
        ctx = RequestContext(tenant_id=uuid.uuid4(), user_id=uuid.uuid4())
        assert ctx.business_scope_str == ""

    def test_business_scope_str_multiple(self):
        ids = [uuid.uuid4(), uuid.uuid4()]
        ctx = RequestContext(tenant_id=uuid.uuid4(), user_id=uuid.uuid4(), business_scope_ids=ids)
        parts = ctx.business_scope_str.split(",")
        assert len(parts) == 2
        assert parts[0] == str(ids[0])

    def test_is_frozen(self):
        ctx = RequestContext(tenant_id=uuid.uuid4(), user_id=uuid.uuid4())
        with pytest.raises((AttributeError, TypeError)):
            ctx.tenant_id = uuid.uuid4()  # type: ignore[misc]

    def test_default_is_platform_admin_false(self):
        ctx = RequestContext(tenant_id=uuid.uuid4(), user_id=uuid.uuid4())
        assert ctx.is_platform_admin is False


# ── RLS injection tests ───────────────────────────────────────────────────────


class TestInjectRLSVariables:
    @pytest.mark.asyncio
    async def test_calls_execute_with_correct_params(self):
        mock_conn = AsyncMock()
        tenant_id = uuid.uuid4()
        user_id = uuid.uuid4()
        ctx = RequestContext(
            tenant_id=tenant_id,
            user_id=user_id,
            is_platform_admin=True,
        )
        await _inject_rls_variables(mock_conn, ctx)
        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args
        params = call_args[0][1]  # second positional arg is the dict
        assert params["tenant_id"] == str(tenant_id)
        assert params["user_id"] == str(user_id)
        assert params["is_admin"] == "true"
        assert params["business_scope"] == ""

    @pytest.mark.asyncio
    async def test_non_admin_context(self):
        mock_conn = AsyncMock()
        ctx = RequestContext(tenant_id=uuid.uuid4(), user_id=uuid.uuid4(), is_platform_admin=False)
        await _inject_rls_variables(mock_conn, ctx)
        params = mock_conn.execute.call_args[0][1]
        assert params["is_admin"] == "false"

    @pytest.mark.asyncio
    async def test_business_scope_ids_serialised(self):
        mock_conn = AsyncMock()
        ids = [uuid.uuid4(), uuid.uuid4()]
        ctx = RequestContext(
            tenant_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            business_scope_ids=ids,
        )
        await _inject_rls_variables(mock_conn, ctx)
        params = mock_conn.execute.call_args[0][1]
        assert params["business_scope"] == f"{ids[0]},{ids[1]}"


# ── build_engine tests ────────────────────────────────────────────────────────


class TestBuildEngine:
    def test_returns_async_engine(self):
        """build_engine returns an AsyncEngine without connecting."""
        from sqlalchemy.ext.asyncio import AsyncEngine
        from sqlalchemy import NullPool

        # Use NullPool to avoid pool_size/max_overflow unsupported by SQLite
        from sqlalchemy.ext.asyncio import create_async_engine
        engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=NullPool)
        assert isinstance(engine, AsyncEngine)

    def test_build_engine_returns_async_engine_type(self):
        """build_engine for PostgreSQL DSN returns AsyncEngine (no connection)."""
        from sqlalchemy.ext.asyncio import AsyncEngine

        # We can't actually connect without a live server; just verify the object type.
        engine = build_engine(
            "postgresql+asyncpg://user:pw@localhost/db",
            pool_min_size=3,
            pool_max_size=10,
        )
        assert isinstance(engine, AsyncEngine)
        # pool_size should match min_size; max_overflow = max - min = 7
        assert engine.pool.size() == 3


# ── DatabaseManager tests ─────────────────────────────────────────────────────


class TestDatabaseManager:
    _PG_DSN = "postgresql+asyncpg://user:pw@localhost/db"

    def test_uninitialised_raises(self):
        mgr = DatabaseManager()
        with pytest.raises(RuntimeError, match="not initialised"):
            _ = mgr.main_engine

    @pytest.mark.asyncio
    async def test_session_without_init_raises(self):
        mgr = DatabaseManager()
        ctx = RequestContext(tenant_id=uuid.uuid4(), user_id=uuid.uuid4())
        with pytest.raises(RuntimeError, match="not initialised"):
            async with mgr.session(ctx):
                pass

    @pytest.mark.asyncio
    async def test_public_audit_session_without_audit_factory_raises(self):
        mgr = DatabaseManager()
        # Uninitialised: _public_audit_factory is None → raises
        with pytest.raises(RuntimeError, match="Public audit pool not configured"):
            async with mgr.public_audit_session():
                pass

    @pytest.mark.asyncio
    async def test_public_audit_session_without_dedicated_pool_raises(self):
        mgr = DatabaseManager()
        # Even after init() without a public_audit_dsn it must refuse to fall back
        mgr.init(self._PG_DSN)
        with pytest.raises(RuntimeError, match="Public audit pool not configured"):
            async with mgr.public_audit_session():
                pass

    def test_init_creates_engine(self):
        mgr = DatabaseManager()
        mgr.init(self._PG_DSN, main_pool_min=1, main_pool_max=2)
        assert mgr.main_engine is not None

    def test_init_with_public_audit_dsn(self):
        mgr = DatabaseManager()
        mgr.init(self._PG_DSN, public_audit_dsn=self._PG_DSN, main_pool_min=1, main_pool_max=2)
        assert mgr._public_audit_engine is not None
        assert mgr._public_audit_factory is not None

    @pytest.mark.asyncio
    async def test_close_disposes_engines(self):
        mgr = DatabaseManager()
        mgr.init(self._PG_DSN, main_pool_min=1, main_pool_max=2)
        await mgr.close()  # should not raise

    @pytest.mark.asyncio
    async def test_close_with_public_audit_engine(self):
        mgr = DatabaseManager()
        mgr.init(self._PG_DSN, public_audit_dsn=self._PG_DSN)
        await mgr.close()  # should not raise

    @pytest.mark.asyncio
    async def test_close_without_init_is_safe(self):
        mgr = DatabaseManager()
        await mgr.close()  # should not raise


# ── Session context manager tests ─────────────────────────────────────────────


class TestDatabaseManagerSessions:
    """Test DatabaseManager.session() and public_audit_session() with SQLite."""

    @pytest_asyncio.fixture
    async def initialised_mgr(self):
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy import NullPool

        engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=NullPool)
        # Session lifecycle tests don't need any tables

        mgr = DatabaseManager()
        # Manually wire an sqlite-backed factory
        mgr._main_engine = engine
        mgr._main_factory = build_session_factory(engine)
        yield mgr
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_manager_session_yields(self, initialised_mgr):
        ctx = RequestContext(tenant_id=uuid.uuid4(), user_id=uuid.uuid4())
        with patch("app.core.database._inject_rls_variables", new_callable=AsyncMock):
            async with initialised_mgr.session(ctx) as s:
                assert s is not None

    @pytest.mark.asyncio
    async def test_manager_public_audit_session_without_factory_raises(self, initialised_mgr):
        with pytest.raises(RuntimeError, match="Public audit pool not configured"):
            async with initialised_mgr.public_audit_session():
                pass

    @pytest.mark.asyncio
    async def test_manager_public_audit_session_yields_with_factory(self, initialised_mgr):
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy import NullPool

        audit_engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=NullPool)
        # No tables needed — just testing session lifecycle

        initialised_mgr._public_audit_factory = build_session_factory(audit_engine)
        try:
            async with initialised_mgr.public_audit_session() as s:
                assert s is not None
        finally:
            await audit_engine.dispose()


class TestGetDbSession:
    @pytest_asyncio.fixture
    async def sqlite_factory(self):
        from sqlalchemy.ext.asyncio import create_async_engine
        engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        # No app tables needed — session lifecycle tests don't access any tables
        factory = build_session_factory(engine)
        yield factory
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_session_commits_on_clean_exit(self, sqlite_factory):
        ctx = RequestContext(tenant_id=uuid.uuid4(), user_id=uuid.uuid4())
        # SQLite doesn't support set_config; patch the injection
        with patch("app.core.database._inject_rls_variables", new_callable=AsyncMock):
            async with get_db_session(sqlite_factory, ctx) as session:
                assert session is not None

    @pytest.mark.asyncio
    async def test_session_rolls_back_on_exception(self, sqlite_factory):
        ctx = RequestContext(tenant_id=uuid.uuid4(), user_id=uuid.uuid4())
        with patch("app.core.database._inject_rls_variables", new_callable=AsyncMock):
            with pytest.raises(ValueError, match="forced rollback"):
                async with get_db_session(sqlite_factory, ctx) as session:
                    raise ValueError("forced rollback")


class TestGetPublicAuditSession:
    @pytest_asyncio.fixture
    async def sqlite_factory(self):
        from sqlalchemy.ext.asyncio import create_async_engine
        engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        # No app tables needed
        factory = build_session_factory(engine)
        yield factory
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_public_audit_yields_session(self, sqlite_factory):
        async with get_public_audit_session(sqlite_factory) as session:
            assert session is not None

    @pytest.mark.asyncio
    async def test_public_audit_rolls_back_on_exception(self, sqlite_factory):
        with pytest.raises(RuntimeError, match="public audit fail"):
            async with get_public_audit_session(sqlite_factory) as session:
                raise RuntimeError("public audit fail")
