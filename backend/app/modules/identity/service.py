"""Identity & Tenancy service layer.

Orchestrates repositories, enforces domain invariants, emits domain events.
Never calls repositories from other modules directly.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import DomainEvent, event_bus
from app.core.exceptions import (
    AuthenticationError,
    ConflictError,
    PermissionDeniedError,
    TenantNotFoundError,
    TenantSuspendedError,
    ValidationError,
)
from app.core.security import encrypt_pii, normalize_email, normalize_text
from app.modules.identity.models import Membership, Tenant, TenantType, User, UserRole
from app.modules.identity.repository import (
    AuditLogRepository,
    MembershipRepository,
    TenantRepository,
    UserRepository,
)

import re

_SLUG_RE = re.compile(r"^[a-z0-9-]{3,40}$")
_MAX_TENANTS_PER_USER = 50


# ── Domain events ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TenantCreated(DomainEvent):
    tenant_id: uuid.UUID = uuid.UUID(int=0)
    tenant_type: TenantType = TenantType.direct_business
    slug: str = ""


@dataclass(frozen=True)
class UserRegistered(DomainEvent):
    user_id: uuid.UUID = uuid.UUID(int=0)
    tenant_id: Optional[uuid.UUID] = None


@dataclass(frozen=True)
class MembershipGranted(DomainEvent):
    membership_id: uuid.UUID = uuid.UUID(int=0)
    user_id: uuid.UUID = uuid.UUID(int=0)
    tenant_id: uuid.UUID = uuid.UUID(int=0)
    role: UserRole = UserRole.business_member


@dataclass(frozen=True)
class MembershipRevoked(DomainEvent):
    membership_id: uuid.UUID = uuid.UUID(int=0)
    user_id: uuid.UUID = uuid.UUID(int=0)
    tenant_id: uuid.UUID = uuid.UUID(int=0)


# ── TenantService ─────────────────────────────────────────────────────────────


class TenantService:
    def __init__(self, session: AsyncSession, master_key_b64: str) -> None:
        self._session = session
        self._master_key = master_key_b64
        self._tenant_repo = TenantRepository(session)
        self._membership_repo = MembershipRepository(session)
        self._audit_repo = AuditLogRepository(session)
        self._pending_events: list[DomainEvent] = []

    @property
    def pending_events(self) -> list[DomainEvent]:
        return list(self._pending_events)

    async def flush_pending_events(self) -> None:
        events, self._pending_events = self._pending_events, []
        for evt in events:
            await event_bus.publish(evt)

    def _validate_slug(self, slug: str) -> None:
        if not _SLUG_RE.match(slug):
            raise ValidationError(
                f"Invalid slug '{slug}'. Must be 3-40 chars, lowercase alphanumeric and hyphens only."
            )

    async def create_tenant(
        self,
        *,
        actor_user_id: uuid.UUID,
        tenant_type: TenantType,
        display_name: str,
        slug: str,
        primary_country: str = "IN",
        claimed_from_trial_id: Optional[uuid.UUID] = None,
    ) -> Tenant:
        self._validate_slug(slug)

        tenant_count = await self._membership_repo.count_tenants_for_user(actor_user_id)
        if tenant_count >= _MAX_TENANTS_PER_USER:
            raise ConflictError(f"Maximum of {_MAX_TENANTS_PER_USER} tenants per user reached")

        tenant = await self._tenant_repo.create(
            type=tenant_type,
            display_name=display_name,
            slug=slug,
            primary_country=primary_country,
            claimed_from_trial_id=claimed_from_trial_id,
        )

        # First member gets admin role based on tenant type
        role = (
            UserRole.agency_admin
            if tenant_type == TenantType.agency
            else UserRole.business_owner
        )
        await self._membership_repo.create(
            user_id=actor_user_id,
            tenant_id=tenant.id,
            role=role,
            granted_by_user_id=actor_user_id,
        )

        await self._audit_repo.log(
            actor_user_id=actor_user_id,
            action="tenant.create",
            tenant_id=tenant.id,
            target_type="Tenant",
            target_id=tenant.id,
            details={"type": tenant_type, "slug": slug},
        )

        self._pending_events.append(
            TenantCreated(tenant_id=tenant.id, tenant_type=tenant_type, slug=slug)
        )
        return tenant

    async def update_tenant(
        self,
        *,
        actor_user_id: uuid.UUID,
        tenant_id: uuid.UUID,
        display_name: Optional[str] = None,
        primary_country: Optional[str] = None,
    ) -> Tenant:
        # Verify actor has admin rights
        has_access = await self._membership_repo.has_role(
            actor_user_id,
            tenant_id,
            UserRole.agency_admin,
            UserRole.business_owner,
        ) or await self._membership_repo.is_platform_admin(actor_user_id)

        if not has_access:
            raise PermissionDeniedError("Insufficient permissions to update tenant")

        tenant = await self._tenant_repo.update(
            tenant_id,
            display_name=display_name,
            primary_country=primary_country,
        )
        await self._audit_repo.log(
            actor_user_id=actor_user_id,
            action="tenant.update",
            tenant_id=tenant_id,
            target_type="Tenant",
            target_id=tenant_id,
        )
        return tenant

    async def get_tenant(self, tenant_id: uuid.UUID) -> Tenant:
        return await self._tenant_repo.get_by_id(tenant_id)

    async def get_tenant_by_slug(self, slug: str) -> Tenant:
        return await self._tenant_repo.get_by_slug(slug)

    async def suggest_slug_alternatives(self, base_slug: str, count: int = 3) -> list[str]:
        """Return up to *count* non-colliding slug alternatives."""
        alternatives = []
        i = 1
        while len(alternatives) < count:
            candidate = f"{base_slug}-{i}"[:40]
            if not await self._tenant_repo.slug_exists(candidate):
                alternatives.append(candidate)
            i += 1
            if i > 100:
                break
        return alternatives


# ── UserService ───────────────────────────────────────────────────────────────


class UserService:
    def __init__(self, session: AsyncSession, master_key_b64: str) -> None:
        self._session = session
        self._master_key = master_key_b64
        self._user_repo = UserRepository(session)
        self._membership_repo = MembershipRepository(session)
        self._pending_events: list[DomainEvent] = []

    @property
    def pending_events(self) -> list[DomainEvent]:
        return list(self._pending_events)

    async def flush_pending_events(self) -> None:
        events, self._pending_events = self._pending_events, []
        for evt in events:
            await event_bus.publish(evt)

    async def get_or_create_from_auth(
        self,
        *,
        auth_provider_id: str,
        email: str,
        display_name: str,
        locale: str = "en-IN",
    ) -> tuple[User, bool]:
        """Return (user, created) — creates the user if not found by auth_provider_id."""
        existing = await self._user_repo.get_by_auth_provider_id(auth_provider_id)
        if existing:
            await self._user_repo.update_last_login(existing.id)
            return existing, False

        email_normalised = normalize_email(email)
        email_encrypted = encrypt_pii(self._master_key, email)
        user = await self._user_repo.create(
            auth_provider_id=auth_provider_id,
            email_encrypted=email_encrypted,
            email_normalized=email_normalised,
            display_name=normalize_text(display_name),
            locale=locale,
        )
        self._pending_events.append(UserRegistered(user_id=user.id, tenant_id=None))
        return user, True

    async def get_user(self, user_id: uuid.UUID) -> User:
        return await self._user_repo.get_by_id(user_id)

    async def get_memberships(self, user_id: uuid.UUID) -> Sequence[Membership]:
        return await self._membership_repo.get_active_for_user(user_id)

    async def update_email(
        self,
        user_id: uuid.UUID,
        *,
        new_email: str,
    ) -> User:
        email_normalized = normalize_email(new_email)
        email_encrypted = encrypt_pii(self._master_key, new_email)
        return await self._user_repo.update_email(
            user_id,
            email_encrypted=email_encrypted,
            email_normalized=email_normalized,
        )


# ── MembershipService ─────────────────────────────────────────────────────────


class MembershipService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._membership_repo = MembershipRepository(session)
        self._tenant_repo = TenantRepository(session)
        self._user_repo = UserRepository(session)
        self._audit_repo = AuditLogRepository(session)
        self._pending_events: list[DomainEvent] = []

    @property
    def pending_events(self) -> list[DomainEvent]:
        return list(self._pending_events)

    async def flush_pending_events(self) -> None:
        events, self._pending_events = self._pending_events, []
        for evt in events:
            await event_bus.publish(evt)

    async def grant(
        self,
        *,
        actor_user_id: uuid.UUID,
        target_user_id: uuid.UUID,
        tenant_id: uuid.UUID,
        role: UserRole,
        business_scope_ids: Optional[list[uuid.UUID]] = None,
    ) -> Membership:
        # Actor must be agency_admin or platform_admin
        is_agency_admin = await self._membership_repo.has_role(
            actor_user_id, tenant_id, UserRole.agency_admin
        )
        is_platform_admin = await self._membership_repo.is_platform_admin(actor_user_id)

        if not (is_agency_admin or is_platform_admin):
            raise PermissionDeniedError("Only agency_admin or platform_admin can grant memberships")

        if role == UserRole.platform_admin and not is_platform_admin:
            raise PermissionDeniedError("Only platform_admin can grant platform_admin role")

        # Validate tenant and target user exist before creating membership
        await self._tenant_repo.get_by_id(tenant_id)
        await self._user_repo.get_by_id(target_user_id)

        membership = await self._membership_repo.create(
            user_id=target_user_id,
            tenant_id=tenant_id,
            role=role,
            granted_by_user_id=actor_user_id,
            business_scope_ids=business_scope_ids,
        )

        await self._audit_repo.log(
            actor_user_id=actor_user_id,
            action="membership.grant",
            tenant_id=tenant_id,
            target_type="Membership",
            target_id=membership.id,
            details={"role": role, "target_user_id": str(target_user_id)},
        )
        self._pending_events.append(
            MembershipGranted(
                membership_id=membership.id,
                user_id=target_user_id,
                tenant_id=tenant_id,
                role=role,
            )
        )
        return membership

    async def revoke(
        self,
        *,
        actor_user_id: uuid.UUID,
        membership_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> Membership:
        is_agency_admin = await self._membership_repo.has_role(
            actor_user_id, tenant_id, UserRole.agency_admin
        )
        is_platform_admin = await self._membership_repo.is_platform_admin(actor_user_id)

        if not (is_agency_admin or is_platform_admin):
            raise PermissionDeniedError("Only agency_admin or platform_admin can revoke memberships")

        target = await self._membership_repo.get_active_membership(membership_id, tenant_id=tenant_id)
        if target is None:
            raise PermissionDeniedError(f"Membership {membership_id} not found in tenant")

        if target.user_id == actor_user_id:
            raise PermissionDeniedError("Cannot revoke your own membership")

        if target.role in (UserRole.agency_admin, UserRole.business_owner):
            admin_count = await self._membership_repo.count_active_admins(tenant_id)
            if admin_count <= 1:
                raise PermissionDeniedError("Cannot remove the last admin from the tenant")

        membership = await self._membership_repo.revoke(membership_id, tenant_id=tenant_id)

        await self._audit_repo.log(
            actor_user_id=actor_user_id,
            action="membership.revoke",
            tenant_id=tenant_id,
            target_type="Membership",
            target_id=membership_id,
        )
        self._pending_events.append(
            MembershipRevoked(
                membership_id=membership.id,
                user_id=membership.user_id,
                tenant_id=tenant_id,
            )
        )
        return membership

    async def list_tenant_members(self, tenant_id: uuid.UUID) -> Sequence[Membership]:
        return await self._membership_repo.get_active_for_tenant(tenant_id)
