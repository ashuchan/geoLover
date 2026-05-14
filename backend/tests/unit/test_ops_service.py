"""Unit tests for Ops service layer (Phase 8)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.ops.models import (
    ImpersonationLog,
    QuotaEnforcementLog,
    StatusComponent,
    TenantGraceExtension,
)
from app.modules.ops.service import (
    AdminOpsService,
    ImpersonationEnded,
    ImpersonationStarted,
    QuotaBlocked,
    QuotaService,
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


def _make_log_entry(**kwargs):
    log = MagicMock(spec=QuotaEnforcementLog)
    log.id = kwargs.get("id", _uuid())
    log.tenant_id = kwargs.get("tenant_id", _uuid())
    log.quota_kind = kwargs.get("quota_kind", "audits")
    log.action = kwargs.get("action", "soft_warn")
    log.triggered_at = kwargs.get("triggered_at", _now())
    return log


def _make_grace(**kwargs):
    grace = MagicMock(spec=TenantGraceExtension)
    grace.id = kwargs.get("id", _uuid())
    grace.tenant_id = kwargs.get("tenant_id", _uuid())
    grace.quota_kind = kwargs.get("quota_kind", "audits")
    grace.extended_until = kwargs.get("extended_until", _now() + timedelta(days=7))
    grace.extended_by_user_id = kwargs.get("extended_by_user_id", _uuid())
    return grace


def _make_impersonation_log(**kwargs):
    log = MagicMock(spec=ImpersonationLog)
    log.id = kwargs.get("id", _uuid())
    log.admin_user_id = kwargs.get("admin_user_id", _uuid())
    log.impersonated_tenant_id = kwargs.get("impersonated_tenant_id", _uuid())
    log.reason = kwargs.get("reason", "Support debug")
    log.started_at = kwargs.get("started_at", _now())
    log.ended_at = kwargs.get("ended_at", None)
    return log


def _make_component(**kwargs):
    c = MagicMock(spec=StatusComponent)
    c.id = kwargs.get("id", _uuid())
    c.name = kwargs.get("name", "api")
    c.last_known_state = kwargs.get("last_known_state", "operational")
    c.last_evaluated_at = kwargs.get("last_evaluated_at", None)
    return c


# ── QuotaService tests ─────────────────────────────────────────────────────────


class TestQuotaServiceCheckQuota:
    @pytest.mark.asyncio
    async def test_below_80_pct_returns_ok(self):
        session = _make_session()
        svc = QuotaService(session)
        action, blocked = await svc.check_quota(
            tenant_id=_uuid(),
            quota_kind="audits",
            current_value=7,
            limit=10,
        )
        assert action == "ok"
        assert blocked is False

    @pytest.mark.asyncio
    async def test_at_85_pct_returns_soft_warn(self):
        session = _make_session()
        svc = QuotaService(session)
        log_entry = _make_log_entry(action="soft_warn")
        with patch.object(svc._log_repo, "create", new=AsyncMock(return_value=log_entry)):
            action, blocked = await svc.check_quota(
                tenant_id=_uuid(),
                quota_kind="audits",
                current_value=85,
                limit=100,
            )
        assert action == "soft_warn"
        assert blocked is False

    @pytest.mark.asyncio
    async def test_at_100_pct_no_grace_returns_hard_block(self):
        session = _make_session()
        svc = QuotaService(session)
        log_entry = _make_log_entry(action="hard_block")
        with patch.object(svc._log_repo, "create", new=AsyncMock(return_value=log_entry)), \
             patch.object(svc._grace_repo, "get_active", new=AsyncMock(return_value=None)):
            action, blocked = await svc.check_quota(
                tenant_id=_uuid(),
                quota_kind="audits",
                current_value=10,
                limit=10,
            )
        assert action == "hard_block"
        assert blocked is True

    @pytest.mark.asyncio
    async def test_hard_block_emits_quota_blocked_event(self):
        session = _make_session()
        svc = QuotaService(session)
        log_entry = _make_log_entry(action="hard_block")
        tenant_id = _uuid()
        with patch.object(svc._log_repo, "create", new=AsyncMock(return_value=log_entry)), \
             patch.object(svc._grace_repo, "get_active", new=AsyncMock(return_value=None)):
            await svc.check_quota(
                tenant_id=tenant_id,
                quota_kind="audits",
                current_value=10,
                limit=10,
            )
        events = svc.pending_events
        assert len(events) == 1
        event = events[0]
        assert isinstance(event, QuotaBlocked)
        assert event.tenant_id == tenant_id
        assert event.quota_kind == "audits"

    @pytest.mark.asyncio
    async def test_at_100_pct_with_active_grace_returns_soft_warn(self):
        session = _make_session()
        svc = QuotaService(session)
        grace = _make_grace()
        with patch.object(svc._grace_repo, "get_active", new=AsyncMock(return_value=grace)):
            action, blocked = await svc.check_quota(
                tenant_id=_uuid(),
                quota_kind="audits",
                current_value=10,
                limit=10,
            )
        assert action == "soft_warn"
        assert blocked is False

    @pytest.mark.asyncio
    async def test_with_active_grace_no_event_emitted(self):
        session = _make_session()
        svc = QuotaService(session)
        grace = _make_grace()
        with patch.object(svc._grace_repo, "get_active", new=AsyncMock(return_value=grace)):
            await svc.check_quota(
                tenant_id=_uuid(),
                quota_kind="audits",
                current_value=10,
                limit=10,
            )
        assert len(svc.pending_events) == 0

    @pytest.mark.asyncio
    async def test_unknown_quota_kind_returns_ok(self):
        session = _make_session()
        svc = QuotaService(session)
        action, blocked = await svc.check_quota(
            tenant_id=_uuid(),
            quota_kind="unknown_kind",
            current_value=9999,
            limit=1,
        )
        assert action == "ok"
        assert blocked is False

    @pytest.mark.asyncio
    async def test_zero_limit_returns_ok(self):
        session = _make_session()
        svc = QuotaService(session)
        action, blocked = await svc.check_quota(
            tenant_id=_uuid(),
            quota_kind="audits",
            current_value=100,
            limit=0,
        )
        assert action == "ok"
        assert blocked is False


class TestQuotaServiceLogAction:
    @pytest.mark.asyncio
    async def test_log_action_creates_log(self):
        session = _make_session()
        svc = QuotaService(session)
        tenant_id = _uuid()
        log_entry = _make_log_entry(tenant_id=tenant_id, action="soft_warn")
        with patch.object(svc._log_repo, "create", new=AsyncMock(return_value=log_entry)) as mock_create:
            result = await svc.log_action(
                tenant_id=tenant_id,
                quota_kind="audits",
                action="soft_warn",
            )
        mock_create.assert_called_once()
        assert result == log_entry

    @pytest.mark.asyncio
    async def test_log_action_passes_threshold_pct(self):
        session = _make_session()
        svc = QuotaService(session)
        log_entry = _make_log_entry()
        with patch.object(svc._log_repo, "create", new=AsyncMock(return_value=log_entry)) as mock_create:
            await svc.log_action(
                tenant_id=_uuid(),
                quota_kind="llm_spend",
                action="hard_block",
                threshold_pct=1.05,
                detail={"note": "exceeded"},
            )
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["threshold_pct"] == 1.05
        assert call_kwargs["detail"] == {"note": "exceeded"}


class TestQuotaServiceExtendGrace:
    @pytest.mark.asyncio
    async def test_extend_grace_creates_extension(self):
        session = _make_session()
        svc = QuotaService(session)
        tenant_id = _uuid()
        user_id = _uuid()
        grace = _make_grace(tenant_id=tenant_id)
        with patch.object(svc._grace_repo, "create", new=AsyncMock(return_value=grace)) as mock_create:
            result = await svc.extend_grace(
                tenant_id=tenant_id,
                quota_kind="audits",
                days=7,
                extended_by_user_id=user_id,
                reason="Customer request",
            )
        mock_create.assert_called_once()
        assert result == grace

    @pytest.mark.asyncio
    async def test_extend_grace_sets_extended_until(self):
        session = _make_session()
        svc = QuotaService(session)
        grace = _make_grace()
        with patch.object(svc._grace_repo, "create", new=AsyncMock(return_value=grace)) as mock_create:
            await svc.extend_grace(
                tenant_id=_uuid(),
                quota_kind="audits",
                days=14,
                extended_by_user_id=_uuid(),
            )
        call_kwargs = mock_create.call_args[1]
        assert "extended_until" in call_kwargs
        # Should be roughly 14 days from now
        extended = call_kwargs["extended_until"]
        diff = extended - _now()
        assert timedelta(days=13) < diff < timedelta(days=15)


class TestQuotaServiceIsInGrace:
    @pytest.mark.asyncio
    async def test_is_in_grace_true_when_active(self):
        session = _make_session()
        svc = QuotaService(session)
        grace = _make_grace()
        with patch.object(svc._grace_repo, "get_active", new=AsyncMock(return_value=grace)):
            result = await svc.is_in_grace(tenant_id=_uuid(), quota_kind="audits")
        assert result is True

    @pytest.mark.asyncio
    async def test_is_in_grace_false_when_none(self):
        session = _make_session()
        svc = QuotaService(session)
        with patch.object(svc._grace_repo, "get_active", new=AsyncMock(return_value=None)):
            result = await svc.is_in_grace(tenant_id=_uuid(), quota_kind="audits")
        assert result is False


# ── AdminOpsService tests ──────────────────────────────────────────────────────


class TestAdminOpsServiceStartImpersonation:
    @pytest.mark.asyncio
    async def test_start_impersonation_creates_log(self):
        session = _make_session()
        svc = AdminOpsService(session)
        admin_id = _uuid()
        tenant_id = _uuid()
        log = _make_impersonation_log(admin_user_id=admin_id, impersonated_tenant_id=tenant_id)
        with patch.object(svc._impersonation_repo, "create", new=AsyncMock(return_value=log)):
            result = await svc.start_impersonation(
                admin_user_id=admin_id,
                impersonated_tenant_id=tenant_id,
                reason="Support debug",
            )
        assert result == log

    @pytest.mark.asyncio
    async def test_start_impersonation_emits_event(self):
        session = _make_session()
        svc = AdminOpsService(session)
        admin_id = _uuid()
        tenant_id = _uuid()
        log = _make_impersonation_log(admin_user_id=admin_id, impersonated_tenant_id=tenant_id)
        with patch.object(svc._impersonation_repo, "create", new=AsyncMock(return_value=log)):
            await svc.start_impersonation(
                admin_user_id=admin_id,
                impersonated_tenant_id=tenant_id,
                reason="Debug session",
            )
        events = svc.pending_events
        assert len(events) == 1
        assert isinstance(events[0], ImpersonationStarted)
        assert events[0].admin_user_id == admin_id
        assert events[0].impersonated_tenant_id == tenant_id


class TestAdminOpsServiceEndImpersonation:
    @pytest.mark.asyncio
    async def test_end_impersonation_calls_repo(self):
        session = _make_session()
        svc = AdminOpsService(session)
        admin_id = _uuid()
        log_id = _uuid()
        log = _make_impersonation_log(id=log_id, admin_user_id=admin_id)
        with patch.object(svc._impersonation_repo, "get", new=AsyncMock(return_value=log)), \
             patch.object(svc._impersonation_repo, "end_session", new=AsyncMock()) as mock_end:
            await svc.end_impersonation(log_id=log_id, admin_user_id=admin_id)
        mock_end.assert_called_once_with(log_id)

    @pytest.mark.asyncio
    async def test_end_impersonation_emits_event(self):
        session = _make_session()
        svc = AdminOpsService(session)
        admin_id = _uuid()
        log_id = _uuid()
        log = _make_impersonation_log(id=log_id, admin_user_id=admin_id)
        with patch.object(svc._impersonation_repo, "get", new=AsyncMock(return_value=log)), \
             patch.object(svc._impersonation_repo, "end_session", new=AsyncMock()):
            await svc.end_impersonation(log_id=log_id, admin_user_id=admin_id)
        events = svc.pending_events
        assert len(events) == 1
        assert isinstance(events[0], ImpersonationEnded)
        assert events[0].log_id == log_id

    @pytest.mark.asyncio
    async def test_end_impersonation_raises_not_found_when_log_missing(self):
        from app.core.exceptions import NotFoundError
        session = _make_session()
        svc = AdminOpsService(session)
        log_id = _uuid()
        with patch.object(svc._impersonation_repo, "get", new=AsyncMock(return_value=None)):
            with pytest.raises(NotFoundError):
                await svc.end_impersonation(log_id=log_id, admin_user_id=_uuid())

    @pytest.mark.asyncio
    async def test_end_impersonation_raises_permission_denied_wrong_admin(self):
        from app.core.exceptions import PermissionDeniedError
        session = _make_session()
        svc = AdminOpsService(session)
        owner_admin_id = _uuid()
        other_admin_id = _uuid()
        log_id = _uuid()
        log = _make_impersonation_log(id=log_id, admin_user_id=owner_admin_id)
        with patch.object(svc._impersonation_repo, "get", new=AsyncMock(return_value=log)):
            with pytest.raises(PermissionDeniedError):
                await svc.end_impersonation(log_id=log_id, admin_user_id=other_admin_id)


class TestAdminOpsServiceUpsertStatusComponent:
    @pytest.mark.asyncio
    async def test_upsert_creates_when_not_exists(self):
        session = _make_session()
        svc = AdminOpsService(session)
        component = _make_component(name="api")
        with patch.object(svc._status_repo, "get_by_name", new=AsyncMock(return_value=None)), \
             patch.object(svc._status_repo, "create", new=AsyncMock(return_value=component)) as mock_create:
            result = await svc.upsert_status_component(
                name="api",
                health_signal_query="error_rate_5m < 0.01",
            )
        mock_create.assert_called_once()
        assert result == component

    @pytest.mark.asyncio
    async def test_upsert_updates_when_exists(self):
        session = _make_session()
        svc = AdminOpsService(session)
        component = _make_component(name="api")
        with patch.object(svc._status_repo, "get_by_name", new=AsyncMock(return_value=component)), \
             patch.object(svc._status_repo, "update_state", new=AsyncMock()) as mock_update:
            result = await svc.upsert_status_component(
                name="api",
                health_signal_query="error_rate_5m < 0.01",
                state="degraded",
            )
        mock_update.assert_called_once()
        assert result == component


class TestAdminOpsServiceUpdateComponentState:
    @pytest.mark.asyncio
    async def test_update_state_updates_component(self):
        session = _make_session()
        svc = AdminOpsService(session)
        component = _make_component(name="api")
        with patch.object(svc._status_repo, "get_by_name", new=AsyncMock(return_value=component)), \
             patch.object(svc._status_repo, "update_state", new=AsyncMock()):
            result = await svc.update_component_state(name="api", state="degraded")
        assert result is not None
        assert result.last_known_state == "degraded"

    @pytest.mark.asyncio
    async def test_update_state_returns_none_when_not_found(self):
        session = _make_session()
        svc = AdminOpsService(session)
        with patch.object(svc._status_repo, "get_by_name", new=AsyncMock(return_value=None)):
            result = await svc.update_component_state(name="nonexistent", state="degraded")
        assert result is None


class TestAdminOpsServiceSeedDefaultComponents:
    @pytest.mark.asyncio
    async def test_seed_creates_5_components(self):
        session = _make_session()
        svc = AdminOpsService(session)

        created_components = []

        async def mock_get_by_name(name):
            return None

        async def mock_create(**kwargs):
            c = _make_component(name=kwargs["name"])
            created_components.append(c)
            return c

        with patch.object(svc._status_repo, "get_by_name", side_effect=mock_get_by_name), \
             patch.object(svc._status_repo, "create", side_effect=mock_create):
            result = await svc.seed_default_components()

        assert len(result) == 5
        names = [c.name for c in result]
        assert "api" in names or all(n in ["api", "audit_engine", "content_generation", "publishing", "notifications"] for n in names)

    @pytest.mark.asyncio
    async def test_seed_skips_existing_components(self):
        session = _make_session()
        svc = AdminOpsService(session)
        existing_component = _make_component(name="api")

        call_count = 0

        async def mock_get_by_name(name):
            if name == "api":
                return existing_component
            return None

        async def mock_create(**kwargs):
            nonlocal call_count
            call_count += 1
            return _make_component(name=kwargs["name"])

        with patch.object(svc._status_repo, "get_by_name", side_effect=mock_get_by_name), \
             patch.object(svc._status_repo, "create", side_effect=mock_create):
            result = await svc.seed_default_components()

        assert len(result) == 5
        assert call_count == 4  # Only 4 created, 1 existed


class TestAdminOpsServiceGetAllComponentStates:
    @pytest.mark.asyncio
    async def test_get_all_returns_list(self):
        session = _make_session()
        svc = AdminOpsService(session)
        components = [_make_component(name="api"), _make_component(name="notifications")]
        with patch.object(svc._status_repo, "list_all", new=AsyncMock(return_value=components)):
            result = await svc.get_all_component_states()
        assert result == components
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_get_all_returns_empty_list(self):
        session = _make_session()
        svc = AdminOpsService(session)
        with patch.object(svc._status_repo, "list_all", new=AsyncMock(return_value=[])):
            result = await svc.get_all_component_states()
        assert result == []
