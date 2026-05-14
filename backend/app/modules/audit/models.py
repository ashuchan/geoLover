"""SQLAlchemy ORM models for the Audit module.

Tables: query_template_sets, query_templates, engine_descriptors,
        audit_runs, query_executions, citations, competitor_observations.

query_template_sets, query_templates, engine_descriptors have no RLS
(global reference data).  The remaining tables have RLS policies applied
in 002_phase2_audit.py.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Enums ──────────────────────────────────────────────────────────────────────


class EngineHealth(str, enum.Enum):
    healthy = "healthy"
    degraded = "degraded"
    unhealthy = "unhealthy"
    paused = "paused"


class AuditStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    partial = "partial"
    completed = "completed"
    failed = "failed"


class AuditTrigger(str, enum.Enum):
    free_audit = "free_audit"
    initial = "initial"
    weekly = "weekly"
    manual = "manual"
    redetection = "redetection"
    api = "api"


class QueryExecutionStatus(str, enum.Enum):
    pending = "pending"
    in_flight = "in_flight"
    succeeded = "succeeded"
    failed = "failed"
    skipped = "skipped"


class CitationMatchType(str, enum.Enum):
    exact_name = "exact_name"
    alias = "alias"
    phone = "phone"
    website = "website"
    address = "address"
    fuzzy_name = "fuzzy_name"
    composite = "composite"


class CitationPolarity(str, enum.Enum):
    positive = "positive"
    neutral = "neutral"
    negative = "negative"


# ── Models ────────────────────────────────────────────────────────────────────


class QueryTemplateSet(Base):
    """A named collection of query templates (global reference data, no RLS)."""

    __tablename__ = "query_template_sets"
    __table_args__ = (
        Index("ix_query_template_sets_slug", "slug", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    locale: Mapped[str] = mapped_column(String(10), nullable=False, default="en-IN")
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    templates: Mapped[list[QueryTemplate]] = relationship(
        "QueryTemplate",
        back_populates="template_set",
        lazy="noload",
        cascade="all, delete-orphan",
    )

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        kwargs.setdefault("locale", "en-IN")
        kwargs.setdefault("is_default", False)
        kwargs.setdefault("created_at", _utcnow())
        super().__init__(**kwargs)


class QueryTemplate(Base):
    """A single query template with variable placeholders (global, no RLS)."""

    __tablename__ = "query_templates"
    __table_args__ = (
        Index("ix_query_templates_set", "template_set_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    template_set_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("query_template_sets.id", ondelete="CASCADE"),
        nullable=False,
    )
    template_text: Mapped[str] = mapped_column(Text, nullable=False)
    # Variables like {business_name}, {city}, {category}
    required_variables: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    template_set: Mapped[QueryTemplateSet] = relationship(
        "QueryTemplateSet", back_populates="templates", lazy="noload"
    )

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        kwargs.setdefault("required_variables", [])
        kwargs.setdefault("priority", 100)
        kwargs.setdefault("created_at", _utcnow())
        super().__init__(**kwargs)


class EngineDescriptor(Base):
    """Metadata for a registered AI engine (global reference data, no RLS)."""

    __tablename__ = "engine_descriptors"
    __table_args__ = (
        Index("ix_engine_descriptors_slug", "slug", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    adapter_class: Mapped[str] = mapped_column(Text, nullable=False)
    supported_locales: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list
    )
    health: Mapped[EngineHealth] = mapped_column(
        Enum(EngineHealth, name="engine_health"),
        nullable=False,
        default=EngineHealth.healthy,
    )
    cost_per_query_usd: Mapped[float] = mapped_column(
        Numeric(10, 6), nullable=False, default=0.0
    )
    config_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        kwargs.setdefault("supported_locales", [])
        kwargs.setdefault("health", EngineHealth.healthy)
        kwargs.setdefault("cost_per_query_usd", 0.0)
        kwargs.setdefault("created_at", _utcnow())
        kwargs.setdefault("updated_at", _utcnow())
        super().__init__(**kwargs)


class AuditRun(Base):
    """A single audit run for a business. RLS-protected by tenant_id."""

    __tablename__ = "audit_runs"
    __table_args__ = (
        Index("ix_audit_runs_business", "business_id"),
        Index("ix_audit_runs_tenant", "tenant_id"),
        Index("ix_audit_runs_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False
    )
    trigger: Mapped[AuditTrigger] = mapped_column(
        Enum(AuditTrigger, name="audit_trigger"), nullable=False
    )
    status: Mapped[AuditStatus] = mapped_column(
        Enum(AuditStatus, name="audit_status"),
        nullable=False,
        default=AuditStatus.pending,
    )
    ai_visibility_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    completeness_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    queries_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    queries_successful: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    queries_cited: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    queries_negative: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    algorithm_version: Mapped[str] = mapped_column(
        String(20), nullable=False, default="v1"
    )
    workflow_run_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    query_executions: Mapped[list[QueryExecution]] = relationship(
        "QueryExecution",
        back_populates="audit_run",
        lazy="noload",
        cascade="all, delete-orphan",
    )

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        kwargs.setdefault("status", AuditStatus.pending)
        kwargs.setdefault("queries_total", 0)
        kwargs.setdefault("queries_successful", 0)
        kwargs.setdefault("queries_cited", 0)
        kwargs.setdefault("queries_negative", 0)
        kwargs.setdefault("algorithm_version", "v1")
        kwargs.setdefault("created_at", _utcnow())
        super().__init__(**kwargs)


class QueryExecution(Base):
    """A single query sent to an AI engine during an audit run. RLS by tenant_id."""

    __tablename__ = "query_executions"
    __table_args__ = (
        Index("ix_query_executions_run", "audit_run_id"),
        Index("ix_query_executions_tenant", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    audit_run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("audit_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False
    )
    engine_descriptor_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("engine_descriptors.id"), nullable=False
    )
    query_template_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[QueryExecutionStatus] = mapped_column(
        Enum(QueryExecutionStatus, name="query_execution_status"),
        nullable=False,
        default=QueryExecutionStatus.pending,
    )
    response_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[Optional[float]] = mapped_column(Numeric(10, 6), nullable=True)
    executed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    audit_run: Mapped[AuditRun] = relationship(
        "AuditRun", back_populates="query_executions", lazy="noload"
    )
    citations: Mapped[list[Citation]] = relationship(
        "Citation",
        back_populates="query_execution",
        lazy="noload",
        cascade="all, delete-orphan",
    )

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        kwargs.setdefault("status", QueryExecutionStatus.pending)
        kwargs.setdefault("created_at", _utcnow())
        super().__init__(**kwargs)


class Citation(Base):
    """A single detected citation of a business in an engine response. RLS by tenant_id."""

    __tablename__ = "citations"
    __table_args__ = (
        Index("ix_citations_execution", "query_execution_id"),
        Index("ix_citations_tenant", "tenant_id"),
        Index("ix_citations_business", "business_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    query_execution_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("query_executions.id", ondelete="CASCADE"),
        nullable=False,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False
    )
    cited: Mapped[bool] = mapped_column(Boolean, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    match_type: Mapped[Optional[CitationMatchType]] = mapped_column(
        Enum(CitationMatchType, name="citation_match_type"), nullable=True
    )
    polarity: Mapped[CitationPolarity] = mapped_column(
        Enum(CitationPolarity, name="citation_polarity"),
        nullable=False,
        default=CitationPolarity.neutral,
    )
    snippet: Mapped[str] = mapped_column(Text, nullable=False, default="")
    snippet_start_pos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    corroborating_signals: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list
    )
    competitors_mentioned: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list
    )
    algorithm_version: Mapped[str] = mapped_column(
        String(20), nullable=False, default="v1"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    query_execution: Mapped[QueryExecution] = relationship(
        "QueryExecution", back_populates="citations", lazy="noload"
    )

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        kwargs.setdefault("polarity", CitationPolarity.neutral)
        kwargs.setdefault("snippet", "")
        kwargs.setdefault("snippet_start_pos", 0)
        kwargs.setdefault("corroborating_signals", [])
        kwargs.setdefault("competitors_mentioned", [])
        kwargs.setdefault("algorithm_version", "v1")
        kwargs.setdefault("created_at", _utcnow())
        super().__init__(**kwargs)


class CompetitorObservation(Base):
    """A competitor observed during an audit run. RLS by tenant_id."""

    __tablename__ = "competitor_observations"
    __table_args__ = (
        Index("ix_competitor_obs_run", "audit_run_id"),
        Index("ix_competitor_obs_tenant", "tenant_id"),
        Index("ix_competitor_obs_business", "business_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    audit_run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("audit_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False
    )
    competitor_name: Mapped[str] = mapped_column(Text, nullable=False)
    competitor_name_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    mention_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_seen_in_execution_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        kwargs.setdefault("mention_count", 1)
        kwargs.setdefault("created_at", _utcnow())
        super().__init__(**kwargs)
