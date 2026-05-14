"""Unit tests for whitelabel service layer."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.whitelabel.models import (
    BrandingLeakReport,
    BulkImportJob,
    BulkImportStatus,
    DomainMapping,
    DomainType,
    DomainVerificationStatus,
    ThemeAsset,
    WhitelabelConfig,
)
from app.modules.whitelabel.service import (
    BulkImportCompleted,
    BulkImportService,
    DomainRevoked,
    DomainService,
    DomainVerified,
    WhitelabelConfigUpdated,
    WhitelabelService,
)


def _make_session():
    s = MagicMock()
    s.flush = AsyncMock()
    s.add = MagicMock()
    s.execute = AsyncMock()
    return s


def _make_config(tenant_id):
    cfg = WhitelabelConfig(tenant_id=tenant_id)
    return cfg


def _make_domain(tenant_id, mapping_id=None, status=DomainVerificationStatus.pending):
    dm = DomainMapping(
        id=mapping_id or uuid.uuid4(),
        tenant_id=tenant_id,
        domain="example.com",
        domain_type=DomainType.custom,
        verification_status=status,
        verification_token="token123",
        verification_method="dns_txt",
    )
    return dm


class TestWhitelabelServiceGetOrCreateConfig:
    @pytest.mark.asyncio
    async def test_creates_new_when_none_exists(self):
        session = _make_session()
        svc = WhitelabelService(session)
        tid = uuid.uuid4()
        cfg = _make_config(tid)

        with patch.object(svc._repo, "get_by_tenant", new=AsyncMock(return_value=None)), \
             patch.object(svc._repo, "create", new=AsyncMock(return_value=cfg)):
            result = await svc.get_or_create_config(tid)
        assert result is cfg

    @pytest.mark.asyncio
    async def test_returns_existing_when_found(self):
        session = _make_session()
        svc = WhitelabelService(session)
        tid = uuid.uuid4()
        cfg = _make_config(tid)

        with patch.object(svc._repo, "get_by_tenant", new=AsyncMock(return_value=cfg)):
            result = await svc.get_or_create_config(tid)
        assert result is cfg


class TestWhitelabelServiceUpdateConfig:
    @pytest.mark.asyncio
    async def test_raises_on_bad_hex_color(self):
        session = _make_session()
        svc = WhitelabelService(session)
        tid = uuid.uuid4()

        with pytest.raises(ValueError, match="Invalid hex color"):
            await svc.update_config(tenant_id=tid, primary_color_hex="notacolor")

    @pytest.mark.asyncio
    async def test_raises_on_bad_secondary_hex_color(self):
        session = _make_session()
        svc = WhitelabelService(session)
        tid = uuid.uuid4()

        with pytest.raises(ValueError, match="Invalid hex color"):
            await svc.update_config(tenant_id=tid, secondary_color_hex="bad")

    @pytest.mark.asyncio
    async def test_raises_on_unknown_font(self):
        session = _make_session()
        svc = WhitelabelService(session)
        tid = uuid.uuid4()

        with pytest.raises(ValueError, match="Invalid font family"):
            await svc.update_config(tenant_id=tid, font_family="Comic Sans")

    @pytest.mark.asyncio
    async def test_appends_event_on_success(self):
        session = _make_session()
        svc = WhitelabelService(session)
        tid = uuid.uuid4()
        cfg = _make_config(tid)

        with patch.object(svc._repo, "update", new=AsyncMock()), \
             patch.object(svc._repo, "get_by_tenant", new=AsyncMock(return_value=cfg)):
            await svc.update_config(tenant_id=tid, primary_color_hex="#FF0000")

        assert len(svc.pending_events) == 1
        assert isinstance(svc.pending_events[0], WhitelabelConfigUpdated)

    @pytest.mark.asyncio
    async def test_valid_font_passes(self):
        session = _make_session()
        svc = WhitelabelService(session)
        tid = uuid.uuid4()
        cfg = _make_config(tid)

        with patch.object(svc._repo, "update", new=AsyncMock()), \
             patch.object(svc._repo, "get_by_tenant", new=AsyncMock(return_value=cfg)):
            result = await svc.update_config(tenant_id=tid, font_family="Roboto")
        assert result is cfg


class TestWhitelabelServiceContrast:
    def test_returns_warnings_for_light_colors(self):
        session = _make_session()
        svc = WhitelabelService(session)
        warnings = svc.get_contrast_warnings(
            primary_color_hex="#EEEEEE",
            secondary_color_hex="#DDDDDD",
        )
        assert len(warnings) >= 1

    def test_no_warnings_for_dark_colors(self):
        session = _make_session()
        svc = WhitelabelService(session)
        warnings = svc.get_contrast_warnings(
            primary_color_hex="#000000",
            secondary_color_hex="#000000",
        )
        assert warnings == []


class TestWhitelabelServiceRegisterThemeAsset:
    @pytest.mark.asyncio
    async def test_raises_on_invalid_content_type(self):
        session = _make_session()
        svc = WhitelabelService(session)

        with pytest.raises(ValueError, match="Invalid content type"):
            await svc.register_theme_asset(
                tenant_id=uuid.uuid4(),
                asset_kind="logo",
                content_type="application/pdf",
                gcs_object_path="gs://bucket/logo.pdf",
            )

    @pytest.mark.asyncio
    async def test_creates_asset_with_valid_content_type(self):
        session = _make_session()
        svc = WhitelabelService(session)
        tid = uuid.uuid4()
        asset = ThemeAsset(
            tenant_id=tid,
            asset_kind="logo",
            content_type="image/png",
            gcs_object_path="gs://bucket/logo.png",
        )

        with patch.object(svc._asset_repo, "create", new=AsyncMock(return_value=asset)):
            result = await svc.register_theme_asset(
                tenant_id=tid,
                asset_kind="logo",
                content_type="image/png",
                gcs_object_path="gs://bucket/logo.png",
            )
        assert result is asset


class TestWhitelabelServiceScanBranding:
    @pytest.mark.asyncio
    async def test_detects_branding_and_creates_report(self):
        session = _make_session()
        svc = WhitelabelService(session)
        report = BrandingLeakReport(
            scan_run_id="run-001",
            scan_target="https://example.com",
            findings=[{"token": "CitedBy", "location": "content", "severity": "fail"}],
            verdict="fail",
        )

        with patch.object(svc._leak_repo, "create", new=AsyncMock(return_value=report)):
            result = await svc.scan_for_branding_leaks(
                scan_run_id="run-001",
                scan_target="https://example.com",
                content="Welcome to CitedBy platform",
            )
        assert result.verdict == "fail"
        assert len(result.findings) == 1

    @pytest.mark.asyncio
    async def test_clean_content_returns_clean_verdict(self):
        session = _make_session()
        svc = WhitelabelService(session)
        report = BrandingLeakReport(
            scan_run_id="run-002",
            scan_target="https://example.com",
            findings=[],
            verdict="clean",
        )

        with patch.object(svc._leak_repo, "create", new=AsyncMock(return_value=report)):
            result = await svc.scan_for_branding_leaks(
                scan_run_id="run-002",
                scan_target="https://example.com",
                content="Clean content with no branding leaks",
            )
        assert result.verdict == "clean"


class TestDomainServiceAddDomain:
    @pytest.mark.asyncio
    async def test_creates_mapping_with_token(self):
        session = _make_session()
        svc = DomainService(session)
        tid = uuid.uuid4()
        mapping = _make_domain(tid)

        with patch.object(svc._domain_repo, "create", new=AsyncMock(return_value=mapping)):
            result = await svc.add_domain(
                tenant_id=tid,
                domain="example.com",
                domain_type="custom",
                verification_method="dns_txt",
            )
        assert result is mapping

    @pytest.mark.asyncio
    async def test_platform_subdomain_auto_verifies(self):
        session = _make_session()
        svc = DomainService(session)
        tid = uuid.uuid4()
        mapping = _make_domain(tid, status=DomainVerificationStatus.verified)

        created_kwargs = {}

        async def _capture_create(**kwargs):
            created_kwargs.update(kwargs)
            return mapping

        with patch.object(svc._domain_repo, "create", new=_capture_create):
            result = await svc.add_domain(
                tenant_id=tid,
                domain="myagency.citedby.app",
                domain_type="platform_subdomain",
            )
        assert created_kwargs["verification_status"] == DomainVerificationStatus.verified
        assert created_kwargs["verified_at"] is not None


class TestDomainServiceVerifyDomain:
    @pytest.mark.asyncio
    async def test_transitions_to_verified(self):
        session = _make_session()
        svc = DomainService(session)
        tid = uuid.uuid4()
        mid = uuid.uuid4()
        mapping = _make_domain(tid, mapping_id=mid)

        with patch.object(svc._domain_repo, "get", new=AsyncMock(return_value=mapping)), \
             patch.object(svc._domain_repo, "update_verification", new=AsyncMock()):
            ok, msg = await svc.verify_domain(mapping_id=mid, tenant_id=tid)

        assert ok is True
        assert msg == "verified"
        assert len(svc.pending_events) == 1
        assert isinstance(svc.pending_events[0], DomainVerified)

    @pytest.mark.asyncio
    async def test_returns_false_when_not_found(self):
        session = _make_session()
        svc = DomainService(session)

        with patch.object(svc._domain_repo, "get", new=AsyncMock(return_value=None)):
            ok, msg = await svc.verify_domain(mapping_id=uuid.uuid4(), tenant_id=uuid.uuid4())

        assert ok is False
        assert "not found" in msg.lower()

    @pytest.mark.asyncio
    async def test_returns_already_verified_when_already_verified(self):
        session = _make_session()
        svc = DomainService(session)
        tid = uuid.uuid4()
        mid = uuid.uuid4()
        mapping = _make_domain(tid, mapping_id=mid, status=DomainVerificationStatus.verified)

        with patch.object(svc._domain_repo, "get", new=AsyncMock(return_value=mapping)):
            ok, msg = await svc.verify_domain(mapping_id=mid, tenant_id=tid)

        assert ok is True
        assert msg == "already_verified"


class TestDomainServiceRevokeDomain:
    @pytest.mark.asyncio
    async def test_sets_revoked_at_and_emits_event(self):
        session = _make_session()
        svc = DomainService(session)
        tid = uuid.uuid4()
        mid = uuid.uuid4()

        with patch.object(svc._domain_repo, "revoke", new=AsyncMock()):
            await svc.revoke_domain(mapping_id=mid, tenant_id=tid)

        assert len(svc.pending_events) == 1
        assert isinstance(svc.pending_events[0], DomainRevoked)


class TestDomainServiceGetVerificationInstructions:
    def test_returns_dns_instructions(self):
        session = _make_session()
        svc = DomainService(session)
        tid = uuid.uuid4()
        mapping = _make_domain(tid)

        instructions = svc.get_verification_instructions(mapping)
        assert "method" in instructions
        assert "token" in instructions
        assert "dns_record" in instructions
        assert instructions["dns_record"]["type"] == "TXT"


class TestBulkImportServiceCreateJob:
    @pytest.mark.asyncio
    async def test_creates_job_in_queued_state(self):
        session = _make_session()
        svc = BulkImportService(session)
        tid = uuid.uuid4()
        uid = uuid.uuid4()
        job = BulkImportJob(
            tenant_id=tid,
            initiated_by_user_id=uid,
            source_object_path="gs://bucket/import.csv",
        )

        with patch.object(svc._job_repo, "create", new=AsyncMock(return_value=job)):
            result = await svc.create_job(
                tenant_id=tid,
                initiated_by_user_id=uid,
                source_object_path="gs://bucket/import.csv",
            )
        assert result.status == BulkImportStatus.queued


class TestBulkImportServiceProcessRows:
    @pytest.mark.asyncio
    async def test_happy_path_all_valid_rows(self):
        session = _make_session()
        svc = BulkImportService(session)
        tid = uuid.uuid4()
        jid = uuid.uuid4()

        rows = [
            {"name": "Shop A", "locality": "Area 1", "city": "Mumbai", "category": "retail"},
            {"name": "Shop B", "locality": "Area 2", "city": "Mumbai", "category": "food"},
        ]

        with patch.object(svc._job_repo, "update_status", new=AsyncMock()):
            result = await svc.process_csv_rows(job_id=jid, tenant_id=tid, rows=rows)

        assert result["succeeded"] == 2
        assert result["failed"] == 0
        assert result["skipped"] == 0
        assert len(svc.pending_events) == 1
        assert isinstance(svc.pending_events[0], BulkImportCompleted)

    @pytest.mark.asyncio
    async def test_partial_success_with_invalid_rows(self):
        session = _make_session()
        svc = BulkImportService(session)
        tid = uuid.uuid4()
        jid = uuid.uuid4()

        rows = [
            {"name": "Shop A", "locality": "Area 1", "city": "Mumbai", "category": "retail"},
            {"name": "", "locality": "Area 2", "city": "Mumbai", "category": "food"},  # bad
            {"name": "Shop C", "locality": "Area 3", "city": "Delhi", "category": "tech"},
        ]

        with patch.object(svc._job_repo, "update_status", new=AsyncMock()):
            result = await svc.process_csv_rows(job_id=jid, tenant_id=tid, rows=rows)

        assert result["succeeded"] == 2
        assert result["failed"] == 1

    @pytest.mark.asyncio
    async def test_detects_duplicate_idempotency_keys(self):
        session = _make_session()
        svc = BulkImportService(session)
        tid = uuid.uuid4()
        jid = uuid.uuid4()

        # Same name+locality = same idempotency key
        rows = [
            {"name": "Shop A", "locality": "Area 1", "city": "Mumbai", "category": "retail"},
            {"name": "Shop A", "locality": "Area 1", "city": "Delhi", "category": "food"},  # dup
        ]

        with patch.object(svc._job_repo, "update_status", new=AsyncMock()):
            result = await svc.process_csv_rows(job_id=jid, tenant_id=tid, rows=rows)

        assert result["succeeded"] == 1
        assert result["skipped"] == 1

    @pytest.mark.asyncio
    async def test_get_job_delegates_to_repo(self):
        session = _make_session()
        svc = BulkImportService(session)
        tid = uuid.uuid4()
        jid = uuid.uuid4()
        job = BulkImportJob(
            id=jid,
            tenant_id=tid,
            initiated_by_user_id=uuid.uuid4(),
            source_object_path="gs://bucket/import.csv",
        )

        with patch.object(svc._job_repo, "get", new=AsyncMock(return_value=job)):
            result = await svc.get_job(job_id=jid, tenant_id=tid)
        assert result is job
