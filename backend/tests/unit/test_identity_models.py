"""Unit tests for identity module — models, enums, invariants."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.modules.identity.models import (
    AdminAuditLog,
    Membership,
    ReservedSlug,
    Tenant,
    TenantType,
    User,
    UserRole,
)


class TestTenantType:
    def test_values(self):
        assert TenantType.agency.value == "agency"
        assert TenantType.direct_business.value == "direct_business"
        assert TenantType.trial.value == "trial"

    def test_str_enum(self):
        assert TenantType.agency == "agency"


class TestUserRole:
    def test_all_roles_defined(self):
        roles = {r.value for r in UserRole}
        assert roles == {
            "platform_admin",
            "agency_admin",
            "agency_member",
            "business_owner",
            "business_member",
        }


class TestTenantInstantiation:
    def test_default_values(self):
        tenant = Tenant(
            type=TenantType.agency,
            display_name="Test Agency",
            slug="test-agency",
        )
        assert tenant.primary_country == "IN"
        assert tenant.deleted_at is None
        assert tenant.claimed_from_trial_id is None

    def test_id_is_uuid(self):
        tenant = Tenant(
            type=TenantType.direct_business,
            display_name="SMB",
            slug="smb",
        )
        assert isinstance(tenant.id, uuid.UUID)

    def test_created_at_is_timezone_aware(self):
        tenant = Tenant(
            type=TenantType.trial,
            display_name="Trial",
            slug="trial",
        )
        assert tenant.created_at.tzinfo is not None


class TestUserInstantiation:
    def test_defaults(self):
        user = User(
            auth_provider_id="auth0|123",
            email_encrypted=b"enc",
            email_normalized="test@example.com",
            display_name="Test User",
        )
        assert user.locale == "en-IN"
        assert user.deleted_at is None
        assert user.phone_encrypted is None
        assert user.last_login_at is None


class TestMembershipInstantiation:
    def test_defaults(self):
        tid = uuid.uuid4()
        uid = uuid.uuid4()
        m = Membership(
            user_id=uid,
            tenant_id=tid,
            role=UserRole.agency_admin,
        )
        assert m.business_scope_ids == []
        assert m.revoked_at is None
        assert m.granted_by_user_id is None

    def test_platform_admin_can_have_null_tenant(self):
        m = Membership(
            user_id=uuid.uuid4(),
            tenant_id=None,
            role=UserRole.platform_admin,
        )
        assert m.tenant_id is None
        assert m.role == UserRole.platform_admin


class TestAdminAuditLog:
    def test_instantiation(self):
        log = AdminAuditLog(
            actor_user_id=uuid.uuid4(),
            action="tenant.create",
        )
        assert log.tenant_id is None
        assert log.target_type is None
        assert log.details is None


class TestReservedSlug:
    def test_instantiation(self):
        rs = ReservedSlug(slug="app", reason="platform")
        assert rs.slug == "app"
