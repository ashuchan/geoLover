"""SQLAlchemy ORM models for the Ops/Admin module (Phase 8)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Numeric, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class QuotaEnforcementLog(Base):
    """Audit log for quota enforcement actions. Platform admin — no RLS."""

    __tablename__ = "quota_enforcement_log"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    business_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid, nullable=True)
    quota_kind: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    threshold_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric, nullable=True)
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    detail: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        kwargs.setdefault("triggered_at", _utcnow())
        super().__init__(**kwargs)


class TenantGraceExtension(Base):
    """Grace period extension for a tenant quota. Platform admin."""

    __tablename__ = "tenant_grace_extensions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    quota_kind: Mapped[str] = mapped_column(Text, nullable=False)
    extended_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    extended_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=False
    )
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        kwargs.setdefault("created_at", _utcnow())
        super().__init__(**kwargs)


class ImpersonationLog(Base):
    """Audit log for admin impersonation sessions. Platform admin — no RLS."""

    __tablename__ = "impersonation_log"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    admin_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=False
    )
    impersonated_tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    impersonated_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        kwargs.setdefault("started_at", _utcnow())
        super().__init__(**kwargs)


class StatusComponent(Base):
    """Platform-wide status page component. No RLS."""

    __tablename__ = "status_components"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    health_signal_query: Mapped[str] = mapped_column(Text, nullable=False)
    last_known_state: Mapped[str] = mapped_column(Text, nullable=False)
    last_evaluated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        kwargs.setdefault("last_known_state", "operational")
        super().__init__(**kwargs)
