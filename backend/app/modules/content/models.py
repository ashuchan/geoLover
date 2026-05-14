"""SQLAlchemy ORM models for the Content module.

Tables: prompt_versions, content_briefs, content_assets, llm_calls, usage_counters
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Enums ──────────────────────────────────────────────────────────────────────


class BriefType(str, enum.Enum):
    direct_answer_page = "direct_answer_page"
    faq_cluster = "faq_cluster"
    comparison_page = "comparison_page"
    entity_summary = "entity_summary"


class BriefState(str, enum.Enum):
    draft = "draft"
    in_review = "in_review"
    approved = "approved"
    rejected = "rejected"
    superseded = "superseded"
    published = "published"


class ApprovalFlow(str, enum.Enum):
    agency_only = "agency_only"
    business_only = "business_only"
    agency_then_business = "agency_then_business"


class LLMPurpose(str, enum.Enum):
    content_brief_gen = "content_brief_gen"
    audit_quick_wins = "audit_quick_wins"
    pii_redaction = "pii_redaction"
    translation = "translation"
    eval = "eval"
    other = "other"


# ── Models ────────────────────────────────────────────────────────────────────


class PromptVersion(Base):
    """Platform-wide prompt templates (no RLS)."""

    __tablename__ = "prompt_versions"
    __table_args__ = (
        Index("ix_prompt_versions_key_locale_cohort", "prompt_key", "locale", "experiment_cohort"),
        Index("ix_prompt_versions_active", "prompt_key", "active_flag"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    prompt_key: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    system_text: Mapped[str] = mapped_column(Text, nullable=False)
    user_template: Mapped[str] = mapped_column(Text, nullable=False)
    parameters_schema: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    output_schema: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    recommended_model: Mapped[str] = mapped_column(Text, nullable=False)
    temperature: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False, default=Decimal("0.0"))
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    locale: Mapped[str] = mapped_column(Text, nullable=False, default="en-IN")
    active_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    experiment_cohort: Mapped[str] = mapped_column(Text, nullable=False, default="control")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    retired_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        kwargs.setdefault("temperature", Decimal("0.0"))
        kwargs.setdefault("locale", "en-IN")
        kwargs.setdefault("active_flag", False)
        kwargs.setdefault("experiment_cohort", "control")
        kwargs.setdefault("created_at", _utcnow())
        super().__init__(**kwargs)


class ContentBrief(Base):
    """A brief describing content to generate. Tenant-scoped with RLS."""

    __tablename__ = "content_briefs"
    __table_args__ = (
        Index("ix_content_briefs_tenant_business", "tenant_id", "business_id"),
        Index("ix_content_briefs_state", "current_state"),
        Index("ix_content_briefs_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    business_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False
    )
    source_audit_run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("audit_runs.id"), nullable=False
    )
    source_lost_query_ids: Mapped[Optional[list]] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=True
    )
    brief_type: Mapped[BriefType] = mapped_column(
        Enum(BriefType, name="brief_type"), nullable=False
    )
    target_query: Mapped[str] = mapped_column(Text, nullable=False)
    current_state: Mapped[BriefState] = mapped_column(
        Enum(BriefState, name="brief_state"), nullable=False, default=BriefState.draft
    )
    current_asset_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    reviewer_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    approval_flow: Mapped[ApprovalFlow] = mapped_column(
        Enum(ApprovalFlow, name="approval_flow_type"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        kwargs.setdefault("current_state", BriefState.draft)
        now = _utcnow()
        kwargs.setdefault("created_at", now)
        kwargs.setdefault("updated_at", now)
        super().__init__(**kwargs)


class ContentAsset(Base):
    """A versioned content asset for a ContentBrief. Tenant-scoped with RLS."""

    __tablename__ = "content_assets"
    __table_args__ = (
        UniqueConstraint("brief_id", "version", name="uq_content_assets_brief_version"),
        Index("ix_content_assets_brief_version", "brief_id", "version"),
        Index("ix_content_assets_tenant_business", "tenant_id", "business_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    business_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    brief_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("content_briefs.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    markdown: Mapped[str] = mapped_column(Text, nullable=False)
    html: Mapped[str] = mapped_column(Text, nullable=False)
    schema_jsonld: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    prompt_version_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("prompt_versions.id"), nullable=False
    )
    llm_call_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    validation_status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    validation_findings: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    reviewer_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        kwargs.setdefault("validation_status", "pending")
        kwargs.setdefault("created_at", _utcnow())
        super().__init__(**kwargs)


class LLMCall(Base):
    """Audit log of every LLM call made by the gateway. Tenant-scoped with RLS."""

    __tablename__ = "llm_calls"
    __table_args__ = (
        Index("ix_llm_calls_tenant_business", "tenant_id", "business_id"),
        Index("ix_llm_calls_created_at", "created_at"),
        Index("ix_llm_calls_purpose", "purpose"),
        Index("ix_llm_calls_cache_key", "cache_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    business_id: Mapped[Optional[uuid.UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    purpose: Mapped[LLMPurpose] = mapped_column(
        Enum(LLMPurpose, name="llm_purpose"), nullable=False
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_key: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("prompt_versions.id"), nullable=True
    )
    input_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cost_inr: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False, default=Decimal("0"))
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    cache_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    workflow_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_class: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        kwargs.setdefault("cost_inr", Decimal("0"))
        kwargs.setdefault("created_at", _utcnow())
        super().__init__(**kwargs)


class UsageCounter(Base):
    """Monthly usage aggregation per business. Tenant-scoped with RLS."""

    __tablename__ = "usage_counters"
    __table_args__ = (
        Index("ix_usage_counters_tenant", "tenant_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, nullable=False
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, nullable=False
    )
    period: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)
    llm_calls_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    llm_cost_inr: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=Decimal("0"))
    content_briefs_generated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("llm_calls_count", 0)
        kwargs.setdefault("llm_cost_inr", Decimal("0"))
        kwargs.setdefault("content_briefs_generated", 0)
        kwargs.setdefault("updated_at", _utcnow())
        super().__init__(**kwargs)
