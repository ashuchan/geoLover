"""Integration test fixtures and helpers — require PostgreSQL via testcontainers."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditRun, AuditStatus, AuditTrigger
from app.modules.categories.models import Category
from app.modules.identity.models import Tenant, TenantType
from app.modules.business_profile.models import Business, BusinessSource, BusinessStatus


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Shared helpers ─────────────────────────────────────────────────────────────


async def make_category(session: AsyncSession, *, slug: str = "bakery") -> Category:
    """Create a Category row directly (no repository abstraction exists)."""
    cat = Category(
        name="Bakery",
        slug=slug,
    )
    session.add(cat)
    await session.flush()
    return cat


async def make_tenant(
    session: AsyncSession,
    *,
    display_name: str = "Test Agency",
    slug: str = "test-agency",
) -> Tenant:
    """Create a Tenant row directly, bypassing slug reservation checks."""
    tenant = Tenant(
        type=TenantType.agency,
        display_name=display_name,
        slug=slug,
    )
    session.add(tenant)
    await session.flush()
    return tenant


async def make_business(
    session: AsyncSession,
    *,
    tenant: Tenant,
    category: Category,
    name: str = "Test Bakery",
) -> Business:
    """Create a Business row directly."""
    biz = Business(
        tenant_id=tenant.id,
        canonical_name=name,
        name_normalized=name.lower(),
        category_id=category.id,
        source=BusinessSource.agency_created,
        status=BusinessStatus.active,
    )
    session.add(biz)
    await session.flush()
    return biz


async def make_audit_run(
    session: AsyncSession,
    *,
    tenant: Tenant,
    business: Business,
) -> AuditRun:
    """Create an AuditRun row directly."""
    run = AuditRun(
        tenant_id=tenant.id,
        business_id=business.id,
        trigger=AuditTrigger.manual,
        status=AuditStatus.pending,
    )
    session.add(run)
    await session.flush()
    return run


# ── Integration-specific fixtures ──────────────────────────────────────────────


@pytest.fixture
def int_tenant_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def int_user_id() -> uuid.UUID:
    return uuid.uuid4()
