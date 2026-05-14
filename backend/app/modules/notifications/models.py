"""SQLAlchemy ORM models for the Notifications & Recrawl module."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, SmallInteger, Text, UniqueConstraint, Uuid
from sqlalchemy import ARRAY
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Enums ──────────────────────────────────────────────────────────────────────


class CitationDeltaType(str, enum.Enum):
    won = "won"
    lost = "lost"
    improved = "improved"
    declined = "declined"


class NotificationPriority(str, enum.Enum):
    urgent = "urgent"
    standard = "standard"
    digestible = "digestible"


class NotificationStatus(str, enum.Enum):
    queued = "queued"
    sending = "sending"
    delivered = "delivered"
    bounced = "bounced"
    failed = "failed"
    suppressed = "suppressed"


class NotificationCadence(str, enum.Enum):
    immediate = "immediate"
    daily_digest = "daily_digest"
    weekly_digest = "weekly_digest"
    only_when_active = "only_when_active"
    off = "off"


# ── Models ────────────────────────────────────────────────────────────────────


class RecrawlSchedule(Base):
    """Recrawl schedule for a business. Tenant-scoped."""

    __tablename__ = "recrawl_schedules"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    business_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("businesses.id"), unique=True, nullable=False
    )
    cadence: Mapped[str] = mapped_column(Text, nullable=False)
    day_of_week: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    hour_local: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    next_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    algorithm_version_baseline: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        kwargs.setdefault("cadence", "weekly")
        kwargs.setdefault("day_of_week", 0)
        kwargs.setdefault("hour_local", 6)
        kwargs.setdefault("enabled", True)
        now = _utcnow()
        kwargs.setdefault("created_at", now)
        kwargs.setdefault("updated_at", now)
        super().__init__(**kwargs)


class CitationDelta(Base):
    """A detected citation delta (won/lost/improved/declined). Tenant-scoped."""

    __tablename__ = "citation_deltas"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    audit_run_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    prior_audit_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid, nullable=True)
    query_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    engine: Mapped[str] = mapped_column(Text, nullable=False)
    delta_type: Mapped[CitationDeltaType] = mapped_column(Text, nullable=False)
    prior_state: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    current_state: Mapped[dict] = mapped_column(JSONB, nullable=False)
    source_publish_attempt_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        kwargs.setdefault("created_at", _utcnow())
        super().__init__(**kwargs)


class NotificationTemplate(Base):
    """Platform-wide notification template. No RLS."""

    __tablename__ = "notification_templates"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    template_key: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    locale: Mapped[str] = mapped_column(Text, nullable=False)
    subject_template: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    body_template: Mapped[str] = mapped_column(Text, nullable=False)
    variables_schema: Mapped[dict] = mapped_column(JSONB, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        kwargs.setdefault("locale", "en-IN")
        kwargs.setdefault("variables_schema", {})
        kwargs.setdefault("active", False)
        kwargs.setdefault("created_at", _utcnow())
        super().__init__(**kwargs)


class Notification(Base):
    """A notification record. Tenant-scoped."""

    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_notifications_idempotency_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    recipient_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=False
    )
    business_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid, nullable=True)
    notification_type: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[NotificationPriority] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    template_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("notification_templates.id"), nullable=True
    )
    render_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[NotificationStatus] = mapped_column(Text, nullable=False)
    send_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    bounced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    suppression_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        kwargs.setdefault("priority", NotificationPriority.standard)
        kwargs.setdefault("render_payload", {})
        kwargs.setdefault("status", NotificationStatus.queued)
        kwargs.setdefault("send_attempts", 0)
        kwargs.setdefault("created_at", _utcnow())
        super().__init__(**kwargs)


class NotificationPreference(Base):
    """User notification preferences per type. Tenant-scoped."""

    __tablename__ = "notification_preferences"
    __table_args__ = (
        UniqueConstraint("user_id", "tenant_id", "notification_type", name="uq_notif_pref_user_tenant_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=False
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    notification_type: Mapped[str] = mapped_column(Text, nullable=False)
    channels_enabled: Mapped[list] = mapped_column(ARRAY(Text), default=list, nullable=False)
    cadence: Mapped[NotificationCadence] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        kwargs.setdefault("channels_enabled", [])
        kwargs.setdefault("cadence", NotificationCadence.immediate)
        kwargs.setdefault("updated_at", _utcnow())
        super().__init__(**kwargs)


class OutboundDeliveryLog(Base):
    """Delivery event log per notification. No RLS (audit log)."""

    __tablename__ = "outbound_delivery_log"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    notification_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("notifications.id"), nullable=False
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    provider_message_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    event: Mapped[str] = mapped_column(Text, nullable=False)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_details: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        kwargs.setdefault("created_at", _utcnow())
        super().__init__(**kwargs)


class BouncedAddress(Base):
    """Registry of bounced email addresses. No RLS."""

    __tablename__ = "bounced_addresses"

    email_normalized: Mapped[str] = mapped_column(Text, primary_key=True)
    bounce_type: Mapped[str] = mapped_column(Text, nullable=False)
    bounced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cleared_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("bounced_at", datetime.now(timezone.utc))
        super().__init__(**kwargs)
