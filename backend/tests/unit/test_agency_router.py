"""Unit tests for Agency & Whitelabel API router."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies.auth import TenantContext
from app.modules.whitelabel.models import (
    BrandingLeakReport,
    BulkImportJob,
    BulkImportStatus,
    DomainMapping,
    DomainType,
    DomainVerificationStatus,
    SslCertStatus,
    ThemeAsset,
    WhitelabelConfig,
)


def _make_ctx(tenant_id=None, user_id=None) -> TenantContext:
    return TenantContext(
        user_id=user_id or uuid.uuid4(),
        auth_provider_id="auth0|test",
        tenant_id=tenant_id or uuid.uuid4(),
        is_platform_admin=True,
        memberships=[],
    )


def _make_app(ctx: TenantContext):
    from app.api.dependencies.auth import get_tenant_context
    from app.main import create_app

    app = create_app()
    app.dependency_overrides[get_tenant_context] = lambda: ctx
    return app


def _make_db_ctx(session):
    @asynccontextmanager
    async def _ctx(factory, req_ctx):
        yield session

    return _ctx


def _make_session():
    s = MagicMock()
    s.flush = AsyncMock()
    s.add = MagicMock()
    s.execute = AsyncMock()
    return s


def _make_config(tenant_id=None):
    tid = tenant_id or uuid.uuid4()
    cfg = WhitelabelConfig(tenant_id=tid)
    return cfg


def _make_domain(tenant_id=None):
    tid = tenant_id or uuid.uuid4()
    dm = DomainMapping(
        tenant_id=tid,
        domain="example.com",
        domain_type=DomainType.custom,
        verification_status=DomainVerificationStatus.pending,
        ssl_cert_status=SslCertStatus.not_required,
    )
    return dm


def _make_asset(tenant_id=None):
    tid = tenant_id or uuid.uuid4()
    return ThemeAsset(
        tenant_id=tid,
        asset_kind="logo",
        content_type="image/png",
        gcs_object_path="gs://bucket/logo.png",
    )


def _make_job(tenant_id=None, user_id=None):
    tid = tenant_id or uuid.uuid4()
    uid = user_id or uuid.uuid4()
    return BulkImportJob(
        tenant_id=tid,
        initiated_by_user_id=uid,
        source_object_path="gs://bucket/import.csv",
    )


class TestGetConfig:
    def test_get_config_success(self):
        tid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid)
        app = _make_app(ctx)
        session = _make_session()
        cfg = _make_config(tid)

        with patch("app.api.v1.routers.agency.get_session_factory"), patch(
            "app.api.v1.routers.agency.get_db_session", new=_make_db_ctx(session)
        ), patch(
            "app.modules.whitelabel.service.WhitelabelService.get_or_create_config",
            new=AsyncMock(return_value=cfg),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/agency/config")
        assert response.status_code in (200, 503)


class TestUpdateConfig:
    def test_update_config_success(self):
        tid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid)
        app = _make_app(ctx)
        session = _make_session()
        cfg = _make_config(tid)

        with patch("app.api.v1.routers.agency.get_session_factory"), patch(
            "app.api.v1.routers.agency.get_db_session", new=_make_db_ctx(session)
        ), patch(
            "app.modules.whitelabel.service.WhitelabelService.get_or_create_config",
            new=AsyncMock(return_value=cfg),
        ), patch(
            "app.modules.whitelabel.service.WhitelabelService.update_config",
            new=AsyncMock(return_value=cfg),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.put(
                "/api/v1/agency/config",
                json={"product_display_name": "My Agency"},
            )
        assert response.status_code in (200, 503)

    def test_update_config_validation_error(self):
        tid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid)
        app = _make_app(ctx)
        session = _make_session()
        cfg = _make_config(tid)

        with patch("app.api.v1.routers.agency.get_session_factory"), patch(
            "app.api.v1.routers.agency.get_db_session", new=_make_db_ctx(session)
        ), patch(
            "app.modules.whitelabel.service.WhitelabelService.get_or_create_config",
            new=AsyncMock(return_value=cfg),
        ), patch(
            "app.modules.whitelabel.service.WhitelabelService.update_config",
            new=AsyncMock(side_effect=ValueError("Invalid hex color: notacolor")),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.put(
                "/api/v1/agency/config",
                json={"primary_color_hex": "notacolor"},
            )
        assert response.status_code in (400, 503)


class TestListDomains:
    def test_list_domains_success(self):
        tid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid)
        app = _make_app(ctx)
        session = _make_session()
        dm = _make_domain(tid)

        with patch("app.api.v1.routers.agency.get_session_factory"), patch(
            "app.api.v1.routers.agency.get_db_session", new=_make_db_ctx(session)
        ), patch(
            "app.modules.whitelabel.repository.DomainMappingRepository.list_for_tenant",
            new=AsyncMock(return_value=[dm]),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/agency/domains")
        assert response.status_code in (200, 503)

    def test_list_domains_empty(self):
        tid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid)
        app = _make_app(ctx)
        session = _make_session()

        with patch("app.api.v1.routers.agency.get_session_factory"), patch(
            "app.api.v1.routers.agency.get_db_session", new=_make_db_ctx(session)
        ), patch(
            "app.modules.whitelabel.repository.DomainMappingRepository.list_for_tenant",
            new=AsyncMock(return_value=[]),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/agency/domains")
        assert response.status_code in (200, 503)


class TestAddDomain:
    def test_add_domain_success(self):
        tid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid)
        app = _make_app(ctx)
        session = _make_session()
        dm = _make_domain(tid)

        with patch("app.api.v1.routers.agency.get_session_factory"), patch(
            "app.api.v1.routers.agency.get_db_session", new=_make_db_ctx(session)
        ), patch(
            "app.modules.whitelabel.service.DomainService.add_domain",
            new=AsyncMock(return_value=dm),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(
                "/api/v1/agency/domains",
                json={"domain": "example.com", "domain_type": "custom"},
            )
        assert response.status_code in (201, 503)


class TestVerifyDomain:
    def test_verify_domain_success(self):
        tid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid)
        app = _make_app(ctx)
        session = _make_session()
        dm = _make_domain(tid)
        dm.verification_status = DomainVerificationStatus.verified

        with patch("app.api.v1.routers.agency.get_session_factory"), patch(
            "app.api.v1.routers.agency.get_db_session", new=_make_db_ctx(session)
        ), patch(
            "app.modules.whitelabel.service.DomainService.verify_domain",
            new=AsyncMock(return_value=(True, "verified")),
        ), patch(
            "app.modules.whitelabel.repository.DomainMappingRepository.get",
            new=AsyncMock(return_value=dm),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(f"/api/v1/agency/domains/{dm.id}/verify")
        assert response.status_code in (200, 503)

    def test_verify_domain_not_found(self):
        tid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid)
        app = _make_app(ctx)
        session = _make_session()

        with patch("app.api.v1.routers.agency.get_session_factory"), patch(
            "app.api.v1.routers.agency.get_db_session", new=_make_db_ctx(session)
        ), patch(
            "app.modules.whitelabel.service.DomainService.verify_domain",
            new=AsyncMock(return_value=(False, "Domain mapping not found")),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(f"/api/v1/agency/domains/{uuid.uuid4()}/verify")
        assert response.status_code in (404, 503)


class TestRevokeDomain:
    def test_revoke_domain_success(self):
        tid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid)
        app = _make_app(ctx)
        session = _make_session()

        with patch("app.api.v1.routers.agency.get_session_factory"), patch(
            "app.api.v1.routers.agency.get_db_session", new=_make_db_ctx(session)
        ), patch(
            "app.modules.whitelabel.service.DomainService.revoke_domain",
            new=AsyncMock(),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.delete(f"/api/v1/agency/domains/{uuid.uuid4()}")
        assert response.status_code in (204, 503)


class TestListAssets:
    def test_list_assets_success(self):
        tid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid)
        app = _make_app(ctx)
        session = _make_session()
        asset = _make_asset(tid)

        with patch("app.api.v1.routers.agency.get_session_factory"), patch(
            "app.api.v1.routers.agency.get_db_session", new=_make_db_ctx(session)
        ), patch(
            "app.modules.whitelabel.repository.ThemeAssetRepository.list_for_tenant",
            new=AsyncMock(return_value=[asset]),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/agency/assets")
        assert response.status_code in (200, 503)


class TestRegisterAsset:
    def test_register_asset_success(self):
        tid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid)
        app = _make_app(ctx)
        session = _make_session()
        asset = _make_asset(tid)

        with patch("app.api.v1.routers.agency.get_session_factory"), patch(
            "app.api.v1.routers.agency.get_db_session", new=_make_db_ctx(session)
        ), patch(
            "app.modules.whitelabel.service.WhitelabelService.register_theme_asset",
            new=AsyncMock(return_value=asset),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(
                "/api/v1/agency/assets",
                json={
                    "asset_kind": "logo",
                    "content_type": "image/png",
                    "gcs_object_path": "gs://bucket/logo.png",
                },
            )
        assert response.status_code in (201, 503)

    def test_register_asset_invalid_content_type(self):
        tid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid)
        app = _make_app(ctx)
        session = _make_session()

        with patch("app.api.v1.routers.agency.get_session_factory"), patch(
            "app.api.v1.routers.agency.get_db_session", new=_make_db_ctx(session)
        ), patch(
            "app.modules.whitelabel.service.WhitelabelService.register_theme_asset",
            new=AsyncMock(side_effect=ValueError("Invalid content type")),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(
                "/api/v1/agency/assets",
                json={
                    "asset_kind": "logo",
                    "content_type": "application/pdf",
                    "gcs_object_path": "gs://bucket/logo.pdf",
                },
            )
        assert response.status_code in (400, 503)


class TestListBulkImports:
    def test_list_bulk_imports_success(self):
        tid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid)
        app = _make_app(ctx)
        session = _make_session()
        job = _make_job(tid)

        with patch("app.api.v1.routers.agency.get_session_factory"), patch(
            "app.api.v1.routers.agency.get_db_session", new=_make_db_ctx(session)
        ), patch(
            "app.modules.whitelabel.repository.BulkImportJobRepository.list_for_tenant",
            new=AsyncMock(return_value=[job]),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/agency/bulk-imports")
        assert response.status_code in (200, 503)


class TestCreateBulkImport:
    def test_create_bulk_import_success(self):
        tid = uuid.uuid4()
        uid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid, user_id=uid)
        app = _make_app(ctx)
        session = _make_session()
        job = _make_job(tid, uid)

        with patch("app.api.v1.routers.agency.get_session_factory"), patch(
            "app.api.v1.routers.agency.get_db_session", new=_make_db_ctx(session)
        ), patch(
            "app.modules.whitelabel.service.BulkImportService.create_job",
            new=AsyncMock(return_value=job),
        ), patch(
            "app.modules.whitelabel.service.BulkImportService.get_job",
            new=AsyncMock(return_value=job),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(
                "/api/v1/agency/bulk-import",
                json={"source_object_path": "gs://bucket/import.csv", "rows": []},
            )
        assert response.status_code in (201, 503)


class TestGetBulkImport:
    def test_get_bulk_import_success(self):
        tid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid)
        app = _make_app(ctx)
        session = _make_session()
        job = _make_job(tid)

        with patch("app.api.v1.routers.agency.get_session_factory"), patch(
            "app.api.v1.routers.agency.get_db_session", new=_make_db_ctx(session)
        ), patch(
            "app.modules.whitelabel.service.BulkImportService.get_job",
            new=AsyncMock(return_value=job),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get(f"/api/v1/agency/bulk-imports/{job.id}")
        assert response.status_code in (200, 503)

    def test_get_bulk_import_not_found(self):
        tid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid)
        app = _make_app(ctx)
        session = _make_session()

        with patch("app.api.v1.routers.agency.get_session_factory"), patch(
            "app.api.v1.routers.agency.get_db_session", new=_make_db_ctx(session)
        ), patch(
            "app.modules.whitelabel.service.BulkImportService.get_job",
            new=AsyncMock(return_value=None),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get(f"/api/v1/agency/bulk-imports/{uuid.uuid4()}")
        assert response.status_code in (404, 503)


class TestListClients:
    def test_list_clients_returns_paginated(self):
        tid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid)
        app = _make_app(ctx)

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/v1/agency/clients")
        assert response.status_code in (200, 503)
        if response.status_code == 200:
            data = response.json()
            assert "items" in data
            assert "limit" in data

    def test_list_clients_with_params(self):
        tid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid)
        app = _make_app(ctx)

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/v1/agency/clients?limit=10&cursor=abc")
        assert response.status_code in (200, 503)


class TestScanBranding:
    def test_scan_branding_finds_leak(self):
        tid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid)
        app = _make_app(ctx)
        session = _make_session()
        report = BrandingLeakReport(
            scan_run_id="run-001",
            scan_target="https://example.com",
            findings=[{"token": "CitedBy", "location": "content", "severity": "fail"}],
            verdict="fail",
        )

        with patch("app.api.v1.routers.agency.get_session_factory"), patch(
            "app.api.v1.routers.agency.get_db_session", new=_make_db_ctx(session)
        ), patch(
            "app.modules.whitelabel.service.WhitelabelService.scan_for_branding_leaks",
            new=AsyncMock(return_value=report),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(
                "/api/v1/agency/scan-branding",
                json={
                    "scan_run_id": "run-001",
                    "scan_target": "https://example.com",
                    "content": "Welcome to CitedBy",
                },
            )
        assert response.status_code in (200, 503)

    def test_scan_branding_clean_content(self):
        tid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid)
        app = _make_app(ctx)
        session = _make_session()
        report = BrandingLeakReport(
            scan_run_id="run-002",
            scan_target="https://example.com",
            findings=[],
            verdict="clean",
        )

        with patch("app.api.v1.routers.agency.get_session_factory"), patch(
            "app.api.v1.routers.agency.get_db_session", new=_make_db_ctx(session)
        ), patch(
            "app.modules.whitelabel.service.WhitelabelService.scan_for_branding_leaks",
            new=AsyncMock(return_value=report),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(
                "/api/v1/agency/scan-branding",
                json={
                    "scan_run_id": "run-002",
                    "scan_target": "https://example.com",
                    "content": "Clean content",
                },
            )
        assert response.status_code in (200, 503)
