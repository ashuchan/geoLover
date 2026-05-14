"""Unit tests for Ops/Admin models (Phase 8)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.modules.ops.models import (
    ImpersonationLog,
    QuotaEnforcementLog,
    StatusComponent,
    TenantGraceExtension,
)


def _uuid():
    return uuid.uuid4()


def _now():
    return datetime.now(timezone.utc)


class TestQuotaEnforcementLog:
    def test_instantiation_defaults(self):
        tenant_id = _uuid()
        log = QuotaEnforcementLog(
            tenant_id=tenant_id,
            quota_kind="audits",
            action="soft_warn",
        )
        assert isinstance(log.id, uuid.UUID)
        assert log.tenant_id == tenant_id
        assert log.quota_kind == "audits"
        assert log.action == "soft_warn"
        assert log.business_id is None
        assert log.threshold_pct is None
        assert log.detail is None
        assert isinstance(log.triggered_at, datetime)

    def test_explicit_id(self):
        eid = _uuid()
        log = QuotaEnforcementLog(
            id=eid,
            tenant_id=_uuid(),
            quota_kind="llm_spend",
            action="hard_block",
        )
        assert log.id == eid

    def test_with_optional_fields(self):
        tenant_id = _uuid()
        business_id = _uuid()
        now = _now()
        log = QuotaEnforcementLog(
            tenant_id=tenant_id,
            business_id=business_id,
            quota_kind="businesses",
            action="hard_block",
            threshold_pct=1.05,
            triggered_at=now,
            detail={"extra": "info"},
        )
        assert log.business_id == business_id
        assert log.threshold_pct == 1.05
        assert log.detail == {"extra": "info"}
        assert log.triggered_at == now

    def test_tablename(self):
        assert QuotaEnforcementLog.__tablename__ == "quota_enforcement_log"


class TestTenantGraceExtension:
    def test_instantiation_defaults(self):
        tenant_id = _uuid()
        user_id = _uuid()
        extended_until = _now()
        grace = TenantGraceExtension(
            tenant_id=tenant_id,
            quota_kind="audits",
            extended_until=extended_until,
            extended_by_user_id=user_id,
        )
        assert isinstance(grace.id, uuid.UUID)
        assert grace.tenant_id == tenant_id
        assert grace.quota_kind == "audits"
        assert grace.extended_until == extended_until
        assert grace.extended_by_user_id == user_id
        assert grace.reason is None
        assert isinstance(grace.created_at, datetime)

    def test_explicit_id(self):
        eid = _uuid()
        grace = TenantGraceExtension(
            id=eid,
            tenant_id=_uuid(),
            quota_kind="llm_spend",
            extended_until=_now(),
            extended_by_user_id=_uuid(),
        )
        assert grace.id == eid

    def test_with_reason(self):
        grace = TenantGraceExtension(
            tenant_id=_uuid(),
            quota_kind="businesses",
            extended_until=_now(),
            extended_by_user_id=_uuid(),
            reason="Customer migration in progress",
        )
        assert grace.reason == "Customer migration in progress"

    def test_tablename(self):
        assert TenantGraceExtension.__tablename__ == "tenant_grace_extensions"


class TestImpersonationLog:
    def test_instantiation_defaults(self):
        admin_id = _uuid()
        tenant_id = _uuid()
        log = ImpersonationLog(
            admin_user_id=admin_id,
            impersonated_tenant_id=tenant_id,
            reason="Support investigation",
        )
        assert isinstance(log.id, uuid.UUID)
        assert log.admin_user_id == admin_id
        assert log.impersonated_tenant_id == tenant_id
        assert log.reason == "Support investigation"
        assert log.impersonated_user_id is None
        assert log.ended_at is None
        assert isinstance(log.started_at, datetime)

    def test_explicit_id(self):
        eid = _uuid()
        log = ImpersonationLog(
            id=eid,
            admin_user_id=_uuid(),
            impersonated_tenant_id=_uuid(),
            reason="Test",
        )
        assert log.id == eid

    def test_with_optional_fields(self):
        admin_id = _uuid()
        tenant_id = _uuid()
        user_id = _uuid()
        now = _now()
        log = ImpersonationLog(
            admin_user_id=admin_id,
            impersonated_tenant_id=tenant_id,
            impersonated_user_id=user_id,
            reason="Debug",
            ended_at=now,
        )
        assert log.impersonated_user_id == user_id
        assert log.ended_at == now

    def test_tablename(self):
        assert ImpersonationLog.__tablename__ == "impersonation_log"


class TestStatusComponent:
    def test_instantiation_defaults(self):
        component = StatusComponent(
            name="api",
            health_signal_query="error_rate_5m < 0.01",
        )
        assert isinstance(component.id, uuid.UUID)
        assert component.name == "api"
        assert component.health_signal_query == "error_rate_5m < 0.01"
        assert component.last_known_state == "operational"
        assert component.description is None
        assert component.last_evaluated_at is None

    def test_explicit_id(self):
        eid = _uuid()
        component = StatusComponent(
            id=eid,
            name="audit_engine",
            health_signal_query="audit_completion_rate > 0.95",
        )
        assert component.id == eid

    def test_with_description(self):
        component = StatusComponent(
            name="notifications",
            description="Notification Delivery",
            health_signal_query="email_delivery_rate > 0.97",
        )
        assert component.description == "Notification Delivery"

    def test_custom_state(self):
        component = StatusComponent(
            name="publishing",
            health_signal_query="publish_success_rate > 0.98",
            last_known_state="degraded",
        )
        assert component.last_known_state == "degraded"

    def test_tablename(self):
        assert StatusComponent.__tablename__ == "status_components"
