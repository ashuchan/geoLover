"""SQLAlchemy ORM models for Identity & Tenancy module."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

import enum


# ── Enums ──────────────────────────────────────────────────────────────────────


class TenantType(str, enum.Enum):
    agency = "agency"
    direct_business = "direct_business"
    trial = "trial"


class UserRole(str, enum.Enum):
    platform_admin = "platform_admin"
    agency_admin = "agency_admin"
    agency_member = "agency_member"
    business_owner = "business_owner"
    business_member = "business_member"


# ── Models ────────────────────────────────────────────────────────────────────


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Tenant(Base):
    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint("length(slug) BETWEEN 3 AND 40", name="ck_tenants_slug_len"),
        CheckConstraint("slug ~ '^[a-z0-9-]+$'", name="ck_tenants_slug_format"),
        Index("ix_tenants_type", "type", postgresql_where="deleted_at IS NULL"),
        Index("ix_tenants_slug_active", "slug", postgresql_where="deleted_at IS NULL"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    type: Mapped[TenantType] = mapped_column(
        Enum(TenantType, name="tenant_type"), nullable=False
    )
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    primary_country: Mapped[str] = mapped_column(String(2), nullable=False, default="IN")
    claimed_from_trial_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    memberships: Mapped[list[Membership]] = relationship(
        "Membership", back_populates="tenant", lazy="noload"
    )
    businesses: Mapped[list] = relationship(
        "Business", back_populates="tenant", lazy="noload"
    )

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        kwargs.setdefault("primary_country", "IN")
        kwargs.setdefault("created_at", _utcnow())
        kwargs.setdefault("updated_at", _utcnow())
        super().__init__(**kwargs)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    auth_provider_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    email_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    email_normalized: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    phone_encrypted: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    locale: Mapped[str] = mapped_column(String(10), nullable=False, default="en-IN")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    memberships: Mapped[list[Membership]] = relationship(
        "Membership",
        foreign_keys="Membership.user_id",
        back_populates="user",
        lazy="noload",
    )

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        kwargs.setdefault("locale", "en-IN")
        kwargs.setdefault("created_at", _utcnow())
        kwargs.setdefault("updated_at", _utcnow())
        super().__init__(**kwargs)


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        CheckConstraint(
            "(role = 'platform_admin' AND tenant_id IS NULL) "
            "OR (role <> 'platform_admin' AND tenant_id IS NOT NULL)",
            name="ck_memberships_admin_tenant",
        ),
        Index(
            "ix_memberships_unique_active",
            "user_id",
            "tenant_id",
            "role",
            unique=True,
            postgresql_where="revoked_at IS NULL",
        ),
        Index("ix_memberships_user", "user_id", postgresql_where="revoked_at IS NULL"),
        Index("ix_memberships_tenant", "tenant_id", postgresql_where="revoked_at IS NULL"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    tenant_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True
    )
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role"), nullable=False
    )
    # UUID[] stored as ARRAY; native PostgreSQL only
    business_scope_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=False, default=list
    )
    granted_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped[User] = relationship(
        "User", foreign_keys=[user_id], back_populates="memberships", lazy="noload"
    )
    tenant: Mapped[Optional[Tenant]] = relationship(
        "Tenant", back_populates="memberships", lazy="noload"
    )

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        kwargs.setdefault("business_scope_ids", [])
        kwargs.setdefault("granted_at", _utcnow())
        super().__init__(**kwargs)


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_log"
    __table_args__ = (
        Index("ix_audit_log_actor", "actor_user_id", "created_at"),
        Index("ix_audit_log_tenant", "tenant_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    tenant_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    action: Mapped[str] = mapped_column(Text, nullable=False)
    target_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    target_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    details: Mapped[Optional[dict]] = mapped_column(sa.JSON, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        kwargs.setdefault("created_at", _utcnow())
        super().__init__(**kwargs)


class ReservedSlug(Base):
    """Platform-level reserved slugs that cannot be used by tenants."""

    __tablename__ = "reserved_slugs"

    slug: Mapped[str] = mapped_column(String(40), primary_key=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("created_at", _utcnow())
        super().__init__(**kwargs)
