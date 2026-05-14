"""Unit tests for identity repository layer — mock-based, no live DB."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import ConflictError, NotFoundError, TenantNotFoundError
from app.modules.identity.models import (
    AdminAuditLog,
    Membership,
    ReservedSlug,
    Tenant,
    TenantType,
    User,
    UserRole,
)
from app.modules.identity.repository import (
    AuditLogRepository,
    MembershipRepository,
    TenantRepository,
    UserRepository,
)


def _mock_session() -> MagicMock:
    s = MagicMock()
    s.execute = AsyncMock()
    s.flush = AsyncMock()
    s.add = MagicMock()
    return s


def _scalar_result(value):
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


def _scalars_result(values):
    r = MagicMock()
    r.scalars.return_value.all.return_value = values
    return r


# ── TenantRepository ──────────────────────────────────────────────────────────


class TestTenantRepository:
    def _repo(self):
        return TenantRepository(_mock_session())

    @pytest.mark.asyncio
    async def test_get_by_id_returns_tenant(self):
        repo = TenantRepository(_mock_session())
        tenant = Tenant(type=TenantType.agency, display_name="Acme", slug="acme")
        repo._session.execute = AsyncMock(return_value=_scalar_result(tenant))

        result = await repo.get_by_id(tenant.id)
        assert result is tenant

    @pytest.mark.asyncio
    async def test_get_by_id_not_found_raises(self):
        repo = TenantRepository(_mock_session())
        repo._session.execute = AsyncMock(return_value=_scalar_result(None))

        with pytest.raises(TenantNotFoundError):
            await repo.get_by_id(uuid.uuid4())

    @pytest.mark.asyncio
    async def test_get_by_slug_returns_tenant(self):
        repo = TenantRepository(_mock_session())
        tenant = Tenant(type=TenantType.agency, display_name="Acme", slug="acme")
        repo._session.execute = AsyncMock(return_value=_scalar_result(tenant))

        result = await repo.get_by_slug("acme")
        assert result is tenant

    @pytest.mark.asyncio
    async def test_get_by_slug_not_found_raises(self):
        repo = TenantRepository(_mock_session())
        repo._session.execute = AsyncMock(return_value=_scalar_result(None))

        with pytest.raises(TenantNotFoundError):
            await repo.get_by_slug("missing")

    @pytest.mark.asyncio
    async def test_slug_exists_true(self):
        repo = TenantRepository(_mock_session())
        repo._session.execute = AsyncMock(return_value=_scalar_result(uuid.uuid4()))

        assert await repo.slug_exists("taken") is True

    @pytest.mark.asyncio
    async def test_slug_exists_false(self):
        repo = TenantRepository(_mock_session())
        repo._session.execute = AsyncMock(return_value=_scalar_result(None))

        assert await repo.slug_exists("free") is False

    @pytest.mark.asyncio
    async def test_is_slug_reserved_true(self):
        repo = TenantRepository(_mock_session())
        repo._session.execute = AsyncMock(return_value=_scalar_result("app"))

        assert await repo.is_slug_reserved("app") is True

    @pytest.mark.asyncio
    async def test_is_slug_reserved_false(self):
        repo = TenantRepository(_mock_session())
        repo._session.execute = AsyncMock(return_value=_scalar_result(None))

        assert await repo.is_slug_reserved("mycompany") is False

    @pytest.mark.asyncio
    async def test_create_adds_and_flushes(self):
        repo = TenantRepository(_mock_session())
        # Execute returns None for slug checks (not reserved, not taken)
        repo._session.execute = AsyncMock(return_value=_scalar_result(None))
        repo._session.flush = AsyncMock()

        result = await repo.create(
            type=TenantType.agency,
            display_name="Acme",
            slug="acme",
        )
        repo._session.add.assert_called_once()
        repo._session.flush.assert_called_once()
        assert isinstance(result, Tenant)

    @pytest.mark.asyncio
    async def test_update_patches_fields(self):
        repo = TenantRepository(_mock_session())
        tenant = Tenant(type=TenantType.agency, display_name="Old", slug="acme")
        repo._session.execute = AsyncMock(return_value=_scalar_result(tenant))
        repo._session.flush = AsyncMock()

        result = await repo.update(tenant.id, display_name="New Name")
        repo._session.flush.assert_called_once()
        assert result is tenant

    @pytest.mark.asyncio
    async def test_update_not_found_raises(self):
        repo = TenantRepository(_mock_session())
        repo._session.execute = AsyncMock(return_value=_scalar_result(None))

        with pytest.raises(TenantNotFoundError):
            await repo.update(uuid.uuid4(), display_name="x")

    @pytest.mark.asyncio
    async def test_soft_delete_sets_deleted_at(self):
        repo = TenantRepository(_mock_session())
        tenant = Tenant(type=TenantType.agency, display_name="Acme", slug="acme")
        repo._session.execute = AsyncMock(return_value=_scalar_result(tenant))
        repo._session.flush = AsyncMock()

        result = await repo.soft_delete(tenant.id)
        assert result is tenant
        assert result.deleted_at is not None


# ── UserRepository ────────────────────────────────────────────────────────────


class TestUserRepository:
    @pytest.mark.asyncio
    async def test_get_by_id_found(self):
        repo = UserRepository(_mock_session())
        user = User(
            auth_provider_id="auth0|abc",
            email_encrypted=b"enc",
            email_normalized="a@b.com",
            display_name="User",
        )
        repo._session.execute = AsyncMock(return_value=_scalar_result(user))

        result = await repo.get_by_id(user.id)
        assert result is user

    @pytest.mark.asyncio
    async def test_get_by_id_not_found_raises(self):
        repo = UserRepository(_mock_session())
        repo._session.execute = AsyncMock(return_value=_scalar_result(None))

        with pytest.raises(NotFoundError):
            await repo.get_by_id(uuid.uuid4())

    @pytest.mark.asyncio
    async def test_get_by_auth_provider_id_found(self):
        repo = UserRepository(_mock_session())
        user = User(
            auth_provider_id="auth0|abc",
            email_encrypted=b"enc",
            email_normalized="a@b.com",
            display_name="User",
        )
        repo._session.execute = AsyncMock(return_value=_scalar_result(user))

        result = await repo.get_by_auth_provider_id("auth0|abc")
        assert result is user

    @pytest.mark.asyncio
    async def test_get_by_auth_provider_id_none(self):
        repo = UserRepository(_mock_session())
        repo._session.execute = AsyncMock(return_value=_scalar_result(None))

        result = await repo.get_by_auth_provider_id("auth0|missing")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_email_normalized_found(self):
        repo = UserRepository(_mock_session())
        user = User(
            auth_provider_id="auth0|abc",
            email_encrypted=b"enc",
            email_normalized="a@b.com",
            display_name="User",
        )
        repo._session.execute = AsyncMock(return_value=_scalar_result(user))

        result = await repo.get_by_email_normalized("a@b.com")
        assert result is user

    @pytest.mark.asyncio
    async def test_create_adds_user(self):
        repo = UserRepository(_mock_session())
        # get_by_email_normalized call returns None (no conflict)
        repo._session.execute = AsyncMock(return_value=_scalar_result(None))
        repo._session.flush = AsyncMock()

        result = await repo.create(
            auth_provider_id="auth0|new",
            email_encrypted=b"enc",
            email_normalized="new@b.com",
            display_name="New",
        )
        repo._session.add.assert_called_once()
        repo._session.flush.assert_called_once()
        assert isinstance(result, User)

    @pytest.mark.asyncio
    async def test_update_last_login_executes(self):
        repo = UserRepository(_mock_session())
        repo._session.execute = AsyncMock(return_value=MagicMock())

        # update_last_login fires a SQL UPDATE; it doesn't modify the Python obj
        await repo.update_last_login(uuid.uuid4())
        repo._session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_email(self):
        repo = UserRepository(_mock_session())
        user = User(
            auth_provider_id="auth0|abc",
            email_encrypted=b"enc",
            email_normalized="old@b.com",
            display_name="User",
        )
        repo._session.execute = AsyncMock(return_value=_scalar_result(user))
        repo._session.flush = AsyncMock()

        result = await repo.update_email(
            user.id,
            email_encrypted=b"newenc",
            email_normalized="new@b.com",
        )
        assert result is user
        assert result.email_encrypted == b"newenc"

    @pytest.mark.asyncio
    async def test_soft_delete_user(self):
        repo = UserRepository(_mock_session())
        user = User(
            auth_provider_id="auth0|abc",
            email_encrypted=b"enc",
            email_normalized="a@b.com",
            display_name="User",
        )
        repo._session.execute = AsyncMock(return_value=_scalar_result(user))
        repo._session.flush = AsyncMock()

        result = await repo.soft_delete(user.id)
        assert result is user
        assert result.deleted_at is not None


# ── MembershipRepository ──────────────────────────────────────────────────────


class TestMembershipRepository:
    @pytest.mark.asyncio
    async def test_get_active_found(self):
        repo = MembershipRepository(_mock_session())
        m = Membership(
            user_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            role=UserRole.agency_admin,
        )
        repo._session.execute = AsyncMock(return_value=_scalar_result(m))

        result = await repo.get_active(m.user_id, m.tenant_id, UserRole.agency_admin)
        assert result is m

    @pytest.mark.asyncio
    async def test_get_active_not_found(self):
        repo = MembershipRepository(_mock_session())
        repo._session.execute = AsyncMock(return_value=_scalar_result(None))

        result = await repo.get_active(uuid.uuid4(), uuid.uuid4(), UserRole.agency_member)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_active_for_user(self):
        repo = MembershipRepository(_mock_session())
        m = Membership(
            user_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            role=UserRole.agency_admin,
        )
        repo._session.execute = AsyncMock(return_value=_scalars_result([m]))

        result = await repo.get_active_for_user(m.user_id)
        assert result == [m]

    @pytest.mark.asyncio
    async def test_get_active_for_tenant(self):
        repo = MembershipRepository(_mock_session())
        tid = uuid.uuid4()
        m = Membership(user_id=uuid.uuid4(), tenant_id=tid, role=UserRole.agency_member)
        repo._session.execute = AsyncMock(return_value=_scalars_result([m]))

        result = await repo.get_active_for_tenant(tid)
        assert result == [m]

    @pytest.mark.asyncio
    async def test_create_membership(self):
        repo = MembershipRepository(_mock_session())
        repo._session.execute = AsyncMock(return_value=_scalar_result(None))
        repo._session.flush = AsyncMock()

        result = await repo.create(
            user_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            role=UserRole.agency_member,
        )
        repo._session.add.assert_called_once()
        repo._session.flush.assert_called_once()
        assert isinstance(result, Membership)

    @pytest.mark.asyncio
    async def test_create_membership_conflict_raises(self):
        repo = MembershipRepository(_mock_session())
        existing = Membership(
            user_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            role=UserRole.agency_admin,
        )
        repo._session.execute = AsyncMock(return_value=_scalar_result(existing))

        with pytest.raises(ConflictError):
            await repo.create(
                user_id=existing.user_id,
                tenant_id=existing.tenant_id,
                role=UserRole.agency_admin,
            )

    @pytest.mark.asyncio
    async def test_get_active_membership_found(self):
        repo = MembershipRepository(_mock_session())
        m = Membership(user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), role=UserRole.agency_member)
        repo._session.execute = AsyncMock(return_value=_scalar_result(m))

        result = await repo.get_active_membership(m.id, tenant_id=m.tenant_id)
        assert result is m

    @pytest.mark.asyncio
    async def test_get_active_membership_not_found(self):
        repo = MembershipRepository(_mock_session())
        repo._session.execute = AsyncMock(return_value=_scalar_result(None))

        result = await repo.get_active_membership(uuid.uuid4(), tenant_id=uuid.uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_count_active_admins(self):
        repo = MembershipRepository(_mock_session())
        mock_result = MagicMock()
        mock_result.scalar_one = MagicMock(return_value=3)
        repo._session.execute = AsyncMock(return_value=mock_result)

        count = await repo.count_active_admins(uuid.uuid4())
        assert count == 3

    @pytest.mark.asyncio
    async def test_count_tenants_for_user(self):
        repo = MembershipRepository(_mock_session())
        mock_result = MagicMock()
        mock_result.scalar_one = MagicMock(return_value=5)
        repo._session.execute = AsyncMock(return_value=mock_result)

        count = await repo.count_tenants_for_user(uuid.uuid4())
        assert count == 5

    @pytest.mark.asyncio
    async def test_create_platform_admin_membership_conflict_raises(self):
        repo = MembershipRepository(_mock_session())
        existing = Membership(
            user_id=uuid.uuid4(),
            tenant_id=None,
            role=UserRole.platform_admin,
        )
        repo._session.execute = AsyncMock(return_value=_scalar_result(existing))

        with pytest.raises(ConflictError):
            await repo.create(
                user_id=existing.user_id,
                tenant_id=None,
                role=UserRole.platform_admin,
            )

    @pytest.mark.asyncio
    async def test_revoke_membership(self):
        repo = MembershipRepository(_mock_session())
        m = Membership(
            user_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            role=UserRole.agency_member,
        )
        repo._session.execute = AsyncMock(return_value=_scalar_result(m))
        repo._session.flush = AsyncMock()

        result = await repo.revoke(m.id, tenant_id=m.tenant_id)
        assert result is m
        assert m.revoked_at is not None

    @pytest.mark.asyncio
    async def test_revoke_not_found_raises(self):
        repo = MembershipRepository(_mock_session())
        repo._session.execute = AsyncMock(return_value=_scalar_result(None))

        with pytest.raises(NotFoundError):
            await repo.revoke(uuid.uuid4(), tenant_id=uuid.uuid4())

    @pytest.mark.asyncio
    async def test_has_role_true(self):
        repo = MembershipRepository(_mock_session())
        repo._session.execute = AsyncMock(return_value=_scalar_result(uuid.uuid4()))

        result = await repo.has_role(uuid.uuid4(), uuid.uuid4(), UserRole.agency_admin)
        assert result is True

    @pytest.mark.asyncio
    async def test_has_role_false(self):
        repo = MembershipRepository(_mock_session())
        repo._session.execute = AsyncMock(return_value=_scalar_result(None))

        result = await repo.has_role(uuid.uuid4(), uuid.uuid4(), UserRole.agency_member)
        assert result is False

    @pytest.mark.asyncio
    async def test_is_platform_admin_true(self):
        repo = MembershipRepository(_mock_session())
        repo._session.execute = AsyncMock(return_value=_scalar_result(uuid.uuid4()))

        assert await repo.is_platform_admin(uuid.uuid4()) is True

    @pytest.mark.asyncio
    async def test_is_platform_admin_false(self):
        repo = MembershipRepository(_mock_session())
        repo._session.execute = AsyncMock(return_value=_scalar_result(None))

        assert await repo.is_platform_admin(uuid.uuid4()) is False

    @pytest.mark.asyncio
    async def test_has_business_scope_access_true(self):
        repo = MembershipRepository(_mock_session())
        repo._session.execute = AsyncMock(return_value=_scalar_result(uuid.uuid4()))

        result = await repo.has_business_scope_access(
            uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_has_business_scope_access_false(self):
        repo = MembershipRepository(_mock_session())
        repo._session.execute = AsyncMock(return_value=_scalar_result(None))

        result = await repo.has_business_scope_access(
            uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        )
        assert result is False


# ── AuditLogRepository ────────────────────────────────────────────────────────


class TestAuditLogRepository:
    @pytest.mark.asyncio
    async def test_log_creates_entry(self):
        repo = AuditLogRepository(_mock_session())
        repo._session.flush = AsyncMock()

        actor_id = uuid.uuid4()
        result = await repo.log(
            actor_user_id=actor_id,
            action="tenant.create",
            tenant_id=uuid.uuid4(),
            details={"key": "value"},
        )
        repo._session.add.assert_called_once()
        repo._session.flush.assert_called_once()
        assert isinstance(result, AdminAuditLog)
        assert result.actor_user_id == actor_id
        assert result.action == "tenant.create"

    @pytest.mark.asyncio
    async def test_log_minimal(self):
        repo = AuditLogRepository(_mock_session())
        repo._session.flush = AsyncMock()

        result = await repo.log(actor_user_id=uuid.uuid4(), action="user.login")
        assert result.tenant_id is None
        assert result.details is None
