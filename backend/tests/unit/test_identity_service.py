"""Unit tests for identity service layer — TenantService, UserService, MembershipService."""

from __future__ import annotations

import base64
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.events import EventBus
from app.core.exceptions import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    TenantNotFoundError,
    ValidationError,
)
from app.modules.identity.models import Membership, Tenant, TenantType, User, UserRole
from app.modules.identity.service import (
    MembershipGranted,
    MembershipRevoked,
    MembershipService,
    TenantCreated,
    TenantService,
    UserRegistered,
    UserService,
)

TEST_MASTER_KEY = base64.b64encode(os.urandom(32)).decode()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_tenant(**kwargs) -> Tenant:
    defaults = dict(type=TenantType.agency, display_name="Acme", slug="acme")
    defaults.update(kwargs)
    return Tenant(**defaults)


def _make_user(**kwargs) -> User:
    defaults = dict(
        auth_provider_id="auth0|xyz",
        email_encrypted=b"enc",
        email_normalized="user@acme.com",
        display_name="Test User",
    )
    defaults.update(kwargs)
    return User(**defaults)


def _make_membership(**kwargs) -> Membership:
    defaults = dict(
        user_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        role=UserRole.agency_admin,
    )
    defaults.update(kwargs)
    return Membership(**defaults)


# ── TenantService tests ────────────────────────────────────────────────────────


class TestTenantServiceValidateSlug:
    def _make_svc(self) -> TenantService:
        return TenantService(MagicMock(), TEST_MASTER_KEY)

    def test_valid_slug_passes(self):
        svc = self._make_svc()
        svc._validate_slug("valid-slug-123")  # should not raise

    @pytest.mark.parametrize(
        "slug",
        ["AB", "ab", "toolongslugthisismorethanfortycharacterslong!", "has space", "has_underscore"],
    )
    def test_invalid_slug_raises(self, slug):
        svc = self._make_svc()
        with pytest.raises(ValidationError):
            svc._validate_slug(slug)


