"""Unit tests for whitelabel repository layer."""

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
    DomainVerificationStatus,
    EmailSenderDomain,
    EmailSenderStatus,
    SslCertStatus,
    ThemeAsset,
    WhitelabelConfig,
)
from app.modules.whitelabel.repository import (
    BrandingLeakReportRepository,
    BulkImportJobRepository,
    DomainMappingRepository,
    EmailSenderDomainRepository,
    ThemeAssetRepository,
    WhitelabelConfigRepository,
)


def _make_session():
    s = MagicMock()
    s.flush = AsyncMock()
    s.add = MagicMock()
    s.execute = AsyncMock()
    return s


def _scalar_result(obj):
    result = MagicMock()
    result.scalar_one_or_none.return_value = obj
    return result


def _scalars_result(objs):
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = objs
    result.scalars.return_value = scalars
    return result


class TestWhitelabelConfigRepository:
    def test_create(self):
        session = _make_session()
        repo = WhitelabelConfigRepository(session)
        tid = uuid.uuid4()

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            repo.create(tenant_id=tid, updated_at=datetime.now(timezone.utc))
        )
        assert session.add.called
        assert session.flush.called

    def test_get_by_tenant_found(self):
        session = _make_session()
        repo = WhitelabelConfigRepository(session)
        tid = uuid.uuid4()
        cfg = WhitelabelConfig(tenant_id=tid)
        session.execute = AsyncMock(return_value=_scalar_result(cfg))

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(repo.get_by_tenant(tid))
        assert result is cfg

    def test_get_by_tenant_not_found(self):
        session = _make_session()
        repo = WhitelabelConfigRepository(session)
        session.execute = AsyncMock(return_value=_scalar_result(None))

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(repo.get_by_tenant(uuid.uuid4()))
        assert result is None

    def test_update(self):
        session = _make_session()
        repo = WhitelabelConfigRepository(session)
        tid = uuid.uuid4()

        import asyncio
        asyncio.get_event_loop().run_until_complete(
            repo.update(tid, primary_color_hex="#FF0000")
        )
        assert session.execute.called


class TestDomainMappingRepository:
    def test_create(self):
        session = _make_session()
        repo = DomainMappingRepository(session)
        tid = uuid.uuid4()

        import asyncio
        asyncio.get_event_loop().run_until_complete(
            repo.create(tenant_id=tid, domain="example.com", domain_type="custom")
        )
        assert session.add.called

    def test_get_found(self):
        session = _make_session()
        repo = DomainMappingRepository(session)
        tid = uuid.uuid4()
        mid = uuid.uuid4()
        dm = DomainMapping(id=mid, tenant_id=tid, domain="example.com", domain_type="custom")
        session.execute = AsyncMock(return_value=_scalar_result(dm))

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(repo.get(mid, tid))
        assert result is dm

    def test_get_not_found(self):
        session = _make_session()
        repo = DomainMappingRepository(session)
        session.execute = AsyncMock(return_value=_scalar_result(None))

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(repo.get(uuid.uuid4(), uuid.uuid4()))
        assert result is None

    def test_get_by_domain(self):
        session = _make_session()
        repo = DomainMappingRepository(session)
        dm = DomainMapping(tenant_id=uuid.uuid4(), domain="example.com", domain_type="custom")
        session.execute = AsyncMock(return_value=_scalar_result(dm))

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(repo.get_by_domain("example.com"))
        assert result is dm

    def test_list_for_tenant(self):
        session = _make_session()
        repo = DomainMappingRepository(session)
        tid = uuid.uuid4()
        items = [DomainMapping(tenant_id=tid, domain="a.com", domain_type="custom")]
        session.execute = AsyncMock(return_value=_scalars_result(items))

        import asyncio
        results = asyncio.get_event_loop().run_until_complete(repo.list_for_tenant(tid))
        assert results == items

    def test_update_verification(self):
        session = _make_session()
        repo = DomainMappingRepository(session)

        import asyncio
        asyncio.get_event_loop().run_until_complete(
            repo.update_verification(
                uuid.uuid4(),
                DomainVerificationStatus.verified,
                verified_at=datetime.now(timezone.utc),
            )
        )
        assert session.execute.called

    def test_update_ssl(self):
        session = _make_session()
        repo = DomainMappingRepository(session)

        import asyncio
        asyncio.get_event_loop().run_until_complete(
            repo.update_ssl(uuid.uuid4(), SslCertStatus.active, ssl_cert_resource_id="res-123")
        )
        assert session.execute.called

    def test_revoke(self):
        session = _make_session()
        repo = DomainMappingRepository(session)

        import asyncio
        asyncio.get_event_loop().run_until_complete(repo.revoke(uuid.uuid4()))
        assert session.execute.called


class TestThemeAssetRepository:
    def test_create(self):
        session = _make_session()
        repo = ThemeAssetRepository(session)

        import asyncio
        asyncio.get_event_loop().run_until_complete(
            repo.create(
                tenant_id=uuid.uuid4(),
                asset_kind="logo",
                content_type="image/png",
                gcs_object_path="gs://bucket/logo.png",
            )
        )
        assert session.add.called

    def test_get_found(self):
        session = _make_session()
        repo = ThemeAssetRepository(session)
        tid = uuid.uuid4()
        aid = uuid.uuid4()
        asset = ThemeAsset(
            id=aid,
            tenant_id=tid,
            asset_kind="logo",
            content_type="image/png",
            gcs_object_path="gs://bucket/logo.png",
        )
        session.execute = AsyncMock(return_value=_scalar_result(asset))

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(repo.get(aid, tid))
        assert result is asset

    def test_list_for_tenant(self):
        session = _make_session()
        repo = ThemeAssetRepository(session)
        tid = uuid.uuid4()
        items = [
            ThemeAsset(
                tenant_id=tid,
                asset_kind="logo",
                content_type="image/png",
                gcs_object_path="gs://bucket/logo.png",
            )
        ]
        session.execute = AsyncMock(return_value=_scalars_result(items))

        import asyncio
        results = asyncio.get_event_loop().run_until_complete(repo.list_for_tenant(tid))
        assert results == items


