"""SQLAlchemy ORM models for the Reporting module.

Tables: reports, share_links
FreeAuditToken is owned by business_profile.models (Phase 1).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Enums ──────────────────────────────────────────────────────────────────────


class ReportStatus(str, enum.Enum):
    generating = "generating"
    ready = "ready"
    failed = "failed"


class QuickWinActionType(str, enum.Enum):
    add_alias = "add_alias"
    add_keyword = "add_keyword"
    update_gbp_description = "update_gbp_description"
    add_location_detail = "add_location_detail"
    generate_faq_content = "generate_faq_content"
    seed_directory = "seed_directory"
    clarify_service_offering = "clarify_service_offering"


class EffortEstimate(str, enum.Enum):
    quick = "quick"
    medium = "medium"
    longer = "longer"


# ── Models ────────────────────────────────────────────────────────────────────


class Report(Base):
    """Immutable audit report snapshot. status='ready' means content is final."""

    __tablename__ = "reports"
    __table_args__ = (
        Index("ix_reports_business_created", "business_id", "created_at"),
        Index("ix_reports_audit_run", "audit_run_id"),
        Index("ix_reports_web_view_token", "web_view_token", unique=True),
        Index("ix_reports_generating", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    business_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    audit_run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("audit_runs.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[ReportStatus] = mapped_column(
        Enum(ReportStatus, name="report_status"), nullable=False, default=ReportStatus.generating
    )
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    confidence_band: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    completeness_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pdf_gcs_uri: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pdf_byte_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pdf_checksum: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    web_view_token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    quick_wins: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    template_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")
    generated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        kwargs.setdefault("version", 1)
        kwargs.setdefault("status", ReportStatus.generating)
        kwargs.setdefault("template_version", "v1")
        kwargs.setdefault("created_at", _utcnow())
        super().__init__(**kwargs)


class ShareLink(Base):
    """Expirable, revocable share link for a Report."""

    __tablename__ = "share_links"
    __table_args__ = (
        Index("ix_share_links_token", "token", unique=True),
        Index("ix_share_links_report", "report_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    business_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    report_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("reports.id"), nullable=False
    )
    token: Mapped[str] = mapped_column(String(48), nullable=False, unique=True)
    created_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    view_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_viewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        kwargs.setdefault("view_count", 0)
        kwargs.setdefault("created_at", _utcnow())
        super().__init__(**kwargs)
