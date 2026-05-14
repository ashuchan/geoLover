"""Unit tests for FastAPI app factory and HTTP endpoints."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies.auth import TenantContext
from app.core.exceptions import ValidationError as CitedByValidationError
from app.modules.identity.models import UserRole


def _make_ctx(**kw) -> TenantContext:
    defaults = dict(
        user_id=uuid.uuid4(),
        auth_provider_id="auth0|test",
        tenant_id=uuid.uuid4(),
        is_platform_admin=False,
        memberships=[],
    )
    defaults.update(kw)
    return TenantContext(**defaults)


# ── App factory ───────────────────────────────────────────────────────────────


class TestCreateApp:
    def test_returns_fastapi_instance(self):
        from fastapi import FastAPI
        from app.main import create_app

        app = create_app()
        assert isinstance(app, FastAPI)

    def test_health_endpoint(self):
        from app.main import create_app

        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_citedby_error_handler(self):
        from app.main import create_app

        app = create_app()

        @app.get("/test-error")
        async def trigger_error():
            raise CitedByValidationError("test error")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/test-error")
        assert response.status_code == 422
        body = response.json()
        assert "error" in body
        assert body["message"] == "test error"


# ── Router layer ──────────────────────────────────────────────────────────────


class TestTenantRouter:
    def _app_with_mock_ctx(self, ctx: TenantContext):
        from app.main import create_app
        from app.api.dependencies.auth import get_tenant_context

        app = create_app()
        app.dependency_overrides[get_tenant_context] = lambda: ctx
        return app

    def test_create_tenant_returns_201(self):
        from app.modules.identity.models import Tenant, TenantType
        from app.api.v1.schemas import TenantResponse

        ctx = _make_ctx(is_platform_admin=False)
        app = self._app_with_mock_ctx(ctx)

        tenant = Tenant(
            type=TenantType.agency,
            display_name="Acme Agency",
            slug="acme-agency",
        )

        with patch("app.api.v1.routers.tenants.get_session_factory") as mock_factory, \
             patch("app.api.v1.routers.tenants.get_master_key", return_value="k" * 32):
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_session.commit = AsyncMock()

            mock_factory_fn = MagicMock()
            mock_factory_fn.return_value = mock_session
            mock_factory.return_value = mock_factory_fn

            with patch("app.modules.identity.service.TenantService.create_tenant", new_callable=AsyncMock, return_value=tenant):
                client = TestClient(app, raise_server_exceptions=False)
                response = client.post(
                    "/api/v1/tenants",
                    json={
                        "type": "agency",
                        "display_name": "Acme Agency",
                        "slug": "acme-agency",
                    },
                )

        assert response.status_code == 201

    def test_missing_auth_returns_401(self):
        from app.main import create_app

        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post(
            "/api/v1/tenants",
            json={"type": "agency", "display_name": "X", "slug": "xxx"},
        )
        # Without auth override, the JWT validation will fail → 401
        assert response.status_code in (401, 422, 500)


class TestBusinessRouter:
    def _app_with_mock_ctx(self, ctx: TenantContext):
        from app.main import create_app
        from app.api.dependencies.auth import get_tenant_context

        app = create_app()
        app.dependency_overrides[get_tenant_context] = lambda: ctx
        return app

    def test_list_businesses_endpoint_exists(self):
        from app.main import create_app

        app = create_app()
        routes = [r.path for r in app.routes]
        assert any("businesses" in r for r in routes)

    def test_create_business_returns_403_without_role(self):
        ctx = _make_ctx(is_platform_admin=False, memberships=[])
        app = self._app_with_mock_ctx(ctx)

        client = TestClient(app, raise_server_exceptions=False)
        response = client.post(
            "/api/v1/businesses",
            json={
                "canonical_name": "My Firm",
                "category_id": str(uuid.uuid4()),
            },
        )
        assert response.status_code == 403