class TestTenantServiceCreate:
    @pytest.mark.asyncio
    async def test_create_tenant_happy_path(self):
        session = MagicMock()
        svc = TenantService(session, TEST_MASTER_KEY)

        tenant = _make_tenant()
        membership = _make_membership()

        svc._tenant_repo = MagicMock()
        svc._tenant_repo.create = AsyncMock(return_value=tenant)
        svc._tenant_repo.is_slug_reserved = AsyncMock(return_value=False)
        svc._tenant_repo.slug_exists = AsyncMock(return_value=False)
        svc._membership_repo = MagicMock()
        svc._membership_repo.create = AsyncMock(return_value=membership)
        svc._membership_repo.count_tenants_for_user = AsyncMock(return_value=0)
        svc._audit_repo = MagicMock()
        svc._audit_repo.log = AsyncMock(return_value=MagicMock())

        bus = EventBus()
        received_events = []

        @bus.subscribe(TenantCreated)
        async def handler(evt):
            received_events.append(evt)

        with patch("app.modules.identity.service.event_bus", bus):
            result = await svc.create_tenant(
                actor_user_id=uuid.uuid4(),
                tenant_type=TenantType.agency,
                display_name="Acme",
                slug="acme",
            )
            await svc.flush_pending_events()

        assert result is tenant
        assert len(received_events) == 1
        svc._membership_repo.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_tenant_agency_gets_agency_admin_role(self):
        session = MagicMock()
        svc = TenantService(session, TEST_MASTER_KEY)

        tenant = _make_tenant(type=TenantType.agency)
        membership = _make_membership()

        svc._tenant_repo = MagicMock()
        svc._tenant_repo.create = AsyncMock(return_value=tenant)
        svc._tenant_repo.is_slug_reserved = AsyncMock(return_value=False)
        svc._tenant_repo.slug_exists = AsyncMock(return_value=False)
        svc._membership_repo = MagicMock()
        svc._membership_repo.create = AsyncMock(return_value=membership)
        svc._membership_repo.count_tenants_for_user = AsyncMock(return_value=0)
        svc._audit_repo = MagicMock()
        svc._audit_repo.log = AsyncMock(return_value=MagicMock())

        with patch("app.modules.identity.service.event_bus", EventBus()):
            await svc.create_tenant(
                actor_user_id=uuid.uuid4(),
                tenant_type=TenantType.agency,
                display_name="Agency",
                slug="agency",
            )

        call_kwargs = svc._membership_repo.create.call_args[1]
        assert call_kwargs["role"] == UserRole.agency_admin

    @pytest.mark.asyncio
    async def test_create_tenant_direct_business_gets_business_owner_role(self):
        session = MagicMock()
        svc = TenantService(session, TEST_MASTER_KEY)

        tenant = _make_tenant(type=TenantType.direct_business)
        membership = _make_membership()

        svc._tenant_repo = MagicMock()
        svc._tenant_repo.create = AsyncMock(return_value=tenant)
        svc._tenant_repo.is_slug_reserved = AsyncMock(return_value=False)
        svc._tenant_repo.slug_exists = AsyncMock(return_value=False)
        svc._membership_repo = MagicMock()
        svc._membership_repo.create = AsyncMock(return_value=membership)
        svc._membership_repo.count_tenants_for_user = AsyncMock(return_value=0)
        svc._audit_repo = MagicMock()
        svc._audit_repo.log = AsyncMock(return_value=MagicMock())

        with patch("app.modules.identity.service.event_bus", EventBus()):
            await svc.create_tenant(
                actor_user_id=uuid.uuid4(),
                tenant_type=TenantType.direct_business,
                display_name="SMB",
                slug="smb",
            )

        call_kwargs = svc._membership_repo.create.call_args[1]
        assert call_kwargs["role"] == UserRole.business_owner

    @pytest.mark.asyncio
    async def test_create_tenant_at_limit_raises(self):
        svc = TenantService(MagicMock(), TEST_MASTER_KEY)
        svc._membership_repo = MagicMock()
        svc._membership_repo.count_tenants_for_user = AsyncMock(return_value=50)

        with pytest.raises(ConflictError):
            await svc.create_tenant(
                actor_user_id=uuid.uuid4(),
                tenant_type=TenantType.agency,
                display_name="Too Many",
                slug="too-many",
            )

    @pytest.mark.asyncio
    async def test_create_tenant_invalid_slug_raises(self):
        svc = TenantService(MagicMock(), TEST_MASTER_KEY)
        with pytest.raises(ValidationError):
            await svc.create_tenant(
                actor_user_id=uuid.uuid4(),
                tenant_type=TenantType.agency,
                display_name="x",
                slug="INVALID SLUG!",
            )

    @pytest.mark.asyncio
    async def test_suggest_slug_alternatives(self):
        svc = TenantService(MagicMock(), TEST_MASTER_KEY)
        svc._tenant_repo = MagicMock()
        svc._tenant_repo.slug_exists = AsyncMock(return_value=False)

        alts = await svc.suggest_slug_alternatives("acme", count=3)
        assert len(alts) == 3
        assert all("acme" in alt for alt in alts)


class TestTenantServiceUpdate:
    @pytest.mark.asyncio
    async def test_update_requires_admin_role(self):
        svc = TenantService(MagicMock(), TEST_MASTER_KEY)
        svc._membership_repo = MagicMock()
        svc._membership_repo.has_role = AsyncMock(return_value=False)
        svc._membership_repo.is_platform_admin = AsyncMock(return_value=False)

        with pytest.raises(PermissionDeniedError):
            await svc.update_tenant(
                actor_user_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                display_name="New Name",
            )

    @pytest.mark.asyncio
    async def test_platform_admin_can_update(self):
        svc = TenantService(MagicMock(), TEST_MASTER_KEY)
        tenant = _make_tenant(display_name="Updated")
        svc._membership_repo = MagicMock()
        svc._membership_repo.has_role = AsyncMock(return_value=False)
        svc._membership_repo.is_platform_admin = AsyncMock(return_value=True)
        svc._tenant_repo = MagicMock()
        svc._tenant_repo.update = AsyncMock(return_value=tenant)
        svc._audit_repo = MagicMock()
        svc._audit_repo.log = AsyncMock()

        result = await svc.update_tenant(
            actor_user_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            display_name="Updated",
        )
        assert result is tenant


# ── UserService tests ─────────────────────────────────────────────────────────


