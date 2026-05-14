"""SQLAlchemy ORM models for the Whitelabel & Agency Portal module."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, LargeBinary, Text
from sqlalchemy import Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Enums ──────────────────────────────────────────────────────────────────────


class DomainType(str, enum.Enum):
    platform_subdomain = "platform_subdomain"
    custom = "custom"


class DomainVerificationStatus(str, enum.Enum):
    pending = "pending"
    verified = "verified"
    failed = "failed"
    revoked = "revoked"


class SslCertStatus(str, enum.Enum):
    not_required = "not_required"
    provisioning = "provisioning"
    active = "active"
    failed = "failed"


class EmailSenderStatus(str, enum.Enum):
    pending_dns = "pending_dns"
    verified = "verified"
    failed = "failed"
    revoked = "revoked"


class BulkImportStatus(str, enum.Enum):
    queued = "queued"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class AssetKind(str, enum.Enum):
    logo = "logo"
    favicon = "favicon"
    pdf_logo = "pdf_logo"
    email_header = "email_header"


# ── Models ────────────────────────────────────────────────────────────────────


class ThemeAsset(Base):
    """Uploaded branding assets for a tenant."""

    __tablename__ = "theme_assets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    asset_kind: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    gcs_object_path: Mapped[str] = mapped_column(Text, nullable=False)
    width_px: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height_px: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    safe_for_email: Mapped[bool] = mapped_column(Boolean, nullable=False)
    uploaded_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        kwargs.setdefault("safe_for_email", False)
        kwargs.setdefault("created_at", _utcnow())
        super().__init__(**kwargs)


class EmailSenderDomain(Base):
    """Email sender domain verification and DKIM configuration."""

    __tablename__ = "email_sender_domains"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    domain: Mapped[str] = mapped_column(Text, nullable=False)
    verification_status: Mapped[str] = mapped_column(Text, nullable=False)
    dkim_selector: Mapped[str] = mapped_column(Text, nullable=False)
    dkim_public_key: Mapped[str] = mapped_column(Text, nullable=False)
    dkim_private_key_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    wrapped_dek: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    kms_key_version: Mapped[str] = mapped_column(Text, nullable=False)
    spf_include_status: Mapped[str] = mapped_column(Text, nullable=False)
    dmarc_status: Mapped[str] = mapped_column(Text, nullable=False)
    from_address: Mapped[str] = mapped_column(Text, nullable=False)
    from_friendly_name: Mapped[str] = mapped_column(Text, nullable=False)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_health_check_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        kwargs.setdefault("verification_status", EmailSenderStatus.pending_dns)
        kwargs.setdefault("spf_include_status", "unknown")
        kwargs.setdefault("dmarc_status", "unknown")
        kwargs.setdefault("created_at", _utcnow())
        super().__init__(**kwargs)


class WhitelabelConfig(Base):
    """Whitelabel configuration for a tenant."""

    __tablename__ = "whitelabel_configs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True)
    product_display_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tagline: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    logo_asset_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("theme_assets.id"), nullable=True
    )
    favicon_asset_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("theme_assets.id"), nullable=True
    )
    primary_color_hex: Mapped[str] = mapped_column(Text, nullable=False)
    secondary_color_hex: Mapped[str] = mapped_column(Text, nullable=False)
    font_family: Mapped[str] = mapped_column(Text, nullable=False)
    support_email: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    customizable_strings: Mapped[dict] = mapped_column(JSONB, nullable=False)
    content_approval_flow: Mapped[str] = mapped_column(Text, nullable=False)
    sender_domain_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("email_sender_domains.id"), nullable=True
    )
    pdf_footer_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        kwargs.setdefault("primary_color_hex", "#2A6FDB")
        kwargs.setdefault("secondary_color_hex", "#37474F")
        kwargs.setdefault("font_family", "Inter")
        kwargs.setdefault("customizable_strings", {})
        kwargs.setdefault("content_approval_flow", "agency_only")
        kwargs.setdefault("updated_at", _utcnow())
        super().__init__(**kwargs)


class DomainMapping(Base):
    """Custom domain mapping for a tenant."""

    __tablename__ = "domain_mappings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    domain: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    domain_type: Mapped[str] = mapped_column(Text, nullable=False)
    verification_status: Mapped[str] = mapped_column(Text, nullable=False)
    verification_method: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    verification_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ssl_cert_status: Mapped[str] = mapped_column(Text, nullable=False)
    ssl_cert_resource_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ssl_active_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_dns_heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        kwargs.setdefault("verification_status", DomainVerificationStatus.pending)
        kwargs.setdefault("ssl_cert_status", SslCertStatus.not_required)
        kwargs.setdefault("created_at", _utcnow())
        super().__init__(**kwargs)


class BulkImportJob(Base):
    """Bulk import job for agency CSV uploads."""

    __tablename__ = "bulk_import_jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    initiated_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=False
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    source_object_path: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    total_rows: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    succeeded_rows: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    failed_rows: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    result_report_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        kwargs.setdefault("source", "csv_upload")
        kwargs.setdefault("status", BulkImportStatus.queued)
        kwargs.setdefault("created_at", _utcnow())
        super().__init__(**kwargs)


class BrandingLeakReport(Base):
    """Platform-wide branding leak scan report. No tenant_id, no RLS."""

    __tablename__ = "branding_leak_reports"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    scan_run_id: Mapped[str] = mapped_column(Text, nullable=False)
    scan_target: Mapped[str] = mapped_column(Text, nullable=False)
    findings: Mapped[list] = mapped_column(JSONB, nullable=False)
    verdict: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", uuid.uuid4())
        kwargs.setdefault("findings", [])
        kwargs.setdefault("created_at", _utcnow())
        super().__init__(**kwargs)
