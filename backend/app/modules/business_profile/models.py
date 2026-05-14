"""SQLAlchemy ORM models for Business Profile module.

All tables here (except businesses itself) have RLS enabled via migration.
The `tenant_id` column is denormalised on every child table so RLS policies
can filter without joining to the parent.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    LargeBinary,
    Numeric,
    String,
    Text,
    Integer,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Enums ──────────────────────────────────────────────────────────────────────


class BusinessStatus(str, enum.Enum):
    trial = "trial"
    active = "active"
    suspended = "suspended"
    deleted = "deleted"


class BusinessSource(str, enum.Enum):
    self_signup = "self_signup"
    agency_created = "agency_created"
    free_audit = "free_audit"


class AliasType(str, enum.Enum):
    former_name = "former_name"
    translit_hindi = "translit_hindi"
    translit_kannada = "translit_kannada"
    abbreviation = "abbreviation"
    colloquial = "colloquial"
    auto_generated = "auto_generated"


class KeywordSource(str, enum.Enum):
    user = "user"
    category_suggested = "category_suggested"
    audit_discovered = "audit_discovered"


class CompetitorSource(str, enum.Enum):
    user = "user"
    audit_discovered = "audit_discovered"


class CompetitorStatus(str, enum.Enum):
    tracked = "tracked"
    dismissed = "dismissed"


# ── Models ────────────────────────────────────────────────────────────────────


class Business(Base):
    __tablename__ = "businesses"
    __table_args__ = (
        CheckConstraint(
            "length(canonical_name) BETWEEN 2 AND 200",
            name="ck_businesses_name_len",
        ),
        Index("ix_businesses_tenant", "tenant_id", postgresql_where="deleted_at IS NULL"),
        Index(
            "ix_businesses_tenant_status",
            "tenant_id",
            "status",
            postgresql_where="deleted_at IS NULL",
        ),
        Index("ix_businesses_name_normalized", "name_normalized"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    canonical_name: Mapped[str] = mapped_column(Text, nullable=False)
    name_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    category_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("categories.id"), nullable=False
    )
    subcategory_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=False, default=list
    )
    primary_location_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    website_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    primary_email_encrypted: Mapped[Optional[bytes]] = mapped_column(
        LargeBinary, nullable=True
    )
    primary_phone_encrypted: Mapped[Optional[bytes]] = mapped_column(
        LargeBinary, nullable=True
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    locale: Mapped[str] = mapped_column(String(10), nullable=False, default="en-IN")
    status: Mapped[BusinessStatus] = mapped_column(
        Enum(BusinessStatus, name="business_status"),
        nullable=False,
        default=BusinessStatus.trial,
    )
    source: Mapped[BusinessSource] = mapped_column(
        Enum(BusinessSource, name="business_source"), nullable=False
    )
    identity_uniqueness_score: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
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

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        kwargs.setdefault("status", BusinessStatus.trial)
        kwargs.setdefault("locale", "en-IN")
        kwargs.setdefault("subcategory_ids", [])
        kwargs.setdefault("created_at", _utcnow())
        kwargs.setdefault("updated_at", _utcnow())
        super().__init__(**kwargs)

    tenant: Mapped[Optional[object]] = relationship("Tenant", back_populates="businesses", lazy="noload")
    category: Mapped[Optional[object]] = relationship("Category", lazy="noload")
    aliases: Mapped[list[BusinessAlias]] = relationship(
        "BusinessAlias", back_populates="business", lazy="noload", cascade="all, delete-orphan"
    )
    locations: Mapped[list[BusinessLocation]] = relationship(
        "BusinessLocation", back_populates="business", lazy="noload", cascade="all, delete-orphan",
        foreign_keys="BusinessLocation.business_id",
    )
    keywords: Mapped[list[BusinessKeyword]] = relationship(
        "BusinessKeyword", back_populates="business", lazy="noload", cascade="all, delete-orphan"
    )
    competitors: Mapped[list[BusinessCompetitor]] = relationship(
        "BusinessCompetitor", back_populates="business", lazy="noload", cascade="all, delete-orphan"
    )


class BusinessAlias(Base):
    __tablename__ = "business_aliases"
    __table_args__ = (
        Index("ix_business_aliases_business", "business_id"),
        Index("ix_business_aliases_normalized", "alias_text_normalized"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False
    )
    alias_text: Mapped[str] = mapped_column(Text, nullable=False)
    alias_text_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    alias_type: Mapped[AliasType] = mapped_column(
        Enum(AliasType, name="alias_type"), nullable=False
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    business: Mapped[Business] = relationship(
        "Business", back_populates="aliases", lazy="noload"
    )

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        kwargs.setdefault("confidence", 1.0)
        kwargs.setdefault("created_at", _utcnow())
        super().__init__(**kwargs)


class BusinessLocation(Base):
    __tablename__ = "business_locations"
    __table_args__ = (
        Index(
            "ix_business_locations_one_primary",
            "business_id",
            unique=True,
            postgresql_where="is_primary = true",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False
    )
    label: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    city: Mapped[str] = mapped_column(Text, nullable=False)
    locality: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    address_line_1: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    address_line_2: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    postal_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    state: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    country: Mapped[str] = mapped_column(String(2), nullable=False, default="IN")
    geo_lat: Mapped[Optional[float]] = mapped_column(Numeric(9, 6), nullable=True)
    geo_lng: Mapped[Optional[float]] = mapped_column(Numeric(9, 6), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    business: Mapped[Business] = relationship(
        "Business",
        back_populates="locations",
        lazy="noload",
        foreign_keys=[business_id],
    )

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        kwargs.setdefault("country", "IN")
        kwargs.setdefault("is_primary", False)
        kwargs.setdefault("created_at", _utcnow())
        super().__init__(**kwargs)


class BusinessKeyword(Base):
    __tablename__ = "business_keywords"
    __table_args__ = (
        Index("ix_business_keywords_business", "business_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False
    )
    keyword: Mapped[str] = mapped_column(Text, nullable=False)
    keyword_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[KeywordSource] = mapped_column(
        Enum(KeywordSource, name="keyword_source"), nullable=False, default=KeywordSource.user
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    business: Mapped[Business] = relationship(
        "Business", back_populates="keywords", lazy="noload"
    )

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        kwargs.setdefault("source", KeywordSource.user)
        kwargs.setdefault("priority", 100)
        kwargs.setdefault("created_at", _utcnow())
        super().__init__(**kwargs)


class BusinessCompetitor(Base):
    __tablename__ = "business_competitors"
    __table_args__ = (
        Index("ix_business_competitors_business", "business_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False
    )
    competitor_name: Mapped[str] = mapped_column(Text, nullable=False)
    competitor_name_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[CompetitorSource] = mapped_column(
        Enum(CompetitorSource, name="competitor_source"), nullable=False
    )
    discovered_in_audit_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    status: Mapped[CompetitorStatus] = mapped_column(
        Enum(CompetitorStatus, name="competitor_status"),
        nullable=False,
        default=CompetitorStatus.tracked,
    )

    business: Mapped[Business] = relationship(
        "Business", back_populates="competitors", lazy="noload"
    )

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        kwargs.setdefault("status", CompetitorStatus.tracked)
        kwargs.setdefault("first_seen_at", _utcnow())
        kwargs.setdefault("last_seen_at", _utcnow())
        super().__init__(**kwargs)


class FreeAuditToken(Base):
    """Public-facing token for the free-audit flow. No RLS — uses public_audit_role."""

    __tablename__ = "free_audit_tokens"
    __table_args__ = (
        Index("ix_free_audit_tokens_token", "token", unique=True),
        Index("ix_free_audit_tokens_business", "business_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    business_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    claimed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        kwargs.setdefault("created_at", _utcnow())
        super().__init__(**kwargs)
