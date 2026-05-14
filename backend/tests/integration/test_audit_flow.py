"""Integration tests — audit/reporting module: Report lifecycle, ShareLink, CitationDelta."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.models import CitationDeltaType
from app.modules.notifications.repository import CitationDeltaRepository
from app.modules.reporting.models import ReportStatus
from app.modules.reporting.repository import ReportRepository, ShareLinkRepository
from tests.integration.conftest import make_audit_run, make_business, make_category, make_tenant

# Skip entire module if testcontainers not available
pytest.importorskip("testcontainers", reason="testcontainers required for integration tests")

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Tests ──────────────────────────────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.asyncio
async def test_report_create_and_retrieve(pg_session: AsyncSession) -> None:
    """Report can be created in generating state and retrieved by ID."""
    tenant = await make_tenant(pg_session, slug=f"t-{uuid.uuid4().hex[:8]}")
    cat = await make_category(pg_session, slug=f"c-{uuid.uuid4().hex[:8]}")
    biz = await make_business(pg_session, tenant=tenant, category=cat)
    run = await make_audit_run(pg_session, tenant=tenant, business=biz)

    repo = ReportRepository(pg_session)
    token = uuid.uuid4().hex[:32]

    report = await repo.create(
        tenant_id=tenant.id,
        business_id=biz.id,
        audit_run_id=run.id,
        web_view_token=token,
        score=72.0,
        confidence_band="medium",
    )
    assert report.status == ReportStatus.generating
    assert report.score == 72.0

    fetched = await repo.get_by_id(report.id)
    assert fetched.id == report.id
    assert fetched.web_view_token == token


@pytest.mark.integration
@pytest.mark.asyncio
async def test_report_mark_ready(pg_session: AsyncSession) -> None:
    """Report status transitions to ready via mark_ready."""
    tenant = await make_tenant(pg_session, slug=f"t-{uuid.uuid4().hex[:8]}")
    cat = await make_category(pg_session, slug=f"c-{uuid.uuid4().hex[:8]}")
    biz = await make_business(pg_session, tenant=tenant, category=cat)
    run = await make_audit_run(pg_session, tenant=tenant, business=biz)

    repo = ReportRepository(pg_session)
    token = uuid.uuid4().hex[:32]

    report = await repo.create(
        tenant_id=tenant.id,
        business_id=biz.id,
        audit_run_id=run.id,
        web_view_token=token,
    )

    ready_report = await repo.mark_ready(
        report.id,
        score=88.5,
        confidence_band="high",
        completeness_pct=0.95,
        quick_wins={"items": ["add_alias", "update_description"]},
    )
    assert ready_report.status == ReportStatus.ready
    assert ready_report.score == 88.5
    assert ready_report.generated_at is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_report_get_by_web_view_token(pg_session: AsyncSession) -> None:
    """Report can be fetched by its web_view_token."""
    tenant = await make_tenant(pg_session, slug=f"t-{uuid.uuid4().hex[:8]}")
    cat = await make_category(pg_session, slug=f"c-{uuid.uuid4().hex[:8]}")
    biz = await make_business(pg_session, tenant=tenant, category=cat)
    run = await make_audit_run(pg_session, tenant=tenant, business=biz)

    repo = ReportRepository(pg_session)
    token = f"tok-{uuid.uuid4().hex[:24]}"

    await repo.create(
        tenant_id=tenant.id,
        business_id=biz.id,
        audit_run_id=run.id,
        web_view_token=token,
    )

    found = await repo.get_by_web_view_token(token)
    assert found is not None
    assert found.web_view_token == token


@pytest.mark.integration
@pytest.mark.asyncio
async def test_report_list_for_business(pg_session: AsyncSession) -> None:
    """list_for_business returns all reports for a business."""
    tenant = await make_tenant(pg_session, slug=f"t-{uuid.uuid4().hex[:8]}")
    cat = await make_category(pg_session, slug=f"c-{uuid.uuid4().hex[:8]}")
    biz = await make_business(pg_session, tenant=tenant, category=cat)

    repo = ReportRepository(pg_session)

    for i in range(3):
        run = await make_audit_run(pg_session, tenant=tenant, business=biz)
        await repo.create(
            tenant_id=tenant.id,
            business_id=biz.id,
            audit_run_id=run.id,
            web_view_token=f"tok-{uuid.uuid4().hex[:24]}",
        )

    reports = await repo.list_for_business(biz.id, tenant.id)
    assert len(reports) == 3


@pytest.mark.integration
@pytest.mark.asyncio
async def test_share_link_creation_and_view_count(pg_session: AsyncSession) -> None:
    """ShareLink can be created; increment_view increases view_count."""
    tenant = await make_tenant(pg_session, slug=f"t-{uuid.uuid4().hex[:8]}")
    cat = await make_category(pg_session, slug=f"c-{uuid.uuid4().hex[:8]}")
    biz = await make_business(pg_session, tenant=tenant, category=cat)
    run = await make_audit_run(pg_session, tenant=tenant, business=biz)

    r_repo = ReportRepository(pg_session)
    report = await r_repo.create(
        tenant_id=tenant.id,
        business_id=biz.id,
        audit_run_id=run.id,
        web_view_token=f"tok-{uuid.uuid4().hex[:24]}",
    )

    sl_repo = ShareLinkRepository(pg_session)
    token = uuid.uuid4().hex[:32]
    expires_at = _utcnow() + timedelta(days=30)

    link = await sl_repo.create(
        tenant_id=tenant.id,
        business_id=biz.id,
        report_id=report.id,
        token=token,
        expires_at=expires_at,
    )
    assert link.view_count == 0

    # Increment view count
    await sl_repo.increment_view(token)

    fetched = await sl_repo.get_by_id(link.id)
    assert fetched.view_count == 1
    assert fetched.last_viewed_at is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_share_link_revoke(pg_session: AsyncSession) -> None:
    """Revoking a ShareLink makes get_by_token return None (expired/revoked)."""
    tenant = await make_tenant(pg_session, slug=f"t-{uuid.uuid4().hex[:8]}")
    cat = await make_category(pg_session, slug=f"c-{uuid.uuid4().hex[:8]}")
    biz = await make_business(pg_session, tenant=tenant, category=cat)
    run = await make_audit_run(pg_session, tenant=tenant, business=biz)

    r_repo = ReportRepository(pg_session)
    report = await r_repo.create(
        tenant_id=tenant.id,
        business_id=biz.id,
        audit_run_id=run.id,
        web_view_token=f"tok-{uuid.uuid4().hex[:24]}",
    )

    sl_repo = ShareLinkRepository(pg_session)
    token = uuid.uuid4().hex[:32]

    await sl_repo.create(
        tenant_id=tenant.id,
        business_id=biz.id,
        report_id=report.id,
        token=token,
        expires_at=_utcnow() + timedelta(days=30),
    )

    # Before revoke: active
    active = await sl_repo.get_by_token(token)
    assert active is not None

    # Revoke
    await sl_repo.revoke(token)

    # After revoke: get_by_token (filters revoked) returns None
    after_revoke = await sl_repo.get_by_token(token)
    assert after_revoke is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_citation_delta_list_for_audit_run(pg_session: AsyncSession) -> None:
    """CitationDelta rows can be created and listed by audit_run_id."""
    tenant = await make_tenant(pg_session, slug=f"t-{uuid.uuid4().hex[:8]}")
    cat = await make_category(pg_session, slug=f"c-{uuid.uuid4().hex[:8]}")
    biz = await make_business(pg_session, tenant=tenant, category=cat)
    run = await make_audit_run(pg_session, tenant=tenant, business=biz)

    repo = CitationDeltaRepository(pg_session)

    for dtype in [CitationDeltaType.won, CitationDeltaType.lost]:
        await repo.create(
            tenant_id=tenant.id,
            business_id=biz.id,
            audit_run_id=run.id,
            query_id=uuid.uuid4(),
            engine="google_ai",
            delta_type=dtype,
            current_state={"cited": dtype == CitationDeltaType.won},
        )

    deltas = await repo.list_for_audit_run(run.id)
    assert len(deltas) == 2
    found_types = {d.delta_type for d in deltas}
    assert CitationDeltaType.won in found_types
    assert CitationDeltaType.lost in found_types
