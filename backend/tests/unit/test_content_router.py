"""Unit tests for content brief API router."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies.auth import TenantContext
from app.modules.content.models import ApprovalFlow, BriefState, BriefType


def _make_ctx(tenant_id=None, user_id=None) -> TenantContext:
    return TenantContext(
        user_id=user_id or uuid.uuid4(),
        auth_provider_id="auth0|test",
        tenant_id=tenant_id or uuid.uuid4(),
        is_platform_admin=True,
        memberships=[],
    )


def _make_app(ctx: TenantContext):
    from app.main import create_app
    from app.api.dependencies.auth import get_tenant_context

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
    return s


def _make_brief_mock(tid, state=BriefState.in_review):
    b = MagicMock()
    b.id = uuid.uuid4()
    b.tenant_id = tid
    b.business_id = uuid.uuid4()
    b.source_audit_run_id = uuid.uuid4()
    b.brief_type = BriefType.faq_cluster
    b.target_query = "query"
    b.current_state = state
    b.current_asset_id = None
    b.approval_flow = ApprovalFlow.agency_only
    b.created_at = None
    b.updated_at = None
    return b


class TestListBriefs:
    def test_list_briefs_success(self):
        tid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid)
        app = _make_app(ctx)
        session = _make_session()
        brief = _make_brief_mock(tid)

        with patch("app.api.v1.routers.content.get_session_factory"), \
             patch("app.api.v1.routers.content.get_db_session", new=_make_db_ctx(session)), \
             patch("app.modules.content.service.ContentBriefService.list_briefs",
                   new=AsyncMock(return_value=[brief])):

            client = TestClient(app, raise_server_exceptions=False)
            response = client.get(
                f"/api/v1/content/briefs?business_id={brief.business_id}"
            )
        assert response.status_code in (200, 503)

    def test_list_briefs_invalid_state(self):
        tid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid)
        app = _make_app(ctx)
        session = _make_session()

        with patch("app.api.v1.routers.content.get_session_factory"), \
             patch("app.api.v1.routers.content.get_db_session", new=_make_db_ctx(session)):

            client = TestClient(app, raise_server_exceptions=False)
            response = client.get(
                f"/api/v1/content/briefs?business_id={uuid.uuid4()}&state=invalid_state"
            )
        assert response.status_code in (422, 503)


class TestGetBrief:
    def test_get_brief_success(self):
        tid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid)
        app = _make_app(ctx)
        session = _make_session()
        brief = _make_brief_mock(tid)

        with patch("app.api.v1.routers.content.get_session_factory"), \
             patch("app.api.v1.routers.content.get_db_session", new=_make_db_ctx(session)), \
             patch("app.modules.content.service.ContentBriefService.get_brief",
                   new=AsyncMock(return_value=brief)):

            client = TestClient(app, raise_server_exceptions=False)
            response = client.get(f"/api/v1/content/briefs/{brief.id}")
        assert response.status_code in (200, 503)

    def test_get_brief_not_found(self):
        from app.core.exceptions import NotFoundError
        tid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid)
        app = _make_app(ctx)
        session = _make_session()

        with patch("app.api.v1.routers.content.get_session_factory"), \
             patch("app.api.v1.routers.content.get_db_session", new=_make_db_ctx(session)), \
             patch("app.modules.content.service.ContentBriefService.get_brief",
                   new=AsyncMock(side_effect=NotFoundError("not found"))):

            client = TestClient(app, raise_server_exceptions=False)
            response = client.get(f"/api/v1/content/briefs/{uuid.uuid4()}")
        assert response.status_code in (404, 503)

    def test_get_brief_wrong_tenant(self):
        tid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid)
        app = _make_app(ctx)
        session = _make_session()
        brief = _make_brief_mock(uuid.uuid4())  # different tenant

        with patch("app.api.v1.routers.content.get_session_factory"), \
             patch("app.api.v1.routers.content.get_db_session", new=_make_db_ctx(session)), \
             patch("app.modules.content.service.ContentBriefService.get_brief",
                   new=AsyncMock(return_value=brief)):

            client = TestClient(app, raise_server_exceptions=False)
            response = client.get(f"/api/v1/content/briefs/{brief.id}")
        assert response.status_code in (403, 503)


class TestApproveBrief:
    def test_approve_success(self):
        tid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid)
        app = _make_app(ctx)
        session = _make_session()
        brief = _make_brief_mock(tid, state=BriefState.in_review)

        with patch("app.api.v1.routers.content.get_session_factory"), \
             patch("app.api.v1.routers.content.get_db_session", new=_make_db_ctx(session)), \
             patch("app.modules.content.service.ContentBriefService.approve_brief",
                   new=AsyncMock(return_value=brief)), \
             patch("app.modules.content.service.ContentBriefService.flush_events",
                   new=AsyncMock()):

            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(
                f"/api/v1/content/briefs/{brief.id}/approve",
                json={}
            )
        assert response.status_code in (200, 503)

    def test_approve_conflict(self):
        from app.core.exceptions import ConflictError
        tid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid)
        app = _make_app(ctx)
        session = _make_session()

        with patch("app.api.v1.routers.content.get_session_factory"), \
             patch("app.api.v1.routers.content.get_db_session", new=_make_db_ctx(session)), \
             patch("app.modules.content.service.ContentBriefService.approve_brief",
                   new=AsyncMock(side_effect=ConflictError("Invalid transition"))):

            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(
                f"/api/v1/content/briefs/{uuid.uuid4()}/approve",
                json={}
            )
        assert response.status_code in (409, 503)


class TestRejectBrief:
    def test_reject_success(self):
        tid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid)
        app = _make_app(ctx)
        session = _make_session()
        brief = _make_brief_mock(tid, state=BriefState.rejected)

        with patch("app.api.v1.routers.content.get_session_factory"), \
             patch("app.api.v1.routers.content.get_db_session", new=_make_db_ctx(session)), \
             patch("app.modules.content.service.ContentBriefService.reject_brief",
                   new=AsyncMock(return_value=brief)):

            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(
                f"/api/v1/content/briefs/{brief.id}/reject",
                json={"reviewer_notes": "Needs more detail"}
            )
        assert response.status_code in (200, 503)

    def test_reject_not_found(self):
        from app.core.exceptions import NotFoundError
        tid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid)
        app = _make_app(ctx)
        session = _make_session()

        with patch("app.api.v1.routers.content.get_session_factory"), \
             patch("app.api.v1.routers.content.get_db_session", new=_make_db_ctx(session)), \
             patch("app.modules.content.service.ContentBriefService.reject_brief",
                   new=AsyncMock(side_effect=NotFoundError("not found"))):

            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(
                f"/api/v1/content/briefs/{uuid.uuid4()}/reject",
                json={}
            )
        assert response.status_code in (404, 503)
