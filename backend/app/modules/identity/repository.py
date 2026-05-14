"""Repository layer for Identity & Tenancy module.

Each repository takes an AsyncSession and performs typed DB operations.
Callers are responsible for providing a session with RLS variables already set
(via app.core.database.get_db_session).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ConflictError,
    NotFoundError,
    TenantNotFoundError,
)
from app.modules.identity.models import (
    AdminAuditLog,
    Membership,
    ReservedSlug,
    Tenant,
    TenantType,
    User,
    UserRole,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── TenantRepository ──────────────────────────────────────────────────────────


class TenantRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, tenant_id: uuid.UUID) -> Tenant:
        result = await self._session.execute(
            select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted_at.is_(None))
        )
        tenant = result.scalar_one_or_none()
        if tenant is None:
            raise TenantNotFoundError(f"Tenant {tenant_id} not found")
        return tenant

    async def get_by_slug(self, slug: str) -> Tenant:
        result = await self._session.execute(
            select(Tenant).where(Tenant.slug == slug, Tenant.deleted_at.is_(None))
        )
        tenant = result.scalar_one_or_none()
        if tenant is None:
            raise TenantNotFoundError(f"Tenant with slug '{slug}' not found")
        return tenant

    async def slug_exists(self, slug: str) -> bool:
        result = await self._session.execute(
            select(Tenant.id).where(Tenant.slug == slug)
        )
        return result.scalar_one_or_none() is not None

    async def is_slug_reserved(self, slug: str) -> bool:
        result = await self._session.execute(
            select(ReservedSlug.slug).where(ReservedSlug.slug == slug)
        )
        return result.scalar_one_or_none() is not None

    async def create(
        self,
        *,
        type: TenantType,
        display_name: str,
        slug: str,
        primary_country: str = "IN",
        claimed_from_trial_id: Optional[uuid.UUID] = None,
    ) -> Tenant:
        if await self.is_slug_reserved(slug):
            raise ConflictError(f"Slug '{slug}' is reserved and cannot be used")
        if await self.slug_exists(slug):
            raise ConflictError(f"Slug '{slug}' is already taken")

        tenant = Tenant(
            type=type,
            display_name=display_name,
            slug=slug,
            primary_country=primary_country,
            claimed_from_trial_id=claimed_from_trial_id,
        )
        self._session.add(tenant)
        await self._session.flush()
        return tenant

    async def update(
        self,
        tenant_id: uuid.UUID,
        *,
        display_name: Optional[str] = None,
        primary_country: Optional[str] = None,
    ) -> Tenant:
        tenant = await self.get_by_id(tenant_id)
        if display_name is not None:
            tenant.display_name = display_name
        if primary_country is not None:
            tenant.primary_country = primary_country
        tenant.updated_at = _utcnow()
        await self._session.flush()
        return tenant

    async def soft_delete(self, tenant_id: uuid.UUID) -> Tenant:
        tenant = await self.get_by_id(tenant_id)
        tenant.deleted_at = _utcnow()
        await self._session.flush()
        return tenant


# ── UserRepository ────────────────────────────────────────────────────────────


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: uuid.UUID) -> User:
        result = await self._session.execute(
            select(User).where(User.id == user_id, User.deleted_at.is_(None))
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise NotFoundError(f"User {user_id} not found")
        return user

    async def get_by_auth_provider_id(self, auth_provider_id: str) -> Optional[User]:
        result = await self._session.execute(
            select(User).where(
                User.auth_provider_id == auth_provider_id,
                User.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_email_normalized(self, email_normalized: str) -> Optional[User]:
        result = await self._session.execute(
            select(User).where(
                User.email_normalized == email_normalized,
                User.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        auth_provider_id: str,
        email_encrypted: bytes,
        email_normalized: str,
        display_name: str,
        phone_encrypted: Optional[bytes] = None,
        locale: str = "en-IN",
    ) -> User:
        existing = await self.get_by_email_normalized(email_normalized)
        if existing:
            raise ConflictError(f"User with email already exists")

        user = User(
            auth_provider_id=auth_provider_id,
            email_encrypted=email_encrypted,
            email_normalized=email_normalized,
            display_name=display_name,
            phone_encrypted=phone_encrypted,
            locale=locale,
        )
        self._session.add(user)
        await self._session.flush()
        return user

    async def update_last_login(self, user_id: uuid.UUID) -> None:
        await self._session.execute(
            update(User)
            .where(User.id == user_id)
            .values(last_login_at=_utcnow(), updated_at=_utcnow())
        )

    async def update_email(
        self,
        user_id: uuid.UUID,
        *,
        email_encrypted: bytes,
        email_normalized: str,
    ) -> User:
        user = await self.get_by_id(user_id)
        user.email_encrypted = email_encrypted
        user.email_normalized = email_normalized
        user.updated_at = _utcnow()
        await self._session.flush()
        return user

    async def soft_delete(self, user_id: uuid.UUID) -> User:
        user = await self.get_by_id(user_id)
        user.deleted_at = _utcnow()
        await self._session.flush()
        return user


# ── MembershipRepository ──────────────────────────────────────────────────────


class MembershipRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_active(
        self, user_id: uuid.UUID, tenant_id: uuid.UUID, role: UserRole
    ) -> Optional[Membership]:
        result = await self._session.execute(
            select(Membership).where(
                Membership.user_id == user_id,
                Membership.tenant_id == tenant_id,
                Membership.role == role,
                Membership.revoked_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_active_for_user(self, user_id: uuid.UUID) -> Sequence[Membership]:
        result = await self._session.execute(
            select(Membership).where(
                Membership.user_id == user_id,
                Membership.revoked_at.is_(None),
            )
        )
        return result.scalars().all()

    async def get_active_for_tenant(self, tenant_id: uuid.UUID) -> Sequence[Membership]:
        result = await self._session.execute(
            select(Membership).where(
                Membership.tenant_id == tenant_id,
                Membership.revoked_at.is_(None),
            )
        )
        return result.scalars().all()

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        tenant_id: Optional[uuid.UUID],
        role: UserRole,
        granted_by_user_id: Optional[uuid.UUID] = None,
        business_scope_ids: Optional[list[uuid.UUID]] = None,
    ) -> Membership:
        if tenant_id:
            existing = await self.get_active(user_id, tenant_id, role)
        else:
            # platform_admin has no tenant; check for global duplicate
            result = await self._session.execute(
                select(Membership).where(
                    Membership.user_id == user_id,
                    Membership.tenant_id.is_(None),
                    Membership.role == role,
                    Membership.revoked_at.is_(None),
                )
            )
            existing = result.scalar_one_or_none()
        if existing:
            raise ConflictError(
                f"User {user_id} already has role {role} in tenant {tenant_id}"
            )

        membership = Membership(
            user_id=user_id,
            tenant_id=tenant_id,
            role=role,
            granted_by_user_id=granted_by_user_id,
            business_scope_ids=business_scope_ids or [],
        )
        self._session.add(membership)
        await self._session.flush()
        return membership

    async def revoke(self, membership_id: uuid.UUID, *, tenant_id: uuid.UUID) -> Membership:
        result = await self._session.execute(
            select(Membership).where(
                Membership.id == membership_id,
                Membership.tenant_id == tenant_id,
                Membership.revoked_at.is_(None),
            )
        )
        membership = result.scalar_one_or_none()
        if membership is None:
            raise NotFoundError(f"Active membership {membership_id} not found in tenant {tenant_id}")
        membership.revoked_at = _utcnow()
        await self._session.flush()
        return membership

    async def get_active_membership(
        self, membership_id: uuid.UUID, *, tenant_id: uuid.UUID
    ) -> Optional["Membership"]:
        result = await self._session.execute(
            select(Membership).where(
                Membership.id == membership_id,
                Membership.tenant_id == tenant_id,
                Membership.revoked_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def count_active_admins(self, tenant_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(func.count()).where(
                Membership.tenant_id == tenant_id,
                Membership.role.in_([UserRole.agency_admin, UserRole.business_owner]),
                Membership.revoked_at.is_(None),
            )
        )
        return result.scalar_one()

    async def has_role(
        self, user_id: uuid.UUID, tenant_id: uuid.UUID, *roles: UserRole
    ) -> bool:
        result = await self._session.execute(
            select(Membership.id).where(
                Membership.user_id == user_id,
                Membership.tenant_id == tenant_id,
                Membership.role.in_(roles),
                Membership.revoked_at.is_(None),
            )
        )
        return result.scalar_one_or_none() is not None

    async def is_platform_admin(self, user_id: uuid.UUID) -> bool:
        result = await self._session.execute(
            select(Membership.id).where(
                Membership.user_id == user_id,
                Membership.role == UserRole.platform_admin,
                Membership.revoked_at.is_(None),
            )
        )
        return result.scalar_one_or_none() is not None

    async def has_business_scope_access(
        self, user_id: uuid.UUID, tenant_id: uuid.UUID, business_id: uuid.UUID
    ) -> bool:
        """Return True if user has an active scoped membership covering this business."""
        from sqlalchemy.dialects.postgresql import array as pg_array
        from sqlalchemy.dialects.postgresql import UUID as PGUUID
        result = await self._session.execute(
            select(Membership.id).where(
                Membership.user_id == user_id,
                Membership.tenant_id == tenant_id,
                Membership.revoked_at.is_(None),
                Membership.role.in_([UserRole.business_member, UserRole.business_owner]),
                Membership.business_scope_ids.contains(
                    pg_array([business_id], type_=PGUUID(as_uuid=True))
                ),
            ).limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def count_tenants_for_user(self, user_id: uuid.UUID) -> int:
        """Count distinct non-revoked tenant memberships for a user."""
        result = await self._session.execute(
            select(func.count(func.distinct(Membership.tenant_id))).where(
                Membership.user_id == user_id,
                Membership.tenant_id.is_not(None),
                Membership.revoked_at.is_(None),
            )
        )
        return result.scalar_one() or 0


# ── AuditLogRepository ────────────────────────────────────────────────────────


class AuditLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def log(
        self,
        *,
        actor_user_id: uuid.UUID,
        action: str,
        tenant_id: Optional[uuid.UUID] = None,
        target_type: Optional[str] = None,
        target_id: Optional[uuid.UUID] = None,
        details: Optional[dict] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> AdminAuditLog:
        entry = AdminAuditLog(
            actor_user_id=actor_user_id,
            tenant_id=tenant_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=details,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self._session.add(entry)
        await self._session.flush()
        return entry
