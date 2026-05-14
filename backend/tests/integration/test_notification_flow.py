"""Integration tests — notifications module: BouncedAddress, CitationDelta, Notification.

NOTE: NotificationPreference uses ARRAY(Text) which is PostgreSQL-only. Those
tests are skipped on SQLite. All other notification-related repos work fine.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.models import (
    CitationDeltaType,
    NotificationPriority,
    NotificationStatus,
)
from app.modules.notifications.repository import (
    BouncedAddressRepository,
    CitationDeltaRepository,
    NotificationRepository,
    RecrawlScheduleRepository,
)
from tests.integration.conftest import make_audit_run, make_business, make_category, make_tenant

# Skip entire module if testcontainers not available
pytest.importorskip("testcontainers", reason="testcontainers required for integration tests")

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Tests ──────────────────────────────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bounced_address_upsert_and_is_bounced(pg_session: AsyncSession) -> None:
    """BouncedAddress upsert creates row; is_bounced returns True until cleared."""
    repo = BouncedAddressRepository(pg_session)
    email = f"bounce-{uuid.uuid4().hex[:8]}@example.com"

    bounced = await repo.upsert(email, bounce_type="hard")
    assert bounced.email_normalized == email
    assert bounced.bounce_type == "hard"
    assert bounced.cleared_at is None

    is_b = await repo.is_bounced(email)
    assert is_b is True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bounced_address_upsert_updates_type(pg_session: AsyncSession) -> None:
    """Upsert on existing bounce updates bounce_type and clears cleared_at."""
    repo = BouncedAddressRepository(pg_session)
    email = f"bounce2-{uuid.uuid4().hex[:8]}@example.com"

    await repo.upsert(email, bounce_type="soft")
    # Upsert again with different type
    await repo.upsert(email, bounce_type="hard")

    record = await repo.get(email)
    assert record is not None
    assert record.bounce_type == "hard"
    assert record.cleared_at is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bounced_address_clear(pg_session: AsyncSession) -> None:
    """Clearing a bounced address makes is_bounced return False."""
    repo = BouncedAddressRepository(pg_session)
    email = f"bounce3-{uuid.uuid4().hex[:8]}@example.com"

    await repo.upsert(email, bounce_type="soft")
    await repo.clear(email)

    is_b = await repo.is_bounced(email)
    assert is_b is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_citation_delta_creation_and_list_for_audit_run(pg_session: AsyncSession) -> None:
    """CitationDelta can be created and listed by audit run."""
    tenant = await make_tenant(pg_session, slug=f"t-{uuid.uuid4().hex[:8]}")
    cat = await make_category(pg_session, slug=f"c-{uuid.uuid4().hex[:8]}")
    biz = await make_business(pg_session, tenant=tenant, category=cat)
    run = await make_audit_run(pg_session, tenant=tenant, business=biz)

    repo = CitationDeltaRepository(pg_session)

    delta = await repo.create(
        tenant_id=tenant.id,
        business_id=biz.id,
        audit_run_id=run.id,
        query_id=uuid.uuid4(),
        engine="google_ai",
        delta_type=CitationDeltaType.won,
        current_state={"cited": True, "rank": 1},
    )
    assert delta.delta_type == CitationDeltaType.won
    assert delta.audit_run_id == run.id

    deltas = await repo.list_for_audit_run(run.id)
    assert len(deltas) == 1
    assert deltas[0].id == delta.id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_citation_delta_multiple_types(pg_session: AsyncSession) -> None:
    """Multiple CitationDelta rows can be created with different types for one run."""
    tenant = await make_tenant(pg_session, slug=f"t-{uuid.uuid4().hex[:8]}")
    cat = await make_category(pg_session, slug=f"c-{uuid.uuid4().hex[:8]}")
    biz = await make_business(pg_session, tenant=tenant, category=cat)
    run = await make_audit_run(pg_session, tenant=tenant, business=biz)

    repo = CitationDeltaRepository(pg_session)

    for dtype in [CitationDeltaType.won, CitationDeltaType.lost, CitationDeltaType.improved]:
        await repo.create(
            tenant_id=tenant.id,
            business_id=biz.id,
            audit_run_id=run.id,
            query_id=uuid.uuid4(),
            engine="perplexity",
            delta_type=dtype,
            current_state={"type": dtype.value},
        )

    deltas = await repo.list_for_audit_run(run.id)
    assert len(deltas) == 3
    found_types = {d.delta_type for d in deltas}
    assert CitationDeltaType.won in found_types
    assert CitationDeltaType.lost in found_types


@pytest.mark.integration
@pytest.mark.asyncio
async def test_notification_creation_and_idempotency_key_lookup(
    pg_session: AsyncSession,
) -> None:
    """Notification can be created and retrieved by idempotency key."""
    from app.modules.identity.repository import UserRepository

    # Need a real user for the FK on recipient_user_id
    u_repo = UserRepository(pg_session)
    user = await u_repo.create(
        auth_provider_id=f"auth0|{uuid.uuid4().hex}",
        email_encrypted=b"enc",
        email_normalized=f"notif-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Recipient",
    )

    repo = NotificationRepository(pg_session)
    idem_key = f"notif-idem-{uuid.uuid4().hex}"

    notif = await repo.create(
        tenant_id=uuid.uuid4(),
        recipient_user_id=user.id,
        notification_type="weekly_digest",
        priority=NotificationPriority.standard,
        channel="email",
        render_payload={"period": "2026-W20"},
        idempotency_key=idem_key,
        status=NotificationStatus.queued,
    )
    assert notif.notification_type == "weekly_digest"
    assert notif.status == NotificationStatus.queued

    found = await repo.get_by_idempotency_key(idem_key)
    assert found is not None
    assert found.id == notif.id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_recrawl_schedule_creation(pg_session: AsyncSession) -> None:
    """RecrawlSchedule is created and retrievable by business."""
    tenant = await make_tenant(pg_session, slug=f"t-{uuid.uuid4().hex[:8]}")
    cat = await make_category(pg_session, slug=f"c-{uuid.uuid4().hex[:8]}")
    biz = await make_business(pg_session, tenant=tenant, category=cat)

    repo = RecrawlScheduleRepository(pg_session)

    schedule = await repo.create(
        tenant_id=tenant.id,
        business_id=biz.id,
        cadence="weekly",
        day_of_week=1,
        hour_local=9,
        enabled=True,
    )
    assert schedule.business_id == biz.id
    assert schedule.cadence == "weekly"
    assert schedule.enabled is True

    fetched = await repo.get_by_business(biz.id)
    assert fetched is not None
    assert fetched.id == schedule.id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_recrawl_schedule_bucket_list(pg_session: AsyncSession) -> None:
    """list_bucket returns schedules matching day_of_week and hour_local."""
    tenant = await make_tenant(pg_session, slug=f"t-{uuid.uuid4().hex[:8]}")

    repo = RecrawlScheduleRepository(pg_session)

    # Create two businesses so we have two schedules in same bucket
    for i in range(2):
        biz_cat = await make_category(pg_session, slug=f"c{i}-{uuid.uuid4().hex[:8]}")
        biz = await make_business(pg_session, tenant=tenant, category=biz_cat, name=f"Biz {i}")
        await repo.create(
            tenant_id=tenant.id,
            business_id=biz.id,
            cadence="weekly",
            day_of_week=3,
            hour_local=10,
            enabled=True,
        )

    bucket = await repo.list_bucket(day_of_week=3, hour_local=10)
    # At least 2 schedules in this bucket
    assert len(bucket) >= 2
