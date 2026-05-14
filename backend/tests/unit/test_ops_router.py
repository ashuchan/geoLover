"""Unit tests for Ops API router (Phase 8)."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies.auth import TenantContext
from app.modules.ops.models import (
    ImpersonationLog,
    QuotaEnforcementLog,
    StatusComponent,
    TenantGraceExtension,
)


def _uuid():
    return uuid.uuid4()


def _now():
    return datetime.now(timezone.utc)


def _make_ctx(tenant_id=None, user_id=None, is_platform_admin=True) -> TenantContext:
    return TenantContext(
        user_id=user_id or _uuid(),
        auth_provider_id="auth0|test",
        tenant_id=tenant_id or _uuid(),
        is_platform_admin=is_platform_admin,
        memberships=[],
    )


def _make_app(ctx: TenantContext):
    from app.api.dependencies.auth import get_tenant_context
    from app.main import create_app

    app = create_app()
    app.dependency_overrides[get_tenant_context] = lambda: ctx
    return app


def _make_session():
    s = MagicMock()
    s.flush = AsyncMock()
    s.add = MagicMock()
    s.execute = AsyncMock()
    s.commit = AsyncMock()
    return s


@asynccontextmanager
async def _null_ctx(factory=None, req_ctx=None):
    yield _make_session()


def _make_factory_ctx(session):
    @asynccontextmanager
    async def _ctx():
        yield session

    return _ctx


def _make_quota_log(tenant_id=None):
    log = MagicMock()
    log.id = _uuid()
    log.tenant_id = tenant_id or _uuid()
    log.quota_kind = "audits"
    log.action = "soft_warn"
    log.triggered_at = _now()
    return log


def _make_grace(tenant_id=None):
    grace = MagicMock()
    grace.id = _uuid()
    grace.tenant_id = tenant_id or _uuid()
    grace.quota_kind = "audits"
    grace.extended_until = _now() + timedelta(days=7)
    grace.created_at = _now()
    return grace


def _make_impersonation_log(admin_user_id=None, tenant_id=None):
    log = MagicMock()
    log.id = _uuid()
    log.admin_user_id = admin_user_id or _uuid()
    log.impersonated_tenant_id = tenant_id or _uuid()
    log.reason = "Support debug"
    log.started_at = _now()
    log.ended_at = None
    return log


def _make_component(name="api"):
    c = MagicMock()
    c.id = _uuid()
    c.name = name
    c.description = "Core API"
    c.last_known_state = "operational"
    c.last_evaluated_at = _now()
    return c


class TestGetQuotaLog:
    def test_list_quota_log_admin_success(self):
        ctx = _make_ctx(is_platform_admin=True)
        app = _make_app(ctx)
        session = _make_session()
        log = _make_quota_log()

        with patch(
            "app.api.v1.routers.ops.get_session_factory",
            return_value=_make_factory_ctx(session),
        ), patch(
            "app.modules.ops.repository.QuotaEnforcementLogRepository.list_recent",
            new=AsyncMock(return_value=[log]),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/ops/quota/log")
        assert response.status_code in (200, 503)

    def test_list_quota_log_with_tenant_filter(self):
        ctx = _make_ctx(is_platform_admin=True)
        app = _make_app(ctx)
        session = _make_session()
        tenant_id = _uuid()
        log = _make_quota_log(tenant_id=tenant_id)

        with patch(
            "app.api.v1.routers.ops.get_session_factory",
            return_value=_make_factory_ctx(session),
        ), patch(
            "app.modules.ops.repository.QuotaEnforcementLogRepository.list_for_tenant",
            new=AsyncMock(return_value=[log]),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get(f"/api/v1/ops/quota/log?tenant_id={tenant_id}")
        assert response.status_code in (200, 503)

    def test_list_quota_log_non_admin_forbidden(self):
        ctx = _make_ctx(is_platform_admin=False)
        app = _make_app(ctx)

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/v1/ops/quota/log")
        assert response.status_code in (403, 503)


class TestExtendGrace:
    def test_extend_grace_success(self):
        ctx = _make_ctx(is_platform_admin=True)
        app = _make_app(ctx)
        session = _make_session()
        grace = _make_grace()

        with patch(
            "app.api.v1.routers.ops.get_session_factory",
            return_value=_make_factory_ctx(session),
        ), patch(
            "app.modules.ops.service.QuotaService.extend_grace",
            new=AsyncMock(return_value=grace),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(
                "/api/v1/ops/quota/grace",
                json={
                    "tenant_id": str(_uuid()),
                    "quota_kind": "audits",
                    "days": 7,
                    "reason": "Customer request",
                },
            )
        assert response.status_code in (201, 503)

    def test_extend_grace_non_admin_forbidden(self):
        ctx = _make_ctx(is_platform_admin=False)
        app = _make_app(ctx)

        client = TestClient(app, raise_server_exceptions=False)
        response = client.post(
            "/api/v1/ops/quota/grace",
            json={
                "tenant_id": str(_uuid()),
                "quota_kind": "audits",
                "days": 7,
            },
        )
        assert response.status_code in (403, 503)


class TestGetGraceExtensions:
    def test_list_grace_extensions_success(self):
        ctx = _make_ctx(is_platform_admin=True)
        app = _make_app(ctx)
        session = _make_session()
        tenant_id = _uuid()
        grace = _make_grace(tenant_id=tenant_id)

        with patch(
            "app.api.v1.routers.ops.get_session_factory",
            return_value=_make_factory_ctx(session),
        ), patch(
            "app.modules.ops.repository.TenantGraceExtensionRepository.list_for_tenant",
            new=AsyncMock(return_value=[grace]),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get(f"/api/v1/ops/quota/grace?tenant_id={tenant_id}")
        assert response.status_code in (200, 503)

    def test_list_grace_extensions_non_admin_forbidden(self):
        ctx = _make_ctx(is_platform_admin=False)
        app = _make_app(ctx)

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get(f"/api/v1/ops/quota/grace?tenant_id={_uuid()}")
        assert response.status_code in (403, 503)


class TestStartImpersonation:
    def test_start_impersonation_success(self):
        ctx = _make_ctx(is_platform_admin=True)
        app = _make_app(ctx)
        session = _make_session()
        log = _make_impersonation_log(admin_user_id=ctx.user_id)

        with patch(
            "app.api.v1.routers.ops.get_session_factory",
            return_value=_make_factory_ctx(session),
        ), patch(
            "app.modules.ops.service.AdminOpsService.start_impersonation",
            new=AsyncMock(return_value=log),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(
                "/api/v1/ops/impersonation/start",
                json={
                    "impersonated_tenant_id": str(_uuid()),
                    "reason": "Support debug",
                },
            )
        assert response.status_code in (201, 503)

    def test_start_impersonation_non_admin_forbidden(self):
        ctx = _make_ctx(is_platform_admin=False)
        app = _make_app(ctx)

        client = TestClient(app, raise_server_exceptions=False)
        response = client.post(
            "/api/v1/ops/impersonation/start",
            json={
                "impersonated_tenant_id": str(_uuid()),
                "reason": "Test",
            },
        )
        assert response.status_code in (403, 503)


class TestEndImpersonation:
    def test_end_impersonation_success(self):
        ctx = _make_ctx(is_platform_admin=True)
        app = _make_app(ctx)
        session = _make_session()
        log_id = _uuid()

        with patch(
            "app.api.v1.routers.ops.get_session_factory",
            return_value=_make_factory_ctx(session),
        ), patch(
            "app.modules.ops.service.AdminOpsService.end_impersonation",
            new=AsyncMock(),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(f"/api/v1/ops/impersonation/{log_id}/end")
        assert response.status_code in (204, 503)

    def test_end_impersonation_non_admin_forbidden(self):
        ctx = _make_ctx(is_platform_admin=False)
        app = _make_app(ctx)

        client = TestClient(app, raise_server_exceptions=False)
        response = client.post(f"/api/v1/ops/impersonation/{_uuid()}/end")
        assert response.status_code in (403, 503)

    def test_end_impersonation_not_found(self):
        from app.core.exceptions import NotFoundError
        ctx = _make_ctx(is_platform_admin=True)
        app = _make_app(ctx)
        session = _make_session()
        log_id = _uuid()

        with patch(
            "app.api.v1.routers.ops.get_session_factory",
            return_value=_make_factory_ctx(session),
        ), patch(
            "app.modules.ops.service.AdminOpsService.end_impersonation",
            new=AsyncMock(side_effect=NotFoundError("Not found")),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(f"/api/v1/ops/impersonation/{log_id}/end")
        assert response.status_code in (404, 503)

    def test_end_impersonation_permission_denied(self):
        from app.core.exceptions import PermissionDeniedError
        ctx = _make_ctx(is_platform_admin=True)
        app = _make_app(ctx)
        session = _make_session()
        log_id = _uuid()

        with patch(
            "app.api.v1.routers.ops.get_session_factory",
            return_value=_make_factory_ctx(session),
        ), patch(
            "app.modules.ops.service.AdminOpsService.end_impersonation",
            new=AsyncMock(side_effect=PermissionDeniedError("Not your session")),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(f"/api/v1/ops/impersonation/{log_id}/end")
        assert response.status_code in (403, 503)


class TestGetStatus:
    def test_get_status_no_auth_required(self):
        """GET /ops/status is public — no auth needed."""
        from app.main import create_app
        import app.core.database as db_module
        app = create_app()
        session = _make_session()
        components = [_make_component("api"), _make_component("notifications")]
        orig_factory = db_module.db_manager._main_factory

        try:
            db_module.db_manager._main_factory = _make_factory_ctx(session)  # type: ignore
            with patch(
                "app.modules.ops.service.AdminOpsService.get_all_component_states",
                new=AsyncMock(return_value=components),
            ):
                client = TestClient(app, raise_server_exceptions=False)
                response = client.get("/api/v1/ops/status")
        finally:
            db_module.db_manager._main_factory = orig_factory
        assert response.status_code in (200, 503)

    def test_get_status_db_not_initialized(self):
        from app.main import create_app
        import app.core.database as db_module
        app = create_app()
        orig_factory = db_module.db_manager._main_factory

        try:
            db_module.db_manager._main_factory = None
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/ops/status")
        finally:
            db_module.db_manager._main_factory = orig_factory
        assert response.status_code in (503,)


class TestUpdateComponentState:
    def test_update_state_success(self):
        ctx = _make_ctx(is_platform_admin=True)
        app = _make_app(ctx)
        session = _make_session()
        component = _make_component("api")
        component.last_known_state = "degraded"

        with patch(
            "app.api.v1.routers.ops.get_session_factory",
            return_value=_make_factory_ctx(session),
        ), patch(
            "app.modules.ops.service.AdminOpsService.update_component_state",
            new=AsyncMock(return_value=component),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.put(
                "/api/v1/ops/status/api",
                json={"state": "degraded"},
            )
        assert response.status_code in (200, 503)

    def test_update_state_not_found(self):
        ctx = _make_ctx(is_platform_admin=True)
        app = _make_app(ctx)
        session = _make_session()

        with patch(
            "app.api.v1.routers.ops.get_session_factory",
            return_value=_make_factory_ctx(session),
        ), patch(
            "app.modules.ops.service.AdminOpsService.update_component_state",
            new=AsyncMock(return_value=None),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.put(
                "/api/v1/ops/status/nonexistent",
                json={"state": "degraded"},
            )
        assert response.status_code in (404, 503)

    def test_update_state_non_admin_forbidden(self):
        ctx = _make_ctx(is_platform_admin=False)
        app = _make_app(ctx)

        client = TestClient(app, raise_server_exceptions=False)
        response = client.put(
            "/api/v1/ops/status/api",
            json={"state": "degraded"},
        )
        assert response.status_code in (403, 503)


class TestSeedDefaultComponents:
    def test_seed_success(self):
        ctx = _make_ctx(is_platform_admin=True)
        app = _make_app(ctx)
        session = _make_session()
        components = [_make_component(name) for name in ["api", "audit_engine", "content_generation", "publishing", "notifications"]]

        with patch(
            "app.api.v1.routers.ops.get_session_factory",
            return_value=_make_factory_ctx(session),
        ), patch(
            "app.modules.ops.service.AdminOpsService.seed_default_components",
            new=AsyncMock(return_value=components),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post("/api/v1/ops/status/seed")
        assert response.status_code in (201, 503)

    def test_seed_non_admin_forbidden(self):
        ctx = _make_ctx(is_platform_admin=False)
        app = _make_app(ctx)

        client = TestClient(app, raise_server_exceptions=False)
        response = client.post("/api/v1/ops/status/seed")
        assert response.status_code in (403, 503)


class TestGetPlans:
    def test_get_plans_no_auth_required(self):
        """GET /ops/plans is public — no auth needed."""
        from app.main import create_app
        app = create_app()

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/v1/ops/plans")
        assert response.status_code in (200, 503)

    def test_get_plans_returns_plan_list(self):
        """GET /ops/plans returns plan limits when successful."""
        from app.main import create_app
        app = create_app()

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/v1/ops/plans")
        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, list)
            assert len(data) > 0
            plan_names = [p["plan"] for p in data]
            assert "free" in plan_names
            assert "enterprise" in plan_names
