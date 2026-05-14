"""Integration tests — audit and reporting modules: Report, ShareLink lifecycle."""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

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
async def test_report_create_and_get_by_id(pg_session: AsyncSession) -> None:
    """Report can be created and retrieved by ID."""
    tenant = await make_tenant(pg_session, slug=f"t-{uuid.uuid4().hex[:8]}")
    cat = await make_category(pg_session, slug=f"c-{uuid.uuid4().hex[:8]}")
    biz = await make_business(pg_session, tenant=tenant, category=cat)
    run = await make_audit_run(pg_session, tenant=tenant, business=biz)

    repo = ReportRepository(pg_session)
    token = secrets.token_urlsafe(32)[:48]

    report = await repo.create(
        tenant_id=tenant.id,
        business_id=biz.id,
        audit_run_id=run.id,
        web_view_token=token,
        version=1,
        score=72.5,
    )
    assert report.id is not None
    assert report.score == 72.5

    fetched = await repo.get_by_id(report.id)
    assert fetched is not None
    assert fetched.id == report.id
    assert fetched.score == 72.5


@pytest.mark.integration
@pytest.mark.asyncio
async def test_report_list_for_business(pg_session: AsyncSession) -> None:
    """list_for_business returns all reports for the given business."""
    tenant = await make_tenant(pg_session, slug=f"t-{uuid.uuid4().hex[:8]}")
    cat = await make_category(pg_session, slug=f"c-{uuid.uuid4().hex[:8]}")
    biz = await make_business(pg_session, tenant=tenant, category=cat)

    repo = ReportRepository(pg_session)

    # Create 3 reports for different audit runs
    for i in range(3):
        run = await make_audit_run(pg_session, tenant=tenant, business=biz)
        token = secrets.token_urlsafe(32)[:48]
        await repo.create(
            tenant_id=tenant.id,
            business_id=biz.id,
            audit_run_id=run.id,
            web_view_token=token,
            version=1,
        )

    reports = await repo.list_for_business(biz.id, tenant.id)
    assert len(reports) == 3