class TestUserService:
    @pytest.mark.asyncio
    async def test_get_or_create_creates_new_user(self):
        svc = UserService(MagicMock(), TEST_MASTER_KEY)
        svc._user_repo = MagicMock()
        svc._user_repo.get_by_auth_provider_id = AsyncMock(return_value=None)
        new_user = _make_user()
        svc._user_repo.create = AsyncMock(return_value=new_user)
        svc._membership_repo = MagicMock()

        bus = EventBus()
        received = []

        @bus.subscribe(UserRegistered)
        async def handler(evt):
            received.append(evt)

        with patch("app.modules.identity.service.event_bus", bus):
            user, created = await svc.get_or_create_from_auth(
                auth_provider_id="auth0|new",
                email="new@example.com",
                display_name="New User",
            )
            await svc.flush_pending_events()

        assert created is True
        assert user is new_user
        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_get_or_create_returns_existing_user(self):
        svc = UserService(MagicMock(), TEST_MASTER_KEY)
        existing_user = _make_user()
        svc._user_repo = MagicMock()
        svc._user_repo.get_by_auth_provider_id = AsyncMock(return_value=existing_user)
        svc._user_repo.update_last_login = AsyncMock()

        user, created = await svc.get_or_create_from_auth(
            auth_provider_id="auth0|xyz",
            email="user@example.com",
            display_name="Existing",
        )

        assert created is False
        assert user is existing_user
        svc._user_repo.update_last_login.assert_called_once_with(existing_user.id)

    @pytest.mark.asyncio
    async def test_get_or_create_with_invalid_email_raises(self):
        svc = UserService(MagicMock(), TEST_MASTER_KEY)
        svc._user_repo = MagicMock()
        svc._user_repo.get_by_auth_provider_id = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="Invalid email"):
            await svc.get_or_create_from_auth(
                auth_provider_id="auth0|x",
                email="not-an-email",
                display_name="User",
            )


# ── MembershipService tests ───────────────────────────────────────────────────


