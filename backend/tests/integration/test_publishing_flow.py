"""Integration tests — publishing module: PublishTarget, PublishAttempt, EntitySeed lifecycle."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.publishing.models import (
    EntitySeedStatus,
    PublishAttemptStatus,
    PublishChannel,
    PublishTargetStatus,
)
from app.modules.publishing.repository import (
    DirectoryRegistryRepository,
    EntitySeedRepository,
    PublishAttemptRepository,
    PublishTargetRepository,
    VerificationPollRepository,
)
from tests.integration.conftest import make_business, make_category, make_tenant

# Skip entire module if testcontainers not available
pytest.importorskip("testcontainers", reason="testcontainers required for integration tests")

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Tests ──────────────────────────────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.asyncio
async def test_publish_target_creation_and_status_update(pg_session: AsyncSession) -> None:
    """PublishTarget is created and its status can be updated."""
    tenant = await make_tenant(pg_session, slug=f"t-{uuid.uuid4().hex[:8]}")
    cat = await make_category(pg_session, slug=f"c-{uuid.uuid4().hex[:8]}")
    biz = await make_business(pg_session, tenant=tenant, category=cat)

    repo = PublishTargetRepository(pg_session)

    target = await repo.create(
        tenant_id=tenant.id,
        business_id=biz.id,
        channel=PublishChannel.google_business_profile,
        status=PublishTargetStatus.pending_oauth,
    )
    assert target.status == PublishTargetStatus.pending_oauth
    assert target.channel == PublishChannel.google_business_profile

    await repo.update_status(target.id, PublishTargetStatus.connected)

    fetched = await repo.get(target.id, tenant.id)
    assert fetched is not None
    assert fetched.status == PublishTargetStatus.connected


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_publish_targets_for_business(pg_session: AsyncSession) -> None:
    """list_for_business returns all targets for the given business."""
    tenant = await make_tenant(pg_session, slug=f"t-{uuid.uuid4().hex[:8]}")
    cat = await make_category(pg_session, slug=f"c-{uuid.uuid4().hex[:8]}")
    biz = await make_business(pg_session, tenant=tenant, category=cat)

    repo = PublishTargetRepository(pg_session)

    await repo.create(
        tenant_id=tenant.id,
        business_id=biz.id,
        channel=PublishChannel.wordpress,
        status=PublishTargetStatus.connected,
    )
    await repo.create(
        tenant_id=tenant.id,
        business_id=biz.id,
        channel=PublishChannel.website_snippet,
        status=PublishTargetStatus.pending_oauth,
    )

    targets = await repo.list_for_business(tenant.id, biz.id)
    assert len(targets) == 2
    channels = {t.channel for t in targets}
    assert PublishChannel.wordpress in channels
    assert PublishChannel.website_snippet in channels


@pytest.mark.integration
@pytest.mark.asyncio
async def test_publish_attempt_idempotency(pg_session: AsyncSession) -> None:
    """Two lookups with the same idempotency_key return the same row."""
    tenant = await make_tenant(pg_session, slug=f"t-{uuid.uuid4().hex[:8]}")
    cat = await make_category(pg_session, slug=f"c-{uuid.uuid4().hex[:8]}")
    biz = await make_business(pg_session, tenant=tenant, category=cat)

    # Create a publish target first (FK constraint)
    target_repo = PublishTargetRepository(pg_session)
    target = await target_repo.create(
        tenant_id=tenant.id,
        business_id=biz.id,
        channel=PublishChannel.google_business_profile,
        status=PublishTargetStatus.connected,
    )

    attempt_repo = PublishAttemptRepository(pg_session)
    idem_key = f"idem-{uuid.uuid4().hex}"

    attempt1 = await attempt_repo.create(
        tenant_id=tenant.id,
        business_id=biz.id,
        target_id=target.id,
        content_asset_id=uuid.uuid4(),
        brief_id=uuid.uuid4(),
        idempotency_key=idem_key,
        status=PublishAttemptStatus.queued,
    )

    # Lookup by idempotency key
    existing = await attempt_repo.get_by_idempotency_key(idem_key)
    assert existing is not None
    assert existing.id == attempt1.id
    assert existing.status == PublishAttemptStatus.queued


@pytest.mark.integration
@pytest.mark.asyncio
async def test_publish_attempt_status_update(pg_session: AsyncSession) -> None:
    """PublishAttempt status can be updated from queued to succeeded."""
    tenant = await make_tenant(pg_session, slug=f"t-{uuid.uuid4().hex[:8]}")
    cat = await make_category(pg_session, slug=f"c-{uuid.uuid4().hex[:8]}")
    biz = await make_business(pg_session, tenant=tenant, category=cat)

    target_repo = PublishTargetRepository(pg_session)
    target = await target_repo.create(
        tenant_id=tenant.id,
        business_id=biz.id,
        channel=PublishChannel.wordpress,
        status=PublishTargetStatus.connected,
    )

    attempt_repo = PublishAttemptRepository(pg_session)
    attempt = await attempt_repo.create(
        tenant_id=tenant.id,
        business_id=biz.id,
        target_id=target.id,
        content_asset_id=uuid.uuid4(),
        brief_id=uuid.uuid4(),
        idempotency_key=f"idem-{uuid.uuid4().hex}",
        status=PublishAttemptStatus.queued,
    )

    await attempt_repo.update_status(
        attempt.id,
        PublishAttemptStatus.succeeded,
        external_object_id="gbp-post-123",
        public_url="https://example.com/post/123",
    )

    fetched = await attempt_repo.get(attempt.id, tenant.id)
    assert fetched is not None
    assert fetched.status == PublishAttemptStatus.succeeded
    assert fetched.external_object_id == "gbp-post-123"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_entity_seed_creation(pg_session: AsyncSession) -> None:
    """EntitySeed can be created and retrieved for a business + directory."""
    tenant = await make_tenant(pg_session, slug=f"t-{uuid.uuid4().hex[:8]}")
    cat = await make_category(pg_session, slug=f"c-{uuid.uuid4().hex[:8]}")
    biz = await make_business(pg_session, tenant=tenant, category=cat)

    # Create a DirectoryRegistry row first (FK)
    dir_repo = DirectoryRegistryRepository(pg_session)
    directory = await dir_repo.create(
        name="Just Dial",
        slug=f"justdial-{uuid.uuid4().hex[:6]}",
        submission_method="api",
        verification_method="manual",
        active=True,
        known_indexed_by_ai=True,
    )

    seed_repo = EntitySeedRepository(pg_session)
    seed = await seed_repo.create(
        tenant_id=tenant.id,
        business_id=biz.id,
        directory_id=directory.id,
        submission_payload={"name": "Test Bakery", "city": "Bangalore"},
        status=EntitySeedStatus.pending_submission,
    )

    assert seed.tenant_id == tenant.id
    assert seed.business_id == biz.id
    assert seed.status == EntitySeedStatus.pending_submission

    # Check retrieval by business+directory
    found = await seed_repo.get_by_business_directory(biz.id, directory.id)
    assert found is not None
    assert found.id == seed.id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_verification_poll_scheduling(pg_session: AsyncSession) -> None:
    """VerificationPoll can be created and listed as due."""
    tenant = await make_tenant(pg_session, slug=f"t-{uuid.uuid4().hex[:8]}")
    cat = await make_category(pg_session, slug=f"c-{uuid.uuid4().hex[:8]}")
    biz = await make_business(pg_session, tenant=tenant, category=cat)

    dir_repo = DirectoryRegistryRepository(pg_session)
    directory = await dir_repo.create(
        name="India Mart",
        slug=f"indiamart-{uuid.uuid4().hex[:6]}",
        submission_method="manual",
        verification_method="dns_txt",
    )

    seed_repo = EntitySeedRepository(pg_session)
    seed = await seed_repo.create(
        tenant_id=tenant.id,
        business_id=biz.id,
        directory_id=directory.id,
        submission_payload={"name": "Test Biz"},
        status=EntitySeedStatus.submitted,
    )

    poll_repo = VerificationPollRepository(pg_session)
    from datetime import timedelta
    past_time = _utcnow() - timedelta(hours=1)
    poll = await poll_repo.create(
        tenant_id=tenant.id,
        seed_id=seed.id,
        scheduled_for=past_time,
        attempt_index=0,
    )

    # Should show up as due
    due = await poll_repo.list_due(_utcnow())
    assert any(p.id == poll.id for p in due)

    # Mark as attempted
    await poll_repo.mark_attempted(poll.id, outcome="verified")

    # No longer in due list
    due_after = await poll_repo.list_due(_utcnow())
    assert not any(p.id == poll.id for p in due_after)
