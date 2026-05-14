"""Unit tests for Ops repository layer (Phase 8)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.ops.models import (
    ImpersonationLog,
    QuotaEnforcementLog,
    StatusComponent,
    TenantGraceExtension,
)
from app.modules.ops.repository import (
    ImpersonationLogRepository,
    QuotaEnforcementLogRepository,
    StatusComponentRepository,
    TenantGraceExtensionRepository,
)


def _uuid():
    return uuid.uuid4()


def _now():
    return datetime.now(timezone.utc)


def _make_session():
    s = MagicMock()
    s.flush = AsyncMock()
    s.add = MagicMock()
    s.execute = AsyncMock()
    return s


def _make_scalars_result(items):
    scalars = MagicMock()
    scalars.all.return_value = items
    result = MagicMock()
    result.scalars.return_value = scalars
    result.scalar_one_or_none.return_value = items[0] if items else None
    return result


# ── QuotaEnforcementLogRepository ─────────────────────────────────────────────


class TestQuotaEnforcementLogRepository:
    @pytest.mark.asyncio
    async def test_create(self):
        session = _make_session()
        repo = QuotaEnforcementLogRepository(session)
        tenant_id = _uuid()

        result = await repo.create(
            tenant_id=tenant_id,
            quota_kind="audits",
            action="soft_warn",
            triggered_at=_now(),
        )
        session.add.assert_called_once()
        session.flush.assert_called_once()
        assert isinstance(result, QuotaEnforcementLog)

    @pytest.mark.asyncio
    async def test_list_for_tenant(self):
        session = _make_session()
        repo = QuotaEnforcementLogRepository(session)
        tenant_id = _uuid()
        log = MagicMock(spec=QuotaEnforcementLog)
        session.execute.return_value = _make_scalars_result([log])

        results = await repo.list_for_tenant(tenant_id)
        session.execute.assert_called_once()
        assert results == [log]

    @pytest.mark.asyncio
    async def test_list_recent(self):
        session = _make_session()
        repo = QuotaEnforcementLogRepository(session)
        log1 = MagicMock(spec=QuotaEnforcementLog)
        log2 = MagicMock(spec=QuotaEnforcementLog)
        session.execute.return_value = _make_scalars_result([log1, log2])

        results = await repo.list_recent(limit=10)
        session.execute.assert_called_once()
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_list_recent_no_tenant_filter(self):
        session = _make_session()
        repo = QuotaEnforcementLogRepository(session)
        session.execute.return_value = _make_scalars_result([])

        # Should not raise - no tenant_id needed
        results = await repo.list_recent()
        assert isinstance(results, list)


# ── TenantGraceExtensionRepository ────────────────────────────────────────────


class TestTenantGraceExtensionRepository:
    @pytest.mark.asyncio
    async def test_create(self):
        session = _make_session()
        repo = TenantGraceExtensionRepository(session)
        tenant_id = _uuid()
        user_id = _uuid()

        result = await repo.create(
            tenant_id=tenant_id,
            quota_kind="audits",
            extended_until=_now() + timedelta(days=7),
            extended_by_user_id=user_id,
        )
        session.add.assert_called_once()
        session.flush.assert_called_once()
        assert isinstance(result, TenantGraceExtension)

    @pytest.mark.asyncio
    async def test_get_active_returns_row(self):
        session = _make_session()
        repo = TenantGraceExtensionRepository(session)
        tenant_id = _uuid()
        grace = MagicMock(spec=TenantGraceExtension)
        session.execute.return_value = _make_scalars_result([grace])

        result = await repo.get_active(tenant_id, "audits", _now())
        assert result == grace

    @pytest.mark.asyncio
    async def test_get_active_returns_none_when_not_found(self):
        session = _make_session()
        repo = TenantGraceExtensionRepository(session)
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        session.execute.return_value = result_mock

        result = await repo.get_active(_uuid(), "audits", _now())
        assert result is None

    @pytest.mark.asyncio
    async def test_list_for_tenant(self):
        session = _make_session()
        repo = TenantGraceExtensionRepository(session)
        grace = MagicMock(spec=TenantGraceExtension)
        session.execute.return_value = _make_scalars_result([grace])

        results = await repo.list_for_tenant(_uuid())
        assert results == [grace]


# ── ImpersonationLogRepository ────────────────────────────────────────────────


class TestImpersonationLogRepository:
    @pytest.mark.asyncio
    async def test_create(self):
        session = _make_session()
        repo = ImpersonationLogRepository(session)

        result = await repo.create(
            admin_user_id=_uuid(),
            impersonated_tenant_id=_uuid(),
            reason="Support test",
        )
        session.add.assert_called_once()
        session.flush.assert_called_once()
        assert isinstance(result, ImpersonationLog)

    @pytest.mark.asyncio
    async def test_end_session(self):
        session = _make_session()
        repo = ImpersonationLogRepository(session)
        log_id = _uuid()

        await repo.end_session(log_id)
        session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_by_admin(self):
        session = _make_session()
        repo = ImpersonationLogRepository(session)
        log = MagicMock(spec=ImpersonationLog)
        session.execute.return_value = _make_scalars_result([log])

        results = await repo.list_by_admin(_uuid())
        assert results == [log]

    @pytest.mark.asyncio
    async def test_list_for_tenant(self):
        session = _make_session()
        repo = ImpersonationLogRepository(session)
        log = MagicMock(spec=ImpersonationLog)
        session.execute.return_value = _make_scalars_result([log])

        results = await repo.list_for_tenant(_uuid())
        assert results == [log]

    @pytest.mark.asyncio
    async def test_get_returns_log(self):
        session = _make_session()
        repo = ImpersonationLogRepository(session)
        log = MagicMock(spec=ImpersonationLog)
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = log
        session.execute.return_value = result_mock

        result = await repo.get(_uuid())
        assert result == log

    @pytest.mark.asyncio
    async def test_get_returns_none_when_not_found(self):
        session = _make_session()
        repo = ImpersonationLogRepository(session)
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        session.execute.return_value = result_mock

        result = await repo.get(_uuid())
        assert result is None


# ── StatusComponentRepository ──────────────────────────────────────────────────


class TestStatusComponentRepository:
    @pytest.mark.asyncio
    async def test_create(self):
        session = _make_session()
        repo = StatusComponentRepository(session)

        result = await repo.create(
            name="api",
            health_signal_query="error_rate_5m < 0.01",
        )
        session.add.assert_called_once()
        session.flush.assert_called_once()
        assert isinstance(result, StatusComponent)

    @pytest.mark.asyncio
    async def test_get_by_name_returns_component(self):
        session = _make_session()
        repo = StatusComponentRepository(session)
        component = MagicMock(spec=StatusComponent)
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = component
        session.execute.return_value = result_mock

        result = await repo.get_by_name("api")
        assert result == component

    @pytest.mark.asyncio
    async def test_get_by_name_returns_none_when_not_found(self):
        session = _make_session()
        repo = StatusComponentRepository(session)
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        session.execute.return_value = result_mock

        result = await repo.get_by_name("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_all(self):
        session = _make_session()
        repo = StatusComponentRepository(session)
        c1 = MagicMock(spec=StatusComponent)
        c2 = MagicMock(spec=StatusComponent)
        session.execute.return_value = _make_scalars_result([c1, c2])

        results = await repo.list_all()
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_update_state(self):
        session = _make_session()
        repo = StatusComponentRepository(session)
        component_id = _uuid()
        now = _now()

        await repo.update_state(component_id, "degraded", now)
        session.execute.assert_called_once()
