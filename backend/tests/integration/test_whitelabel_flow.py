"""Integration tests — whitelabel module: WhitelabelConfig, DomainMapping, BulkImport."""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.whitelabel.models import DomainVerificationStatus
from app.modules.whitelabel.service import BulkImportService, DomainService, WhitelabelService
from tests.integration.conftest import make_tenant

# Skip entire module if testcontainers not available
pytest.importorskip("testcontainers", reason="testcontainers required for integration tests")

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


# ── Tests ──────────────────────────────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.asyncio
async def test_whitelabel_config_get_or_create(pg_session: AsyncSession) -> None:
    """WhitelabelConfig is created on first access, returned on subsequent."""
    svc = WhitelabelService(pg_session)
    tid = uuid.uuid4()

    config = await svc.get_or_create_config(tid)
    assert config.tenant_id == tid
    assert config.primary_color_hex == "#2A6FDB"

    # Second call returns same row
    config2 = await svc.get_or_create_config(tid)
    assert config2.id == config.id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_update_config_with_valid_colors(pg_session: AsyncSession) -> None:
    """update_config accepts valid hex colors and persists them."""
    svc = WhitelabelService(pg_session)
    tid = uuid.uuid4()

    await svc.get_or_create_config(tid)
    updated = await svc.update_config(
        tenant_id=tid,
        primary_color_hex="#FF5733",
        secondary_color_hex="#33A1FF",
    )
    assert updated.primary_color_hex == "#FF5733"
    assert updated.secondary_color_hex == "#33A1FF"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_update_config_raises_on_bad_hex(pg_session: AsyncSession) -> None:
    """update_config raises ValueError for an invalid hex color."""
    svc = WhitelabelService(pg_session)
    tid = uuid.uuid4()

    await svc.get_or_create_config(tid)

    with pytest.raises(ValueError, match="Invalid hex color"):
        await svc.update_config(
            tenant_id=tid,
            primary_color_hex="not-a-color",
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_update_config_emits_event(pg_session: AsyncSession) -> None:
    """update_config appends WhitelabelConfigUpdated to pending_events."""
    svc = WhitelabelService(pg_session)
    tid = uuid.uuid4()

    await svc.get_or_create_config(tid)
    await svc.update_config(tenant_id=tid, primary_color_hex="#AABBCC")

    assert len(svc.pending_events) == 1
    assert svc.pending_events[0].name == "WhitelabelConfigUpdated"
    assert svc.pending_events[0].tenant_id == tid


@pytest.mark.integration
@pytest.mark.asyncio
async def test_domain_add_custom_is_pending(pg_session: AsyncSession) -> None:
    """Adding a custom domain starts in pending verification status."""
    svc = DomainService(pg_session)
    tid = uuid.uuid4()

    mapping = await svc.add_domain(
        tenant_id=tid,
        domain=f"app-{uuid.uuid4().hex[:8]}.example.com",
        domain_type="custom",
    )
    assert mapping.verification_status == DomainVerificationStatus.pending
    assert mapping.verification_token is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_domain_add_platform_subdomain_is_verified(pg_session: AsyncSession) -> None:
    """Adding a platform subdomain is auto-verified."""
    svc = DomainService(pg_session)
    tid = uuid.uuid4()

    mapping = await svc.add_domain(
        tenant_id=tid,
        domain=f"myagency-{uuid.uuid4().hex[:8]}.citedby.app",
        domain_type="platform_subdomain",
    )
    assert mapping.verification_status == DomainVerificationStatus.verified
    assert mapping.verified_at is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_domain_verify_custom_domain(pg_session: AsyncSession) -> None:
    """verify_domain transitions a pending domain to verified."""
    svc = DomainService(pg_session)
    tid = uuid.uuid4()

    mapping = await svc.add_domain(
        tenant_id=tid,
        domain=f"custom-{uuid.uuid4().hex[:8]}.example.com",
        domain_type="custom",
    )
    assert mapping.verification_status == DomainVerificationStatus.pending

    success, reason = await svc.verify_domain(mapping_id=mapping.id, tenant_id=tid)
    assert success is True
    assert reason == "verified"

    # Verifying again returns already_verified
    success2, reason2 = await svc.verify_domain(mapping_id=mapping.id, tenant_id=tid)
    assert success2 is True
    assert reason2 == "already_verified"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bulk_import_process_csv_rows_mixed(pg_session: AsyncSession) -> None:
    """process_csv_rows handles valid and invalid rows correctly."""
    from app.modules.identity.repository import UserRepository

    u_repo = UserRepository(pg_session)
    user = await u_repo.create(
        auth_provider_id=f"auth0|{uuid.uuid4().hex}",
        email_encrypted=b"enc",
        email_normalized=f"bulk-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Importer",
    )

    svc = BulkImportService(pg_session)
    tid = uuid.uuid4()

    job = await svc.create_job(
        tenant_id=tid,
        initiated_by_user_id=user.id,
        source_object_path="gs://bucket/import.csv",
    )

    valid_row = {
        "business_name": "Test Bakery",
        "city": "Bangalore",
        "category": "Bakery",
        "website": "https://testbakery.com",
    }
    invalid_row = {}  # Missing required fields

    result = await svc.process_csv_rows(
        job_id=job.id,
        tenant_id=tid,
        rows=[valid_row, invalid_row, valid_row],  # valid, invalid, duplicate key
    )

    assert result["succeeded"] >= 1
    assert result["failed"] >= 1
    assert "outcomes" in result


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bulk_import_job_get(pg_session: AsyncSession) -> None:
    """BulkImportJob can be fetched by job_id and tenant_id."""
    from app.modules.identity.repository import UserRepository

    u_repo = UserRepository(pg_session)
    user = await u_repo.create(
        auth_provider_id=f"auth0|{uuid.uuid4().hex}",
        email_encrypted=b"enc",
        email_normalized=f"bulk2-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Importer2",
    )

    svc = BulkImportService(pg_session)
    tid = uuid.uuid4()

    job = await svc.create_job(
        tenant_id=tid,
        initiated_by_user_id=user.id,
        source_object_path="gs://bucket/another.csv",
    )

    fetched = await svc.get_job(job_id=job.id, tenant_id=tid)
    assert fetched is not None
    assert fetched.id == job.id

    # Different tenant cannot see it
    nothing = await svc.get_job(job_id=job.id, tenant_id=uuid.uuid4())
    assert nothing is None