@pytest.mark.integration
@pytest.mark.asyncio
async def test_report_mark_ready(pg_session: AsyncSession) -> None:
    """mark_ready updates status to ready and sets generated_at."""
    tenant = await make_tenant(pg_session, slug=f"t-{uuid.uuid4().hex[:8]}")
    cat = await make_category(pg_session, slug=f"c-{uuid.uuid4().hex[:8]}")
    biz = await make_business(pg_session, tenant=tenant, category=cat)
    run = await make_audit_run(pg_session, tenant=tenant, business=biz)

    repo = ReportRepository(pg_session)
    token = secrets.token_urlsafe(32)[:48]

    report = await repo.create(
        tenant_id=tenant.id,
        business_id=biz.id,
        audit_run_id=run.id,
        web_view_token=token,
    )

    from app.modules.reporting.models import ReportStatus
    assert report.status == ReportStatus.generating

    ready = await repo.mark_ready(
        report.id,
        quick_wins={"items": []},
        score=80.0,
    )
    assert ready.status == ReportStatus.ready
    assert ready.generated_at is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_share_link_create_and_get_by_token(pg_session: AsyncSession) -> None:
    """ShareLink can be created and retrieved by token."""
    tenant = await make_tenant(pg_session, slug=f"t-{uuid.uuid4().hex[:8]}")
    cat = await make_category(pg_session, slug=f"c-{uuid.uuid4().hex[:8]}")
    biz = await make_business(pg_session, tenant=tenant, category=cat)
    run = await make_audit_run(pg_session, tenant=tenant, business=biz)

    report_repo = ReportRepository(pg_session)
    report_token = secrets.token_urlsafe(32)[:48]
    report = await report_repo.create(
        tenant_id=tenant.id,
        business_id=biz.id,
        audit_run_id=run.id,
        web_view_token=report_token,
    )

    link_repo = ShareLinkRepository(pg_session)
    share_token = secrets.token_urlsafe(32)[:48]
    expires_at = _utcnow() + timedelta(days=7)

    link = await link_repo.create(
        tenant_id=tenant.id,
        business_id=biz.id,
        report_id=report.id,
        token=share_token,
        expires_at=expires_at,
    )
    assert link.id is not None
    assert link.view_count == 0

    fetched = await link_repo.get_by_token(share_token)
    assert fetched is not None
    assert fetched.id == link.id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_share_link_increment_view(pg_session: AsyncSession) -> None:
    """increment_view updates view_count on ShareLink."""
    tenant = await make_tenant(pg_session, slug=f"t-{uuid.uuid4().hex[:8]}")
    cat = await make_category(pg_session, slug=f"c-{uuid.uuid4().hex[:8]}")
    biz = await make_business(pg_session, tenant=tenant, category=cat)
    run = await make_audit_run(pg_session, tenant=tenant, business=biz)

    report_repo = ReportRepository(pg_session)
    report_token = secrets.token_urlsafe(32)[:48]
    report = await report_repo.create(
        tenant_id=tenant.id,
        business_id=biz.id,
        audit_run_id=run.id,
        web_view_token=report_token,
    )

    link_repo = ShareLinkRepository(pg_session)
    share_token = secrets.token_urlsafe(32)[:48]
    expires_at = _utcnow() + timedelta(days=7)

    link = await link_repo.create(
        tenant_id=tenant.id,
        business_id=biz.id,
        report_id=report.id,
        token=share_token,
        expires_at=expires_at,
    )
    assert link.view_count == 0

    await link_repo.increment_view(share_token)
    await link_repo.increment_view(share_token)

    fetched = await link_repo.get_by_token(share_token)
    assert fetched is not None
    assert fetched.view_count == 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_share_link_revoke(pg_session: AsyncSession) -> None:
    """revoke sets revoked_at; revoked link is not returned by get_by_token."""
    tenant = await make_tenant(pg_session, slug=f"t-{uuid.uuid4().hex[:8]}")
    cat = await make_category(pg_session, slug=f"c-{uuid.uuid4().hex[:8]}")
    biz = await make_business(pg_session, tenant=tenant, category=cat)
    run = await make_audit_run(pg_session, tenant=tenant, business=biz)

    report_repo = ReportRepository(pg_session)
    report_token = secrets.token_urlsafe(32)[:48]
    report = await report_repo.create(
        tenant_id=tenant.id,
        business_id=biz.id,
        audit_run_id=run.id,
        web_view_token=report_token,
    )

    link_repo = ShareLinkRepository(pg_session)
    share_token = secrets.token_urlsafe(32)[:48]
    expires_at = _utcnow() + timedelta(days=7)

    link = await link_repo.create(
        tenant_id=tenant.id,
        business_id=biz.id,
        report_id=report.id,
        token=share_token,
        expires_at=expires_at,
    )

    revoked = await link_repo.revoke(share_token)
    assert revoked is not None
    assert revoked.revoked_at is not None

    # get_by_token filters out revoked links
    not_found = await link_repo.get_by_token(share_token)
    assert not_found is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_report_get_by_web_view_token(pg_session: AsyncSession) -> None:
    """Report can be fetched by its unique web_view_token."""
    tenant = await make_tenant(pg_session, slug=f"t-{uuid.uuid4().hex[:8]}")
    cat = await make_category(pg_session, slug=f"c-{uuid.uuid4().hex[:8]}")
    biz = await make_business(pg_session, tenant=tenant, category=cat)
    run = await make_audit_run(pg_session, tenant=tenant, business=biz)

    repo = ReportRepository(pg_session)
    token = secrets.token_urlsafe(32)[:48]

    report = await repo.create(
        tenant_id=tenant.id,
        business_id=biz.id,
        audit_run_id=run.id,
        web_view_token=token,
    )

    fetched = await repo.get_by_web_view_token(token)
    assert fetched is not None
    assert fetched.id == report.id
