"""SQLAlchemy ORM models for the Publishing & Entity Seeding module."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, LargeBinary, Text, UniqueConstraint
from sqlalchemy import Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Enums ──────────────────────────────────────────────────────────────────────


class PublishChannel(str, enum.Enum):
    google_business_profile = "google_business_profile"
    wordpress = "wordpress"
    website_snippet = "website_snippet"
    justdial = "justdial"
    indiamart = "indiamart"
    sulekha = "sulekha"


class PublishTargetStatus(str, enum.Enum):
    pending_oauth = "pending_oauth"
    connected = "connected"
    failed = "failed"
    revoked = "revoked"
    disabled = "disabled"


class PublishAttemptStatus(str, enum.Enum):
    queued = "queued"
    in_progress = "in_progress"
    succeeded = "succeeded"
    failed_retryable = "failed_retryable"
    failed_terminal = "failed_terminal"
    verified = "verified"
    verification_failed = "verification_failed"
    awaiting_customer_publish = "awaiting_customer_publish"


class EntitySeedStatus(str, enum.Enum):
    pending_submission = "pending_submission"
    submitted = "submitted"
    rejected = "rejected"
    verified = "verified"
    lost_visibility = "lost_visibility"
    submission_unconfirmed = "submission_unconfirmed"
    submission_unverified = "submission_unverified"


# ── Models ────────────────────────────────────────────────────────────────────


class DirectoryRegistry(Base):
    """Platform-wide directory/listing registry. No RLS."""

    __tablename__ = "directory_registry"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    submission_method: Mapped[str] = mapped_column(Text, nullable=False)
    adapter_class: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    verification_method: Mapped[str] = mapped_column(Text, nullable=False)
    verification_config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    known_indexed_by_ai: Mapped[bool] = mapped_column(Boolean, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        kwargs.setdefault("verification_config", {})
        kwargs.setdefault("active", True)
        kwargs.setdefault("known_indexed_by_ai", False)
        kwargs.setdefault("created_at", _utcnow())
        super().__init__(**kwargs)


class OAuthToken(Base):
    """Encrypted OAuth tokens. Tenant-scoped with RLS."""

    __tablename__ = "oauth_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    access_token_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    refresh_token_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    wrapped_dek: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    kms_key_version: Mapped[str] = mapped_column(Text, nullable=False)
    access_token_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    account_subject: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_refreshed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        now = _utcnow()
        kwargs.setdefault("created_at", now)
        kwargs.setdefault("updated_at", now)
        super().__init__(**kwargs)


class PublishTarget(Base):
    """A publishing target (channel connection) for a business. Tenant-scoped."""

    __tablename__ = "publish_targets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    business_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("businesses.id"), nullable=False
    )
    channel: Mapped[PublishChannel] = mapped_column(Text, nullable=False)
    status: Mapped[PublishTargetStatus] = mapped_column(Text, nullable=False)
    connected_account_label: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    external_identifier: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    oauth_token_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("oauth_tokens.id"), nullable=True
    )
    publish_authorized_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_publish_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    meta: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        kwargs.setdefault("status", PublishTargetStatus.pending_oauth)
        kwargs.setdefault("meta", {})
        now = _utcnow()
        kwargs.setdefault("created_at", now)
        kwargs.setdefault("updated_at", now)
        super().__init__(**kwargs)


class PublishAttempt(Base):
    """A publish attempt for a content asset to a target. Tenant-scoped."""

    __tablename__ = "publish_attempts"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_publish_attempts_idempotency_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("publish_targets.id"), nullable=False
    )
    content_asset_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    brief_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[PublishAttemptStatus] = mapped_column(Text, nullable=False)
    attempts_count: Mapped[int] = mapped_column(Integer, nullable=False)
    external_object_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    public_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    next_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        kwargs.setdefault("status", PublishAttemptStatus.queued)
        kwargs.setdefault("attempts_count", 0)
        kwargs.setdefault("created_at", _utcnow())
        super().__init__(**kwargs)


class EntitySeed(Base):
    """An entity seeding record for a directory. Tenant-scoped."""

    __tablename__ = "entity_seeds"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    directory_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("directory_registry.id"), nullable=False
    )
    submission_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[EntitySeedStatus] = mapped_column(Text, nullable=False)
    external_listing_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    external_listing_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    first_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    verification_failures: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        kwargs.setdefault("status", EntitySeedStatus.pending_submission)
        kwargs.setdefault("verification_failures", 0)
        kwargs.setdefault("profile_snapshot", {})
        now = _utcnow()
        kwargs.setdefault("created_at", now)
        kwargs.setdefault("updated_at", now)
        super().__init__(**kwargs)


class VerificationPoll(Base):
    """Scheduled verification poll for a publish attempt or entity seed."""

    __tablename__ = "verification_polls"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    seed_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("entity_seeds.id"), nullable=True
    )
    publish_attempt_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("publish_attempts.id"), nullable=True
    )
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    outcome: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attempt_index: Mapped[int] = mapped_column(Integer, nullable=False)

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        super().__init__(**kwargs)
