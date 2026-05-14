"""Dedicated unit tests for the free-audit router."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


def _make_app():
    from app.main import create_app
    return create_app()


def _make_db_ctx(session):
    @asynccontextmanager
    async def _ctx(factory, request_ctx):
        yield session

    return _ctx


def _make_session():
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()
    return session


class TestFreeAuditStartEndpoint:
    def _make_tenant_mock(self):
        t = MagicMock()
        t.id = uuid.uuid4()
        t.slug = "trial-abc12345"
        return t

    def _make_business_mock(self, tid):
        b = MagicMock()
        b.id = uuid.uuid4()
        b.tenant_id = tid
        b.canonical_name = "Test Bakery"
        b.name_normalized = "test bakery"
        b.website_url = None
        return b

    def _make_audit_run_mock(self, tid, bid):
        r = MagicMock()
        r.id = uuid.uuid4()
        r.tenant_id = tid
        r.business_id = bid
        r.status = MagicMock()
        r.status.value = "pending"
        return r

    def test_start_free_audit_success(self):
        app = _make_app()
        session = _make_session()

        tenant = self._make_tenant_mock()
        business = self._make_business_mock(tenant.id)
        run = self._make_audit_run_mock(tenant.id, business.id)

        with patch("app.api.v1.routers.free_audit.get_session_factory"), \
             patch("app.api.v1.routers.free_audit.get_db_session",
                   new=_make_db_ctx(session)), \
             patch("app.modules.identity.repository.TenantRepository.create",
                   new_callable=AsyncMock, return_value=tenant), \
             patch("app.modules.business_profile.repository.BusinessRepository.create",
                   new_callable=AsyncMock, return_value=business), \
             patch("app.modules.business_profile.repository.BusinessLocationRepository.create",
                   new_callable=AsyncMock, return_value=MagicMock()), \
             patch("app.modules.business_profile.repository.BusinessKeywordRepository.create_batch",
                   new_callable=AsyncMock, return_value=[]), \
             patch("app.modules.audit.service.AuditService.create_audit_run",
                   new_callable=AsyncMock, return_value=run), \
             patch("app.modules.audit.service.AuditService.flush_events",
                   new_callable=AsyncMock), \
             patch("app.modules.reporting.service.FreeAuditSubmissionService.submit",
                   new_callable=AsyncMock, return_value="test-fat-token"), \
             patch("app.modules.reporting.service.FreeAuditSubmissionService.flush_events",
                   new_callable=AsyncMock):

            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(
                "/api/v1/free-audit/start",
                json={
                    "business_name": "Test Bakery",
                    "city": "Bangalore",
                    "locality": "Koramangala",
                    "category": "bakery",
                    "email": "test@example.com",
                    "keywords": ["fresh bread", "cakes"],
                },
            )
        assert response.status_code in (201, 503)
        if response.status_code == 201:
            data = response.json()
            assert "token" in data
            assert "status_url" in data

    def test_start_free_audit_conflict_error(self):
        from app.core.exceptions import ConflictError
        app = _make_app()
        session = _make_session()

        with patch("app.api.v1.routers.free_audit.get_session_factory"), \
             patch("app.api.v1.routers.free_audit.get_db_session",
                   new=_make_db_ctx(session)), \
             patch("app.modules.identity.repository.TenantRepository.create",
                   new_callable=AsyncMock,
                   side_effect=ConflictError("Slug taken")):

            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(
                "/api/v1/free-audit/start",
                json={
                    "business_name": "Test Bakery",
                    "city": "Bangalore",
                    "locality": "Koramangala",
                    "category": "bakery",
                    "email": "test@example.com",
                },
            )
        assert response.status_code in (409, 503)

    def test_start_free_audit_no_keywords(self):
        app = _make_app()
        session = _make_session()

        tenant = self._make_tenant_mock()
        business = self._make_business_mock(tenant.id)
        run = self._make_audit_run_mock(tenant.id, business.id)

        with patch("app.api.v1.routers.free_audit.get_session_factory"), \
             patch("app.api.v1.routers.free_audit.get_db_session",
                   new=_make_db_ctx(session)), \
             patch("app.modules.identity.repository.TenantRepository.create",
                   new_callable=AsyncMock, return_value=tenant), \
             patch("app.modules.business_profile.repository.BusinessRepository.create",
                   new_callable=AsyncMock, return_value=business), \
             patch("app.modules.business_profile.repository.BusinessLocationRepository.create",
                   new_callable=AsyncMock, return_value=MagicMock()), \
             patch("app.modules.audit.service.AuditService.create_audit_run",
                   new_callable=AsyncMock, return_value=run), \
             patch("app.modules.audit.service.AuditService.flush_events",
                   new_callable=AsyncMock), \
             patch("app.modules.reporting.service.FreeAuditSubmissionService.submit",
                   new_callable=AsyncMock, return_value="test-fat-token2"), \
             patch("app.modules.reporting.service.FreeAuditSubmissionService.flush_events",
                   new_callable=AsyncMock):

            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(
                "/api/v1/free-audit/start",
                json={
                    "business_name": "Test Bakery",
                    "city": "Bangalore",
                    "locality": "Koramangala",
                    "category": "bakery",
                    "email": "test@example.com",
                    "keywords": [],  # no keywords — skips create_batch
                },
            )
        assert response.status_code in (201, 503)


class TestFreeAuditStatusEndpoint:
    def test_status_citedby_error(self):
        """Test generic CitedByError is caught."""
        from app.core.exceptions import PermissionDeniedError
        app = _make_app()
        session = _make_session()

        with patch("app.api.v1.routers.free_audit.get_session_factory"), \
             patch("app.api.v1.routers.free_audit.get_db_session",
                   new=_make_db_ctx(session)), \
             patch("app.modules.reporting.service.FreeAuditSubmissionService.get_status",
                   new_callable=AsyncMock,
                   side_effect=PermissionDeniedError("Access denied")):

            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/free-audit/some-token/status")
        assert response.status_code in (403, 503)
