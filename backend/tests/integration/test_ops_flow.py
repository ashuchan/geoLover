"""Integration tests — ops module: QuotaService, AdminOpsService."""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ops.repository import QuotaEnforcementLogRepository
from app.modules.ops.service import AdminOpsService, QuotaService

# Skip entire module if testcontainers not available
pytest.importorskip("testcontainers", reason="testcontainers required for integration tests")

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


# ── Tests ──────────────────────────────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.asyncio
async def test_quota_check_below_limit(pg_session: AsyncSession) -> None:
    """Below 80% of limit → ok, no log entry created."""
    tid = uuid.uuid4()
    svc = QuotaService(pg_session)

    action, blocked = await svc.check_quota(
        tenant_id=tid, quota_kind="audits", current_value=5, limit=100
    )
    assert action == "ok"
    assert blocked is False

    # No logs should have been created
    logs = await QuotaEnforcementLogRepository(pg_session).list_for_tenant(tid)
    assert len(logs) == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_quota_check_soft_warn_zone(pg_session: AsyncSession) -> None:
    """At 85% of limit → soft_warn, not blocked, log entry created."""
    tid = uuid.uuid4()
    svc = QuotaService(pg_session)

    action, blocked = await svc.check_quota(
        tenant_id=tid, quota_kind="audits", current_value=85, limit=100
    )
    assert action == "soft_warn"
    assert blocked is False

    logs = await QuotaEnforcementLogRepository(pg_session).list_for_tenant(tid)
    assert any(log.action == "soft_warn" for log in logs)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_quota_check_over_limit_creates_log(pg_session: AsyncSession) -> None:
    """At 100% → hard_block and log entry created with correct action."""
    tid = uuid.uuid4()
    svc = QuotaService(pg_session)

    action, blocked = await svc.check_quota(
        tenant_id=tid, quota_kind="audits", current_value=12, limit=12
    )
    assert action == "hard_block"
    assert blocked is True

    logs = await QuotaEnforcementLogRepository(pg_session).list_for_tenant(tid)
    assert any(log.action == "hard_block" for log in logs)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_quota_check_hard_block_emits_event(pg_session: AsyncSession) -> None:
    """hard_block adds a QuotaBlocked event to pending_events."""
    tid = uuid.uuid4()
    svc = QuotaService(pg_session)

    await svc.check_quota(
        tenant_id=tid, quota_kind="content_briefs", current_value=50, limit=50
    )

    assert len(svc.pending_events) == 1
    event = svc.pending_events[0]
    assert event.name == "QuotaBlocked"
    assert event.tenant_id == tid
    assert event.quota_kind == "content_briefs"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_grace_extension_allows_over_limit(pg_session: AsyncSession) -> None:
    """Active grace extension prevents hard_block even at 100%."""
    from app.modules.identity.repository import UserRepository

    u_repo = UserRepository(pg_session)
    admin = await u_repo.create(
        auth_provider_id=f"auth0|{uuid.uuid4().hex}",
        email_encrypted=b"enc",
        email_normalized=f"admin-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Admin",
    )

    tid = uuid.uuid4()
    svc = QuotaService(pg_session)

    # Grant a grace period
    await svc.extend_grace(
        tenant_id=tid,
        quota_kind="audits",
        days=7,
        extended_by_user_id=admin.id,
        reason="Trial extension for onboarding",
    )

    # Now at 100% but grace is active → should be soft_warn, not hard_block
    action, blocked = await svc.check_quota(
        tenant_id=tid, quota_kind="audits", current_value=100, limit=100
    )
    assert action == "soft_warn"
    assert blocked is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_impersonation_start_and_end(pg_session: AsyncSession) -> None:
    """AdminOpsService.start_impersonation creates a log; end_impersonation sets ended_at."""
    from app.modules.identity.repository import UserRepository

    u_repo = UserRepository(pg_session)
    admin = await u_repo.create(
        auth_provider_id=f"auth0|{uuid.uuid4().hex}",
        email_encrypted=b"enc",
        email_normalized=f"admin2-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Admin2",
    )

    impersonated_tid = uuid.uuid4()
    svc = AdminOpsService(pg_session)

    log = await svc.start_impersonation(
        admin_user_id=admin.id,
        impersonated_tenant_id=impersonated_tid,
        reason="Support request #1234",
    )
    assert log.admin_user_id == admin.id
    assert log.impersonated_tenant_id == impersonated_tid
    assert log.ended_at is None

    # Verify ImpersonationStarted event emitted
    assert any(e.name == "ImpersonationStarted" for e in svc.pending_events)

    await svc.end_impersonation(log_id=log.id, admin_user_id=admin.id)

    # Verify ImpersonationEnded event emitted
    assert any(e.name == "ImpersonationEnded" for e in svc.pending_events)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_status_component_upsert_and_state_update(pg_session: AsyncSession) -> None:
    """upsert_status_component creates component; update_component_state changes state."""
    svc = AdminOpsService(pg_session)

    component = await svc.upsert_status_component(
        name=f"api-{uuid.uuid4().hex[:6]}",
        description="Core API",
        health_signal_query="error_rate_5m < 0.01",
        state="operational",
    )
    assert component.last_known_state == "operational"

    # Second upsert with same name updates state
    updated = await svc.upsert_status_component(
        name=component.name,
        description="Core API",
        health_signal_query="error_rate_5m < 0.01",
        state="degraded",
    )
    assert updated.last_known_state == "degraded"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_seed_default_components(pg_session: AsyncSession) -> None:
    """seed_default_components creates 5 default status components."""
    svc = AdminOpsService(pg_session)

    components = await svc.seed_default_components()
    assert len(components) == 5
    names = {c.name for c in components}
    assert "api" in names
    assert "audit_engine" in names
    assert "notifications" in names

    # Second call should not create duplicates
    components2 = await svc.seed_default_components()
    assert len(components2) == 5


@pytest.mark.integration
@pytest.mark.asyncio
async def test_quota_unknown_kind_returns_ok(pg_session: AsyncSession) -> None:
    """Unknown quota_kind is gracefully ignored and returns ok."""
    tid = uuid.uuid4()
    svc = QuotaService(pg_session)

    action, blocked = await svc.check_quota(
        tenant_id=tid,
        quota_kind="nonexistent_quota",
        current_value=999,
        limit=1,
    )
    assert action == "ok"
    assert blocked is False