class TestMembershipService:
    @pytest.mark.asyncio
    async def test_grant_requires_agency_admin(self):
        svc = MembershipService(MagicMock())
        svc._membership_repo = MagicMock()
        svc._membership_repo.has_role = AsyncMock(return_value=False)
        svc._membership_repo.is_platform_admin = AsyncMock(return_value=False)

        with pytest.raises(PermissionDeniedError):
            await svc.grant(
                actor_user_id=uuid.uuid4(),
                target_user_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                role=UserRole.agency_member,
            )

    @pytest.mark.asyncio
    async def test_grant_platform_admin_role_requires_platform_admin(self):
        svc = MembershipService(MagicMock())
        svc._membership_repo = MagicMock()
        svc._membership_repo.has_role = AsyncMock(return_value=True)  # agency_admin
        svc._membership_repo.is_platform_admin = AsyncMock(return_value=False)

        with pytest.raises(PermissionDeniedError, match="platform_admin"):
            await svc.grant(
                actor_user_id=uuid.uuid4(),
                target_user_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                role=UserRole.platform_admin,
            )

    @pytest.mark.asyncio
    async def test_grant_nonexistent_tenant_raises(self):
        svc = MembershipService(MagicMock())
        svc._membership_repo = MagicMock()
        svc._membership_repo.has_role = AsyncMock(return_value=True)
        svc._membership_repo.is_platform_admin = AsyncMock(return_value=False)
        svc._tenant_repo = MagicMock()
        svc._tenant_repo.get_by_id = AsyncMock(side_effect=TenantNotFoundError("not found"))

        with pytest.raises(TenantNotFoundError):
            await svc.grant(
                actor_user_id=uuid.uuid4(),
                target_user_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                role=UserRole.agency_member,
            )

    @pytest.mark.asyncio
    async def test_grant_nonexistent_target_user_raises(self):
        svc = MembershipService(MagicMock())
        svc._membership_repo = MagicMock()
        svc._membership_repo.has_role = AsyncMock(return_value=True)
        svc._membership_repo.is_platform_admin = AsyncMock(return_value=False)
        svc._tenant_repo = MagicMock()
        svc._tenant_repo.get_by_id = AsyncMock(return_value=_make_tenant())
        svc._user_repo = MagicMock()
        svc._user_repo.get_by_id = AsyncMock(side_effect=NotFoundError("user not found"))

        with pytest.raises(NotFoundError):
            await svc.grant(
                actor_user_id=uuid.uuid4(),
                target_user_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                role=UserRole.agency_member,
            )

    @pytest.mark.asyncio
    async def test_grant_success_emits_event(self):
        svc = MembershipService(MagicMock())
        membership = _make_membership()
        svc._membership_repo = MagicMock()
        svc._membership_repo.has_role = AsyncMock(return_value=True)
        svc._membership_repo.is_platform_admin = AsyncMock(return_value=False)
        svc._membership_repo.create = AsyncMock(return_value=membership)
        svc._tenant_repo = MagicMock()
        svc._tenant_repo.get_by_id = AsyncMock(return_value=_make_tenant())
        svc._user_repo = MagicMock()
        svc._user_repo.get_by_id = AsyncMock(return_value=MagicMock())
        svc._audit_repo = MagicMock()
        svc._audit_repo.log = AsyncMock()

        bus = EventBus()
        received = []

        @bus.subscribe(MembershipGranted)
        async def handler(evt):
            received.append(evt)

        with patch("app.modules.identity.service.event_bus", bus):
            result = await svc.grant(
                actor_user_id=uuid.uuid4(),
                target_user_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                role=UserRole.agency_member,
            )
            await svc.flush_pending_events()

        assert result is membership
        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_revoke_requires_admin(self):
        svc = MembershipService(MagicMock())
        svc._membership_repo = MagicMock()
        svc._membership_repo.has_role = AsyncMock(return_value=False)
        svc._membership_repo.is_platform_admin = AsyncMock(return_value=False)

        with pytest.raises(PermissionDeniedError):
            await svc.revoke(
                actor_user_id=uuid.uuid4(),
                membership_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_revoke_membership_not_found_raises(self):
        svc = MembershipService(MagicMock())
        svc._membership_repo = MagicMock()
        svc._membership_repo.has_role = AsyncMock(return_value=True)
        svc._membership_repo.is_platform_admin = AsyncMock(return_value=False)
        svc._membership_repo.get_active_membership = AsyncMock(return_value=None)

        with pytest.raises(PermissionDeniedError):
            await svc.revoke(
                actor_user_id=uuid.uuid4(),
                membership_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_revoke_self_raises(self):
        svc = MembershipService(MagicMock())
        actor_id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        membership = _make_membership(user_id=actor_id, tenant_id=tenant_id)
        svc._membership_repo = MagicMock()
        svc._membership_repo.has_role = AsyncMock(return_value=True)
        svc._membership_repo.is_platform_admin = AsyncMock(return_value=False)
        svc._membership_repo.get_active_membership = AsyncMock(return_value=membership)

        with pytest.raises(PermissionDeniedError, match="own"):
            await svc.revoke(
                actor_user_id=actor_id,
                membership_id=membership.id,
                tenant_id=tenant_id,
            )

    @pytest.mark.asyncio
    async def test_revoke_last_admin_raises(self):
        svc = MembershipService(MagicMock())
        membership = _make_membership(role=UserRole.agency_admin)
        actor_id = uuid.uuid4()
        svc._membership_repo = MagicMock()
        svc._membership_repo.has_role = AsyncMock(return_value=True)
        svc._membership_repo.is_platform_admin = AsyncMock(return_value=False)
        svc._membership_repo.get_active_membership = AsyncMock(return_value=membership)
        svc._membership_repo.count_active_admins = AsyncMock(return_value=1)

        with pytest.raises(PermissionDeniedError, match="last admin"):
            await svc.revoke(
                actor_user_id=actor_id,
                membership_id=membership.id,
                tenant_id=membership.tenant_id,
            )

    @pytest.mark.asyncio
    async def test_revoke_success_emits_event(self):
        svc = MembershipService(MagicMock())
        membership = _make_membership()
        other_member = _make_membership(tenant_id=membership.tenant_id, role=UserRole.agency_admin)
        actor_id = uuid.uuid4()
        svc._membership_repo = MagicMock()
        svc._membership_repo.has_role = AsyncMock(return_value=True)
        svc._membership_repo.is_platform_admin = AsyncMock(return_value=False)
        svc._membership_repo.get_active_membership = AsyncMock(return_value=membership)
        svc._membership_repo.count_active_admins = AsyncMock(return_value=2)
        svc._membership_repo.revoke = AsyncMock(return_value=membership)
        svc._audit_repo = MagicMock()
        svc._audit_repo.log = AsyncMock()

        bus = EventBus()
        received = []

        @bus.subscribe(MembershipRevoked)
        async def handler(evt):
            received.append(evt)

        with patch("app.modules.identity.service.event_bus", bus):
            await svc.revoke(
                actor_user_id=uuid.uuid4(),
                membership_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
            )
            await svc.flush_pending_events()

        assert len(received) == 1


# ── TenantService get/slug methods ───────────────────────────────────────────


class TestTenantServiceGetters:
    @pytest.mark.asyncio
    async def test_get_tenant(self):
        svc = TenantService(MagicMock(), TEST_MASTER_KEY)
        tenant = _make_tenant()
        svc._tenant_repo = MagicMock()
        svc._tenant_repo.get_by_id = AsyncMock(return_value=tenant)

        result = await svc.get_tenant(tenant.id)
        assert result is tenant

    @pytest.mark.asyncio
    async def test_get_tenant_by_slug(self):
        svc = TenantService(MagicMock(), TEST_MASTER_KEY)
        tenant = _make_tenant()
        svc._tenant_repo = MagicMock()
        svc._tenant_repo.get_by_slug = AsyncMock(return_value=tenant)

        result = await svc.get_tenant_by_slug("acme")
        assert result is tenant

    @pytest.mark.asyncio
    async def test_suggest_slug_alternatives_hits_100_iterations(self):
        svc = TenantService(MagicMock(), TEST_MASTER_KEY)
        svc._tenant_repo = MagicMock()
        # Always taken → loop will exhaust at 100 and break early
        svc._tenant_repo.slug_exists = AsyncMock(return_value=True)

        alts = await svc.suggest_slug_alternatives("x", count=3)
        assert len(alts) == 0  # all taken, break at i > 100


# ── UserService getters ───────────────────────────────────────────────────────


class TestUserServiceGetters:
    @pytest.mark.asyncio
    async def test_get_user(self):
        svc = UserService(MagicMock(), TEST_MASTER_KEY)
        user = _make_user()
        svc._user_repo = MagicMock()
        svc._user_repo.get_by_id = AsyncMock(return_value=user)

        result = await svc.get_user(user.id)
        assert result is user

    @pytest.mark.asyncio
    async def test_get_memberships(self):
        svc = UserService(MagicMock(), TEST_MASTER_KEY)
        m = _make_membership()
        svc._membership_repo = MagicMock()
        svc._membership_repo.get_active_for_user = AsyncMock(return_value=[m])

        result = await svc.get_memberships(m.user_id)
        assert result == [m]

    @pytest.mark.asyncio
    async def test_update_email(self):
        svc = UserService(MagicMock(), TEST_MASTER_KEY)
        user = _make_user()
        svc._user_repo = MagicMock()
        svc._user_repo.update_email = AsyncMock(return_value=user)

        result = await svc.update_email(user.id, new_email="new@example.com")
        assert result is user
        svc._user_repo.update_email.assert_called_once()


# ── MembershipService list ────────────────────────────────────────────────────


class TestMembershipServiceList:
    @pytest.mark.asyncio
    async def test_list_tenant_members(self):
        svc = MembershipService(MagicMock())
        m = _make_membership()
        svc._membership_repo = MagicMock()
        svc._membership_repo.get_active_for_tenant = AsyncMock(return_value=[m])

        result = await svc.list_tenant_members(m.tenant_id)
        assert result == [m]


# ── Domain event tests ────────────────────────────────────────────────────────


class TestIdentityDomainEvents:
    def test_tenant_created_event_type(self):
        evt = TenantCreated(
            tenant_id=uuid.uuid4(),
            tenant_type=TenantType.agency,
            slug="acme",
        )
        assert evt.event_type == "TenantCreated"

    def test_user_registered_event_type(self):
        evt = UserRegistered(user_id=uuid.uuid4())
        assert evt.event_type == "UserRegistered"

    def test_membership_granted_event_type(self):
        evt = MembershipGranted(
            membership_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            role=UserRole.agency_admin,
        )
        assert evt.event_type == "MembershipGranted"

    def test_membership_revoked_event_type(self):
        evt = MembershipRevoked(
            membership_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
        )
        assert evt.event_type == "MembershipRevoked"