class TestEmailSenderDomainRepository:
    def test_create(self):
        session = _make_session()
        repo = EmailSenderDomainRepository(session)

        import asyncio
        asyncio.get_event_loop().run_until_complete(
            repo.create(
                tenant_id=uuid.uuid4(),
                domain="mail.example.com",
                dkim_selector="citedby",
                dkim_public_key="pubkey",
                dkim_private_key_encrypted=b"enc",
                wrapped_dek=b"dek",
                kms_key_version="v1",
                from_address="hello@example.com",
                from_friendly_name="Example",
            )
        )
        assert session.add.called

    def test_get_found(self):
        session = _make_session()
        repo = EmailSenderDomainRepository(session)
        tid = uuid.uuid4()
        did = uuid.uuid4()
        domain = EmailSenderDomain(
            id=did,
            tenant_id=tid,
            domain="mail.example.com",
            dkim_selector="sel",
            dkim_public_key="pk",
            dkim_private_key_encrypted=b"enc",
            wrapped_dek=b"dek",
            kms_key_version="v1",
            from_address="h@ex.com",
            from_friendly_name="Ex",
        )
        session.execute = AsyncMock(return_value=_scalar_result(domain))

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(repo.get(did, tid))
        assert result is domain

    def test_get_by_tenant_domain(self):
        session = _make_session()
        repo = EmailSenderDomainRepository(session)
        session.execute = AsyncMock(return_value=_scalar_result(None))

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            repo.get_by_tenant_domain(uuid.uuid4(), "mail.example.com")
        )
        assert result is None

    def test_list_verified_all(self):
        session = _make_session()
        repo = EmailSenderDomainRepository(session)
        session.execute = AsyncMock(return_value=_scalars_result([]))

        import asyncio
        results = asyncio.get_event_loop().run_until_complete(repo.list_verified())
        assert results == []

    def test_list_verified_by_tenant(self):
        session = _make_session()
        repo = EmailSenderDomainRepository(session)
        session.execute = AsyncMock(return_value=_scalars_result([]))

        import asyncio
        results = asyncio.get_event_loop().run_until_complete(repo.list_verified(uuid.uuid4()))
        assert results == []

    def test_update_status(self):
        session = _make_session()
        repo = EmailSenderDomainRepository(session)

        import asyncio
        asyncio.get_event_loop().run_until_complete(
            repo.update_status(uuid.uuid4(), EmailSenderStatus.verified)
        )
        assert session.execute.called


class TestBulkImportJobRepository:
    def test_create(self):
        session = _make_session()
        repo = BulkImportJobRepository(session)

        import asyncio
        asyncio.get_event_loop().run_until_complete(
            repo.create(
                tenant_id=uuid.uuid4(),
                initiated_by_user_id=uuid.uuid4(),
                source_object_path="gs://bucket/import.csv",
            )
        )
        assert session.add.called

    def test_get_found(self):
        session = _make_session()
        repo = BulkImportJobRepository(session)
        tid = uuid.uuid4()
        jid = uuid.uuid4()
        job = BulkImportJob(
            id=jid,
            tenant_id=tid,
            initiated_by_user_id=uuid.uuid4(),
            source_object_path="gs://bucket/import.csv",
        )
        session.execute = AsyncMock(return_value=_scalar_result(job))

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(repo.get(jid, tid))
        assert result is job

    def test_list_for_tenant(self):
        session = _make_session()
        repo = BulkImportJobRepository(session)
        session.execute = AsyncMock(return_value=_scalars_result([]))

        import asyncio
        results = asyncio.get_event_loop().run_until_complete(repo.list_for_tenant(uuid.uuid4()))
        assert results == []

    def test_update_status(self):
        session = _make_session()
        repo = BulkImportJobRepository(session)

        import asyncio
        asyncio.get_event_loop().run_until_complete(
            repo.update_status(uuid.uuid4(), BulkImportStatus.completed, succeeded_rows=5)
        )
        assert session.execute.called


class TestBrandingLeakReportRepository:
    def test_create(self):
        session = _make_session()
        repo = BrandingLeakReportRepository(session)

        import asyncio
        asyncio.get_event_loop().run_until_complete(
            repo.create(
                scan_run_id="run-001",
                scan_target="https://example.com",
                findings=[],
                verdict="clean",
            )
        )
        assert session.add.called

    def test_list_recent(self):
        session = _make_session()
        repo = BrandingLeakReportRepository(session)
        report = BrandingLeakReport(
            scan_run_id="run-001",
            scan_target="https://example.com",
            findings=[],
            verdict="clean",
        )
        session.execute = AsyncMock(return_value=_scalars_result([report]))

        import asyncio
        results = asyncio.get_event_loop().run_until_complete(repo.list_recent(limit=10))
        assert len(results) == 1
        assert results[0] is report
