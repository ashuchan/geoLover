"""Integration tests — identity module: Tenant, User, Membership lifecycle."""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.models import TenantType, UserRole
from app.modules.identity.repository import (
    AuditLogRepository,
    MembershipRepository,
    TenantRepository,
    UserRepository,
)
from app.core.exceptions import ConflictError, TenantNotFoundError

# Skip entire module if testcontainers not available
pytest.importorskip("testcontainers", reason="testcontainers required for integration tests")

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_email() -> str:
    """Return a unique email address for each test call."""
    return f"user-{uuid.uuid4().hex[:8]}@example.com"


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_tenant_and_retrieve_by_slug(pg_session: AsyncSession) -> None:
    """Tenant can be created and fetched back by slug."""
    repo = TenantRepository(pg_session)
    slug = f"tenant-{uuid.uuid4().hex[:8]}"
    tenant = await repo.create(
        type=TenantType.agency,
        display_name="Integration Test Agency",
        slug=slug,
    )
    assert tenant.slug == slug
    assert tenant.type == TenantType.agency

    fetched = await repo.get_by_slug(slug)
    assert fetched.id == tenant.id
    assert fetched.display_name == "Integration Test Agency"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_tenant_duplicate_slug_raises(pg_session: AsyncSession) -> None:
    """Creating two tenants with the same slug raises ConflictError."""
    repo = TenantRepository(pg_session)
    slug = f"dup-{uuid.uuid4().hex[:8]}"
    await repo.create(type=TenantType.trial, display_name="First", slug=slug)

    with pytest.raises(ConflictError):
        await repo.create(type=TenantType.trial, display_name="Second", slug=slug)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_user_and_retrieve(pg_session: AsyncSession) -> None:
    """User can be created and retrieved by ID."""
    repo = UserRepository(pg_session)
    email_norm = _make_email()
    user = await repo.create(
        auth_provider_id=f"auth0|{uuid.uuid4().hex}",
        email_encrypted=b"encrypted-bytes",
        email_normalized=email_norm,
        display_name="Jane Doe",
    )
    assert user.email_normalized == email_norm

    fetched = await repo.get_by_id(user.id)
    assert fetched.display_name == "Jane Doe"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_user_duplicate_email_raises(pg_session: AsyncSession) -> None:
    """Creating two users with the same normalised email raises ConflictError."""
    repo = UserRepository(pg_session)
    email_norm = _make_email()
    await repo.create(
        auth_provider_id=f"auth0|{uuid.uuid4().hex}",
        email_encrypted=b"enc",
        email_normalized=email_norm,
        display_name="Alice",
    )

    with pytest.raises(ConflictError):
        await repo.create(
            auth_provider_id=f"auth0|{uuid.uuid4().hex}",
            email_encrypted=b"enc2",
            email_normalized=email_norm,
            display_name="Bob",
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_membership_create_and_list(pg_session: AsyncSession) -> None:
    """Membership is created and visible in list_for_tenant."""
    t_repo = TenantRepository(pg_session)
    u_repo = UserRepository(pg_session)
    m_repo = MembershipRepository(pg_session)

    slug = f"t-{uuid.uuid4().hex[:8]}"
    tenant = await t_repo.create(type=TenantType.agency, display_name="Acme", slug=slug)
    user = await u_repo.create(
        auth_provider_id=f"auth0|{uuid.uuid4().hex}",
        email_encrypted=b"enc",
        email_normalized=_make_email(),
        display_name="Member",
    )
    membership = await m_repo.create(
        user_id=user.id,
        tenant_id=tenant.id,
        role=UserRole.agency_admin,
    )
    assert membership.tenant_id == tenant.id

    memberships = await m_repo.get_active_for_tenant(tenant.id)
    assert any(m.id == membership.id for m in memberships)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_audit_log_creation(pg_session: AsyncSession) -> None:
    """AdminAuditLog entry can be created and retrieved."""
    u_repo = UserRepository(pg_session)
    log_repo = AuditLogRepository(pg_session)

    actor = await u_repo.create(
        auth_provider_id=f"auth0|{uuid.uuid4().hex}",
        email_encrypted=b"enc",
        email_normalized=_make_email(),
        display_name="Admin",
    )
    entry = await log_repo.log(
        actor_user_id=actor.id,
        action="tenant.created",
        details={"slug": "test-slug"},
    )
    assert entry.action == "tenant.created"
    assert entry.actor_user_id == actor.id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tenant_soft_delete(pg_session: AsyncSession) -> None:
    """Soft-deleted tenant is not returned by get_by_slug."""
    repo = TenantRepository(pg_session)
    slug = f"del-{uuid.uuid4().hex[:8]}"
    tenant = await repo.create(type=TenantType.trial, display_name="Gone", slug=slug)
    await repo.soft_delete(tenant.id)

    with pytest.raises(TenantNotFoundError):
        await repo.get_by_slug(slug)
