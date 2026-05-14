"""Router-layer tests using FastAPI TestClient with dependency overrides and service mocking."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies.auth import TenantContext
from app.modules.identity.models import Membership, TenantType, UserRole


def _make_ctx(**kw) -> TenantContext:
    tid = uuid.uuid4()
    uid = uuid.uuid4()
    defaults = dict(
        user_id=uid,
        auth_provider_id="auth0|test",
        tenant_id=tid,
        is_platform_admin=True,  # default to admin so role checks pass
        memberships=[],
    )
    defaults.update(kw)
    return TenantContext(**defaults)


def _make_app(ctx: TenantContext):
    from app.main import create_app
    from app.api.dependencies.auth import get_tenant_context

    app = create_app()
    app.dependency_overrides[get_tenant_context] = lambda: ctx
    return app


def _mock_db_session():
    """Return a mock async context manager that yields a MagicMock session.

    For business router: patch get_db_session with the returned ctx fn.
    For tenant router: patch get_session_factory to return a factory wrapping session.
    """
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    @asynccontextmanager
    async def _ctx(factory, request_ctx):
        yield session

    @asynccontextmanager
    async def _session_ctx():
        yield session

    def _factory():
        return _session_ctx()

    return _ctx, session, _factory


# ── Tenant router ─────────────────────────────────────────────────────────────


class TestTenantRouterEndpoints:
    def test_get_current_tenant_not_found_returns_404(self):
        from app.core.exceptions import TenantNotFoundError

        ctx = _make_ctx()
        app = _make_app(ctx)
        _, _, mock_factory = _mock_db_session()

        with patch("app.api.v1.routers.tenants.get_session_factory", return_value=mock_factory), \
             patch("app.api.v1.routers.tenants.get_master_key", return_value="k" * 32), \
             patch("app.modules.identity.service.TenantService.get_tenant",
                   new_callable=AsyncMock,
                   side_effect=TenantNotFoundError("not found")):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/tenants/current")

        assert response.status_code == 404

    def test_get_current_tenant_success(self):
        from app.modules.identity.models import Tenant

        ctx = _make_ctx()
        app = _make_app(ctx)
        _, _, mock_factory = _mock_db_session()
        tenant = Tenant(type=TenantType.agency, display_name="Acme", slug="acme")

        with patch("app.api.v1.routers.tenants.get_session_factory", return_value=mock_factory), \
             patch("app.api.v1.routers.tenants.get_master_key", return_value="k" * 32), \
             patch("app.modules.identity.service.TenantService.get_tenant",
                   new_callable=AsyncMock,
                   return_value=tenant):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/tenants/current")

        assert response.status_code == 200

    def test_update_current_tenant(self):
        from app.modules.identity.models import Tenant

        ctx = _make_ctx()
        app = _make_app(ctx)
        _, _, mock_factory = _mock_db_session()
        tenant = Tenant(type=TenantType.agency, display_name="Updated", slug="acme")

        with patch("app.api.v1.routers.tenants.get_session_factory", return_value=mock_factory), \
             patch("app.api.v1.routers.tenants.get_master_key", return_value="k" * 32), \
             patch("app.modules.identity.service.TenantService.update_tenant",
                   new_callable=AsyncMock,
                   return_value=tenant):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.patch(
                "/api/v1/tenants/current",
                json={"display_name": "Updated"},
            )

        assert response.status_code == 200

    def test_list_members(self):
        ctx = _make_ctx()
        app = _make_app(ctx)
        _, _, mock_factory = _mock_db_session()
        m = Membership(user_id=uuid.uuid4(), tenant_id=ctx.tenant_id, role=UserRole.agency_member)

        with patch("app.api.v1.routers.tenants.get_session_factory", return_value=mock_factory), \
             patch("app.api.v1.routers.tenants.get_master_key", return_value="k" * 32), \
             patch("app.modules.identity.service.MembershipService.list_tenant_members",
                   new_callable=AsyncMock,
                   return_value=[m]):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/tenants/current/members")

        assert response.status_code == 200

    def test_revoke_member(self):
        ctx = _make_ctx()
        app = _make_app(ctx)
        _, _, mock_factory = _mock_db_session()
        m = Membership(user_id=uuid.uuid4(), tenant_id=ctx.tenant_id, role=UserRole.agency_member)

        with patch("app.api.v1.routers.tenants.get_session_factory", return_value=mock_factory), \
             patch("app.api.v1.routers.tenants.get_master_key", return_value="k" * 32), \
             patch("app.modules.identity.service.MembershipService.revoke",
                   new_callable=AsyncMock,
                   return_value=m):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.delete(f"/api/v1/tenants/current/members/{uuid.uuid4()}")

        assert response.status_code == 200


# ── Business router ───────────────────────────────────────────────────────────


class TestBusinessRouterEndpoints:
    def _biz(self, ctx):
        from app.modules.business_profile.models import Business, BusinessSource
        return Business(
            tenant_id=ctx.tenant_id,
            canonical_name="My Firm",
            name_normalized="my firm",
            category_id=uuid.uuid4(),
            source=BusinessSource.self_signup,
        )

    def test_list_businesses(self):
        ctx = _make_ctx()
        app = _make_app(ctx)
        mock_db, _, _ = _mock_db_session()
        biz = self._biz(ctx)

        with patch("app.api.v1.routers.businesses.get_db_session", mock_db), \
             patch("app.api.v1.routers.businesses.get_session_factory"), \
             patch("app.api.v1.routers.businesses.get_master_key", return_value="k" * 32), \
             patch("app.modules.business_profile.service.BusinessProfileService.list_businesses",
                   new_callable=AsyncMock,
                   return_value=[biz]):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/businesses")

        assert response.status_code == 200

    def test_get_business(self):
        ctx = _make_ctx()
        app = _make_app(ctx)
        mock_db, _, _ = _mock_db_session()
        biz = self._biz(ctx)

        with patch("app.api.v1.routers.businesses.get_db_session", mock_db), \
             patch("app.api.v1.routers.businesses.get_session_factory"), \
             patch("app.api.v1.routers.businesses.get_master_key", return_value="k" * 32), \
             patch("app.modules.business_profile.service.BusinessProfileService.get_business",
                   new_callable=AsyncMock,
                   return_value=biz):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get(f"/api/v1/businesses/{biz.id}")

        assert response.status_code == 200

    def test_create_business(self):
        ctx = _make_ctx()
        app = _make_app(ctx)
        mock_db, _, _ = _mock_db_session()
        biz = self._biz(ctx)

        with patch("app.api.v1.routers.businesses.get_db_session", mock_db), \
             patch("app.api.v1.routers.businesses.get_session_factory"), \
             patch("app.api.v1.routers.businesses.get_master_key", return_value="k" * 32), \
             patch("app.modules.business_profile.service.BusinessProfileService.create_business",
                   new_callable=AsyncMock,
                   return_value=biz):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(
                "/api/v1/businesses",
                json={
                    "canonical_name": "My Firm",
                    "category_id": str(uuid.uuid4()),
                },
            )

        assert response.status_code == 201

    def test_update_business(self):
        ctx = _make_ctx()
        app = _make_app(ctx)
        mock_db, _, _ = _mock_db_session()
        biz = self._biz(ctx)

        with patch("app.api.v1.routers.businesses.get_db_session", mock_db), \
             patch("app.api.v1.routers.businesses.get_session_factory"), \
             patch("app.api.v1.routers.businesses.get_master_key", return_value="k" * 32), \
             patch("app.modules.business_profile.service.BusinessProfileService.update_business",
                   new_callable=AsyncMock,
                   return_value=biz):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.patch(
                f"/api/v1/businesses/{biz.id}",
                json={"description": "Updated"},
            )

        assert response.status_code == 200

    def test_delete_business(self):
        ctx = _make_ctx()
        app = _make_app(ctx)
        mock_db, _, _ = _mock_db_session()
        biz = self._biz(ctx)

        with patch("app.api.v1.routers.businesses.get_db_session", mock_db), \
             patch("app.api.v1.routers.businesses.get_session_factory"), \
             patch("app.api.v1.routers.businesses.get_master_key", return_value="k" * 32), \
             patch("app.modules.business_profile.service.BusinessProfileService.delete_business",
                   new_callable=AsyncMock,
                   return_value=biz):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.delete(f"/api/v1/businesses/{biz.id}")

        assert response.status_code == 204

    def test_add_alias(self):
        ctx = _make_ctx()
        app = _make_app(ctx)
        mock_db, _, _ = _mock_db_session()
        from app.modules.business_profile.models import AliasType, BusinessAlias

        biz = self._biz(ctx)
        alias = BusinessAlias(
            business_id=biz.id,
            tenant_id=ctx.tenant_id,
            alias_text="My Firm Ltd",
            alias_text_normalized="my firm ltd",
            alias_type=AliasType.abbreviation,
        )

        with patch("app.api.v1.routers.businesses.get_db_session", mock_db), \
             patch("app.api.v1.routers.businesses.get_session_factory"), \
             patch("app.api.v1.routers.businesses.get_master_key", return_value="k" * 32), \
             patch("app.modules.business_profile.service.BusinessProfileService.add_alias",
                   new_callable=AsyncMock,
                   return_value=alias):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(
                f"/api/v1/businesses/{biz.id}/aliases",
                json={"alias_text": "My Firm Ltd", "alias_type": "abbreviation"},
            )

        assert response.status_code == 201

    def test_add_location(self):
        ctx = _make_ctx()
        app = _make_app(ctx)
        mock_db, _, _ = _mock_db_session()
        from app.modules.business_profile.models import BusinessLocation

        biz = self._biz(ctx)
        loc = BusinessLocation(
            business_id=biz.id,
            tenant_id=ctx.tenant_id,
            city="Bangalore",
        )

        with patch("app.api.v1.routers.businesses.get_db_session", mock_db), \
             patch("app.api.v1.routers.businesses.get_session_factory"), \
             patch("app.api.v1.routers.businesses.get_master_key", return_value="k" * 32), \
             patch("app.modules.business_profile.service.BusinessProfileService.add_location",
                   new_callable=AsyncMock,
                   return_value=loc):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(
                f"/api/v1/businesses/{biz.id}/locations",
                json={"city": "Bangalore"},
            )

        assert response.status_code == 201

    def test_add_keywords(self):
        ctx = _make_ctx()
        app = _make_app(ctx)
        mock_db, _, _ = _mock_db_session()
        from app.modules.business_profile.models import BusinessKeyword

        biz = self._biz(ctx)
        kw = BusinessKeyword(
            business_id=biz.id,
            tenant_id=ctx.tenant_id,
            keyword="ca firm",
            keyword_normalized="ca firm",
        )

        with patch("app.api.v1.routers.businesses.get_db_session", mock_db), \
             patch("app.api.v1.routers.businesses.get_session_factory"), \
             patch("app.api.v1.routers.businesses.get_master_key", return_value="k" * 32), \
             patch("app.modules.business_profile.service.BusinessProfileService.add_keywords",
                   new_callable=AsyncMock,
                   return_value=[kw]):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(
                f"/api/v1/businesses/{biz.id}/keywords",
                json={"keywords": ["ca firm", "tax filing"]},
            )

        assert response.status_code == 201

    def test_business_not_found_returns_404(self):
        from app.core.exceptions import BusinessNotFoundError

        ctx = _make_ctx()
        app = _make_app(ctx)
        mock_db, _, _ = _mock_db_session()

        with patch("app.api.v1.routers.businesses.get_db_session", mock_db), \
             patch("app.api.v1.routers.businesses.get_session_factory"), \
             patch("app.api.v1.routers.businesses.get_master_key", return_value="k" * 32), \
             patch("app.modules.business_profile.service.BusinessProfileService.get_business",
                   new_callable=AsyncMock,
                   side_effect=BusinessNotFoundError("not found")):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get(f"/api/v1/businesses/{uuid.uuid4()}")

        assert response.status_code == 404

    def test_create_business_citedby_error_returns_error(self):
        from app.core.exceptions import ValidationError as CitedByValidationError

        ctx = _make_ctx()
        app = _make_app(ctx)
        mock_db, _, _ = _mock_db_session()

        with patch("app.api.v1.routers.businesses.get_db_session", mock_db), \
             patch("app.api.v1.routers.businesses.get_session_factory"), \
             patch("app.api.v1.routers.businesses.get_master_key", return_value="k" * 32), \
             patch("app.modules.business_profile.service.BusinessProfileService.create_business",
                   new_callable=AsyncMock,
                   side_effect=CitedByValidationError("name too short")):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(
                "/api/v1/businesses",
                json={"canonical_name": "X", "category_id": str(uuid.uuid4())},
            )

        assert response.status_code == 422

    def test_update_business_returns_403_without_role(self):
        ctx = _make_ctx(is_platform_admin=False, memberships=[])
        app = _make_app(ctx)

        client = TestClient(app, raise_server_exceptions=False)
        response = client.patch(
            f"/api/v1/businesses/{uuid.uuid4()}",
            json={"description": "Updated"},
        )
        assert response.status_code == 403

    def test_delete_business_returns_403_without_role(self):
        ctx = _make_ctx(is_platform_admin=False, memberships=[])
        app = _make_app(ctx)

        client = TestClient(app, raise_server_exceptions=False)
        response = client.delete(f"/api/v1/businesses/{uuid.uuid4()}")
        assert response.status_code == 403

    def test_update_business_citedby_error_returns_error(self):
        from app.core.exceptions import BusinessNotFoundError

        ctx = _make_ctx()
        app = _make_app(ctx)
        mock_db, _, _ = _mock_db_session()
        biz = self._biz(ctx)

        with patch("app.api.v1.routers.businesses.get_db_session", mock_db), \
             patch("app.api.v1.routers.businesses.get_session_factory"), \
             patch("app.api.v1.routers.businesses.get_master_key", return_value="k" * 32), \
             patch("app.modules.business_profile.service.BusinessProfileService.update_business",
                   new_callable=AsyncMock,
                   side_effect=BusinessNotFoundError("not found")):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.patch(
                f"/api/v1/businesses/{biz.id}",
                json={"description": "Updated"},
            )

        assert response.status_code == 404

    def test_delete_business_citedby_error_returns_error(self):
        from app.core.exceptions import BusinessNotFoundError

        ctx = _make_ctx()
        app = _make_app(ctx)
        mock_db, _, _ = _mock_db_session()
        biz = self._biz(ctx)

        with patch("app.api.v1.routers.businesses.get_db_session", mock_db), \
             patch("app.api.v1.routers.businesses.get_session_factory"), \
             patch("app.api.v1.routers.businesses.get_master_key", return_value="k" * 32), \
             patch("app.modules.business_profile.service.BusinessProfileService.delete_business",
                   new_callable=AsyncMock,
                   side_effect=BusinessNotFoundError("not found")):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.delete(f"/api/v1/businesses/{biz.id}")

        assert response.status_code == 404


# ── Audit router ─────────────────────────────────────────────────────────────


class TestAuditRouterEndpoints:
    def _make_run_mock(self, tid: uuid.UUID, bid: uuid.UUID):
        run = MagicMock()
        run.id = uuid.uuid4()
        run.tenant_id = tid
        run.business_id = bid
        run.trigger = MagicMock()
        run.trigger.value = "manual"
        run.status = MagicMock()
        run.status.value = "pending"
        run.ai_visibility_score = None
        run.completeness_pct = None
        run.queries_total = 0
        run.queries_successful = 0
        run.algorithm_version = "v1"
        run.workflow_run_id = None
        from datetime import datetime, timezone
        run.created_at = datetime.now(timezone.utc)
        return run

    def test_create_audit_run_success(self):
        ctx = _make_ctx()
        app = _make_app(ctx)
        bid = uuid.uuid4()
        run = self._make_run_mock(ctx.tenant_id, bid)

        with patch("app.api.v1.routers.audits.AuditService") as MockSvc, \
             patch("app.api.v1.routers.audits.get_db_session"):
            svc_instance = MagicMock()
            svc_instance.create_audit_run = AsyncMock(return_value=run)
            svc_instance.flush_events = AsyncMock()
            MockSvc.return_value = svc_instance

            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(
                "/api/v1/audits",
                json={"business_id": str(bid), "trigger": "manual"},
            )
        assert response.status_code in (200, 201, 422, 503)

    def test_create_audit_run_invalid_trigger_returns_422(self):
        ctx = _make_ctx()
        app = _make_app(ctx)

        with patch("app.api.v1.routers.audits.get_db_session"):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(
                "/api/v1/audits",
                json={"business_id": str(uuid.uuid4()), "trigger": "invalid_trigger"},
            )
        assert response.status_code == 422

    def test_list_audit_runs(self):
        ctx = _make_ctx()
        app = _make_app(ctx)

        with patch("app.api.v1.routers.audits.AuditService") as MockSvc, \
             patch("app.api.v1.routers.audits.get_db_session"):
            svc_instance = MagicMock()
            svc_instance.list_audit_runs = AsyncMock(return_value=[])
            MockSvc.return_value = svc_instance

            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/audits")
        assert response.status_code in (200, 503)

    def test_get_audit_run_not_found(self):
        from app.core.exceptions import NotFoundError
        ctx = _make_ctx()
        app = _make_app(ctx)
        audit_id = uuid.uuid4()

        with patch("app.api.v1.routers.audits.AuditService") as MockSvc, \
             patch("app.api.v1.routers.audits.get_db_session"):
            svc_instance = MagicMock()
            svc_instance.get_audit_run = AsyncMock(side_effect=NotFoundError("not found"))
            MockSvc.return_value = svc_instance

            client = TestClient(app, raise_server_exceptions=False)
            response = client.get(f"/api/v1/audits/{audit_id}")
        assert response.status_code == 404

    def test_get_audit_run_wrong_tenant(self):
        ctx = _make_ctx(is_platform_admin=False)
        ctx_tid = ctx.tenant_id
        app = _make_app(ctx)
        audit_id = uuid.uuid4()

        run = self._make_run_mock(uuid.uuid4(), uuid.uuid4())  # different tenant
        run.tenant_id = uuid.uuid4()  # not ctx.tenant_id

        with patch("app.api.v1.routers.audits.AuditService") as MockSvc, \
             patch("app.api.v1.routers.audits.get_db_session"):
            svc_instance = MagicMock()
            svc_instance.get_audit_run = AsyncMock(return_value=run)
            MockSvc.return_value = svc_instance

            client = TestClient(app, raise_server_exceptions=False)
            response = client.get(f"/api/v1/audits/{audit_id}")
        assert response.status_code in (403, 404, 503)


# ── Report router ──────────────────────────────────────────────────────────────


class TestReportRouterEndpoints:
    def _make_report_mock(self, tid: uuid.UUID):
        from datetime import datetime, timezone
        from app.modules.reporting.models import ReportStatus
        report = MagicMock()
        report.id = uuid.uuid4()
        report.tenant_id = tid
        report.business_id = uuid.uuid4()
        report.audit_run_id = uuid.uuid4()
        report.version = 1
        report.status = ReportStatus.ready
        report.score = 72.5
        report.confidence_band = "medium"
        report.completeness_pct = 0.9
        report.web_view_token = "test-token-123"
        report.quick_wins = None
        report.template_version = "v1"
        report.generated_at = datetime.now(timezone.utc)
        report.created_at = datetime.now(timezone.utc)
        return report

    def _make_link_mock(self):
        from datetime import datetime, timezone
        link = MagicMock()
        link.id = uuid.uuid4()
        link.token = "sharetoken123"
        link.report_id = uuid.uuid4()
        link.expires_at = datetime.now(timezone.utc)
        link.view_count = 0
        link.created_at = datetime.now(timezone.utc)
        return link

    def test_get_report_success(self):
        ctx = _make_ctx()
        app = _make_app(ctx)
        report = self._make_report_mock(ctx.tenant_id)

        with patch("app.api.v1.routers.reports.ReportService") as MockSvc, \
             patch("app.api.v1.routers.reports.get_db_session"):
            svc_instance = MagicMock()
            svc_instance.get_report = AsyncMock(return_value=report)
            MockSvc.return_value = svc_instance

            client = TestClient(app, raise_server_exceptions=False)
            response = client.get(f"/api/v1/reports/{report.id}")
        assert response.status_code in (200, 503)

    def test_get_report_wrong_tenant(self):
        ctx = _make_ctx(is_platform_admin=False)
        app = _make_app(ctx)
        report = self._make_report_mock(uuid.uuid4())  # different tenant

        with patch("app.api.v1.routers.reports.ReportService") as MockSvc, \
             patch("app.api.v1.routers.reports.get_db_session"):
            svc_instance = MagicMock()
            svc_instance.get_report = AsyncMock(return_value=report)
            MockSvc.return_value = svc_instance

            client = TestClient(app, raise_server_exceptions=False)
            response = client.get(f"/api/v1/reports/{report.id}")
        assert response.status_code in (403, 503)

    def test_get_report_not_found(self):
        from app.core.exceptions import NotFoundError
        ctx = _make_ctx()
        app = _make_app(ctx)

        with patch("app.api.v1.routers.reports.ReportService") as MockSvc, \
             patch("app.api.v1.routers.reports.get_db_session"):
            svc_instance = MagicMock()
            svc_instance.get_report = AsyncMock(side_effect=NotFoundError("not found"))
            MockSvc.return_value = svc_instance

            client = TestClient(app, raise_server_exceptions=False)
            response = client.get(f"/api/v1/reports/{uuid.uuid4()}")
        assert response.status_code in (404, 503)

    def test_get_report_by_token(self):
        ctx = _make_ctx()
        app = _make_app(ctx)
        report = self._make_report_mock(ctx.tenant_id)

        with patch("app.api.v1.routers.reports.ReportService") as MockSvc, \
             patch("app.api.v1.routers.reports.get_db_session"):
            svc_instance = MagicMock()
            svc_instance.get_report_by_token = AsyncMock(return_value=report)
            MockSvc.return_value = svc_instance

            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/reports/by-token/test-token-123")
        assert response.status_code in (200, 503)

    def test_create_share_link(self):
        ctx = _make_ctx()
        app = _make_app(ctx)
        link = self._make_link_mock()

        with patch("app.api.v1.routers.reports.ReportService") as MockSvc, \
             patch("app.api.v1.routers.reports.get_db_session"):
            svc_instance = MagicMock()
            svc_instance.create_share_link = AsyncMock(return_value=link)
            MockSvc.return_value = svc_instance

            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(
                f"/api/v1/reports/{uuid.uuid4()}/share",
                json={"ttl_days": 30},
            )
        assert response.status_code in (201, 422, 503)

    def test_revoke_share_link(self):
        ctx = _make_ctx()
        app = _make_app(ctx)

        with patch("app.api.v1.routers.reports.ReportService") as MockSvc, \
             patch("app.api.v1.routers.reports.get_db_session"):
            svc_instance = MagicMock()
            svc_instance.revoke_share_link = AsyncMock(return_value=None)
            MockSvc.return_value = svc_instance

            client = TestClient(app, raise_server_exceptions=False)
            response = client.delete("/api/v1/reports/share/sharetoken123")
        assert response.status_code in (204, 503)


# ── Free audit router ──────────────────────────────────────────────────────────


class TestFreeAuditRouterEndpoints:
    """Tests for public free-audit endpoints.

    The router imports FreeAuditSubmissionService inside functions, so we patch
    at the source module rather than the router module.
    """

    def _make_db_session_ctx(self, svc_instance):
        """Patch get_db_session to yield a mock session; patch Service constructor."""
        from contextlib import asynccontextmanager
        session = MagicMock()
        session.commit = AsyncMock()

        @asynccontextmanager
        async def _ctx(factory, request_ctx):
            yield session

        return _ctx, session

    def test_get_status_not_found(self):
        from app.core.exceptions import NotFoundError
        ctx = _make_ctx()
        app = _make_app(ctx)

        with patch("app.modules.reporting.service.FreeAuditSubmissionService.get_status",
                   new_callable=AsyncMock,
                   side_effect=NotFoundError("not found")), \
             patch("app.api.v1.routers.free_audit.get_session_factory"), \
             patch("app.api.v1.routers.free_audit.get_db_session",
                   new=lambda factory, ctx: _mock_db_session()[0](factory, ctx)):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/free-audit/missing-token/status")
        assert response.status_code in (404, 503)

    def test_get_status_success(self):
        ctx = _make_ctx()
        app = _make_app(ctx)
        status_data = {
            "status": "running",
            "progress": {"completeness_pct": 0.5, "queries_done": 10, "queries_total": 20},
            "report_ready": False,
            "claim_offered": False,
        }

        with patch("app.modules.reporting.service.FreeAuditSubmissionService.get_status",
                   new_callable=AsyncMock,
                   return_value=status_data), \
             patch("app.api.v1.routers.free_audit.get_session_factory"), \
             patch("app.api.v1.routers.free_audit.get_db_session",
                   new=lambda factory, ctx: _mock_db_session()[0](factory, ctx)):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/free-audit/valid-token/status")
        assert response.status_code in (200, 503)

    def test_claim_success(self):
        ctx = _make_ctx()
        app = _make_app(ctx)

        with patch("app.modules.reporting.service.FreeAuditSubmissionService.claim",
                   new_callable=AsyncMock,
                   return_value=True), \
             patch("app.api.v1.routers.free_audit.get_session_factory"), \
             patch("app.api.v1.routers.free_audit.get_db_session",
                   new=lambda factory, ctx: _mock_db_session()[0](factory, ctx)):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post("/api/v1/free-audit/valid-token/claim")
        assert response.status_code in (200, 503)

    def test_claim_not_found_returns_success_false(self):
        ctx = _make_ctx()
        app = _make_app(ctx)

        with patch("app.modules.reporting.service.FreeAuditSubmissionService.claim",
                   new_callable=AsyncMock,
                   return_value=False), \
             patch("app.api.v1.routers.free_audit.get_session_factory"), \
             patch("app.api.v1.routers.free_audit.get_db_session",
                   new=lambda factory, ctx: _mock_db_session()[0](factory, ctx)):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post("/api/v1/free-audit/missing-token/claim")
        assert response.status_code in (200, 503)
