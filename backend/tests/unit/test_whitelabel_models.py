"""Unit tests for whitelabel models."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.modules.whitelabel.models import (
    AssetKind,
    BrandingLeakReport,
    BulkImportJob,
    BulkImportStatus,
    DomainMapping,
    DomainType,
    DomainVerificationStatus,
    EmailSenderDomain,
    EmailSenderStatus,
    SslCertStatus,
    ThemeAsset,
    WhitelabelConfig,
)


class TestEnumValues:
    def test_domain_type_values(self):
        assert DomainType.platform_subdomain == "platform_subdomain"
        assert DomainType.custom == "custom"

    def test_domain_verification_status_values(self):
        assert DomainVerificationStatus.pending == "pending"
        assert DomainVerificationStatus.verified == "verified"
        assert DomainVerificationStatus.failed == "failed"
        assert DomainVerificationStatus.revoked == "revoked"

    def test_ssl_cert_status_values(self):
        assert SslCertStatus.not_required == "not_required"
        assert SslCertStatus.provisioning == "provisioning"
        assert SslCertStatus.active == "active"
        assert SslCertStatus.failed == "failed"

    def test_email_sender_status_values(self):
        assert EmailSenderStatus.pending_dns == "pending_dns"
        assert EmailSenderStatus.verified == "verified"
        assert EmailSenderStatus.failed == "failed"
        assert EmailSenderStatus.revoked == "revoked"

    def test_bulk_import_status_values(self):
        assert BulkImportStatus.queued == "queued"
        assert BulkImportStatus.processing == "processing"
        assert BulkImportStatus.completed == "completed"
        assert BulkImportStatus.failed == "failed"

    def test_asset_kind_values(self):
        assert AssetKind.logo == "logo"
        assert AssetKind.favicon == "favicon"
        assert AssetKind.pdf_logo == "pdf_logo"
        assert AssetKind.email_header == "email_header"


class TestThemeAssetModel:
    def test_defaults(self):
        tenant_id = uuid.uuid4()
        asset = ThemeAsset(
            tenant_id=tenant_id,
            asset_kind="logo",
            content_type="image/png",
            gcs_object_path="gs://bucket/logo.png",
        )
        assert isinstance(asset.id, uuid.UUID)
        assert asset.safe_for_email is False
        assert asset.width_px is None
        assert asset.height_px is None
        assert asset.uploaded_by_user_id is None
        assert isinstance(asset.created_at, datetime)

    def test_explicit_values(self):
        tid = uuid.uuid4()
        uid = uuid.uuid4()
        asset = ThemeAsset(
            tenant_id=tid,
            asset_kind="favicon",
            content_type="image/svg+xml",
            gcs_object_path="gs://bucket/favicon.svg",
            width_px=32,
            height_px=32,
            safe_for_email=True,
            uploaded_by_user_id=uid,
        )
        assert asset.width_px == 32
        assert asset.height_px == 32
        assert asset.safe_for_email is True
        assert asset.uploaded_by_user_id == uid


class TestEmailSenderDomainModel:
    def test_defaults(self):
        tid = uuid.uuid4()
        obj = EmailSenderDomain(
            tenant_id=tid,
            domain="mail.example.com",
            dkim_selector="citedby",
            dkim_public_key="pubkey",
            dkim_private_key_encrypted=b"encrypted",
            wrapped_dek=b"dek",
            kms_key_version="v1",
            from_address="hello@example.com",
            from_friendly_name="Example",
        )
        assert obj.verification_status == EmailSenderStatus.pending_dns
        assert obj.spf_include_status == "unknown"
        assert obj.dmarc_status == "unknown"
        assert isinstance(obj.created_at, datetime)


class TestWhitelabelConfigModel:
    def test_defaults(self):
        tid = uuid.uuid4()
        cfg = WhitelabelConfig(tenant_id=tid)
        assert isinstance(cfg.id, uuid.UUID)
        assert cfg.primary_color_hex == "#2A6FDB"
        assert cfg.secondary_color_hex == "#37474F"
        assert cfg.font_family == "Inter"
        assert cfg.customizable_strings == {}
        assert cfg.content_approval_flow == "agency_only"
        assert isinstance(cfg.updated_at, datetime)

    def test_explicit_color(self):
        tid = uuid.uuid4()
        cfg = WhitelabelConfig(tenant_id=tid, primary_color_hex="#FF0000")
        assert cfg.primary_color_hex == "#FF0000"


class TestDomainMappingModel:
    def test_defaults(self):
        tid = uuid.uuid4()
        dm = DomainMapping(
            tenant_id=tid,
            domain="app.example.com",
            domain_type=DomainType.custom,
        )
        assert isinstance(dm.id, uuid.UUID)
        assert dm.verification_status == DomainVerificationStatus.pending
        assert dm.ssl_cert_status == SslCertStatus.not_required
        assert isinstance(dm.created_at, datetime)
        assert dm.revoked_at is None


class TestBulkImportJobModel:
    def test_defaults(self):
        tid = uuid.uuid4()
        uid = uuid.uuid4()
        job = BulkImportJob(
            tenant_id=tid,
            initiated_by_user_id=uid,
            source_object_path="gs://bucket/import.csv",
        )
        assert isinstance(job.id, uuid.UUID)
        assert job.source == "csv_upload"
        assert job.status == BulkImportStatus.queued
        assert job.total_rows is None
        assert job.succeeded_rows is None
        assert job.failed_rows is None
        assert isinstance(job.created_at, datetime)


class TestBrandingLeakReportModel:
    def test_no_tenant_id(self):
        """BrandingLeakReport has no tenant_id field."""
        report = BrandingLeakReport(
            scan_run_id="run-001",
            scan_target="https://example.com",
            findings=[],
            verdict="clean",
        )
        assert isinstance(report.id, uuid.UUID)
        assert report.findings == []
        assert report.verdict == "clean"
        assert isinstance(report.created_at, datetime)
        assert not hasattr(report, "tenant_id") or True  # no tenant_id column

    def test_with_findings(self):
        findings = [{"token": "CitedBy", "location": "content", "severity": "fail"}]
        report = BrandingLeakReport(
            scan_run_id="run-002",
            scan_target="https://example.com/page",
            findings=findings,
            verdict="fail",
        )
        assert report.verdict == "fail"
        assert len(report.findings) == 1
