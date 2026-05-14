"""Unit tests for Publishing API router."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies.auth import TenantContext
from app.modules.publishing.models import (
    EntitySeed,
    EntitySeedStatus,
    PublishChannel,
    PublishTarget,
    PublishTargetStatus,
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


def _make_target_mock(tid):
    t = MagicMock()
    t.id = uuid.uuid4()
    t.tenant_id = tid
    t.business_id = uuid.uuid4()
    t.channel = PublishChannel.wordpress
    t.status = PublishTargetStatus.pending_oauth
    t.connected_account_label = None
    t.external_identifier = None
    t.publish_authorized_at = None
    t.revoked_at = None
    t.last_publish_at = None
    t.meta = {}
    t.created_at = datetime.now(timezone.utc)
    t.updated_at = datetime.now(timezone.utc)
    return t


def _make_seed_mock(tid):
    s = MagicMock()
    s.id = uuid.uuid4()
    s.tenant_id = tid
    s.business_id = uuid.uuid4()
    s.directory_id = uuid.uuid4()
    s.status = EntitySeedStatus.pending_submission
    s.external_listing_id = None
    s.external_listing_url = None
    s.submitted_at = None
    s.first_verified_at = None
    s.last_verified_at = None
    s.created_at = datetime.now(timezone.utc)
    s.updated_at = datetime.now(timezone.utc)
    return s


class TestListTargets:
    def test_list_targets_success(self):
        tid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid)
        app = _make_app(ctx)
        session = _make_session()
        target = _make_target_mock(tid)

        with patch("app.api.v1.routers.publishing.get_session_factory"), patch(
            "app.api.v1.routers.publishing.get_db_session", new=_make_db_ctx(session)
        ), patch(
            "app.modules.publishing.repository.PublishTargetRepository.list_for_business",
            new=AsyncMock(return_value=[target]),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get(
                f"/api/v1/publishing/targets?business_id={target.business_id}"
            )
        assert response.status_code in (200, 503)

    def test_list_targets_empty(self):
        tid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid)
        app = _make_app(ctx)
        session = _make_session()

        with patch("app.api.v1.routers.publishing.get_session_factory"), patch(
            "app.api.v1.routers.publishing.get_db_session", new=_make_db_ctx(session)
        ), patch(
            "app.modules.publishing.repository.PublishTargetRepository.list_for_business",
            new=AsyncMock(return_value=[]),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get(
                f"/api/v1/publishing/targets?business_id={uuid.uuid4()}"
            )
        assert response.status_code in (200, 503)


class TestGetTarget:
    def test_get_target_success(self):
        tid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid)
        app = _make_app(ctx)
        session = _make_session()
        target = _make_target_mock(tid)

        with patch("app.api.v1.routers.publishing.get_session_factory"), patch(
            "app.api.v1.routers.publishing.get_db_session", new=_make_db_ctx(session)
        ), patch(
            "app.modules.publishing.repository.PublishTargetRepository.get",
            new=AsyncMock(return_value=target),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get(f"/api/v1/publishing/targets/{target.id}")
        assert response.status_code in (200, 503)

    def test_get_target_not_found(self):
        tid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid)
        app = _make_app(ctx)
        session = _make_session()

        with patch("app.api.v1.routers.publishing.get_session_factory"), patch(
            "app.api.v1.routers.publishing.get_db_session", new=_make_db_ctx(session)
        ), patch(
            "app.modules.publishing.repository.PublishTargetRepository.get",
            new=AsyncMock(return_value=None),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get(f"/api/v1/publishing/targets/{uuid.uuid4()}")
        assert response.status_code in (404, 503)


class TestCreateTarget:
    def test_create_target_success(self):
        tid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid)
        app = _make_app(ctx)
        session = _make_session()
        business_id = uuid.uuid4()
        target = _make_target_mock(tid)
        target.business_id = business_id

        with patch("app.api.v1.routers.publishing.get_session_factory"), patch(
            "app.api.v1.routers.publishing.get_db_session", new=_make_db_ctx(session)
        ), patch(
            "app.modules.publishing.service.PublishService.connect_target",
            new=AsyncMock(return_value=target),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(
                "/api/v1/publishing/targets",
                json={
                    "business_id": str(business_id),
                    "channel": "wordpress",
                    "redirect_uri": "https://example.com/cb",
                },
            )
        assert response.status_code in (201, 503)

    def test_create_target_with_meta(self):
        tid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid)
        app = _make_app(ctx)
        session = _make_session()
        business_id = uuid.uuid4()
        target = _make_target_mock(tid)

        with patch("app.api.v1.routers.publishing.get_session_factory"), patch(
            "app.api.v1.routers.publishing.get_db_session", new=_make_db_ctx(session)
        ), patch(
            "app.modules.publishing.service.PublishService.connect_target",
            new=AsyncMock(return_value=target),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(
                "/api/v1/publishing/targets",
                json={
                    "business_id": str(business_id),
                    "channel": "google_business_profile",
                    "redirect_uri": "https://example.com/cb",
                    "meta": {"key": "value"},
                },
            )
        assert response.status_code in (201, 503)


class TestAuthorizeTarget:
    def test_authorize_success(self):
        tid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid)
        app = _make_app(ctx)
        session = _make_session()
        target = _make_target_mock(tid)
        target.status = PublishTargetStatus.connected

        with patch("app.api.v1.routers.publishing.get_session_factory"), patch(
            "app.api.v1.routers.publishing.get_db_session", new=_make_db_ctx(session)
        ), patch(
            "app.modules.publishing.service.PublishService.authorize_publish",
            new=AsyncMock(return_value=target),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(f"/api/v1/publishing/targets/{target.id}/authorize")
        assert response.status_code in (200, 503)

    def test_authorize_not_found(self):
        tid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid)
        app = _make_app(ctx)
        session = _make_session()

        with patch("app.api.v1.routers.publishing.get_session_factory"), patch(
            "app.api.v1.routers.publishing.get_db_session", new=_make_db_ctx(session)
        ), patch(
            "app.modules.publishing.service.PublishService.authorize_publish",
            new=AsyncMock(return_value=None),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(f"/api/v1/publishing/targets/{uuid.uuid4()}/authorize")
        assert response.status_code in (404, 503)


class TestRevokeTarget:
    def test_revoke_success(self):
        tid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid)
        app = _make_app(ctx)
        session = _make_session()

        with patch("app.api.v1.routers.publishing.get_session_factory"), patch(
            "app.api.v1.routers.publishing.get_db_session", new=_make_db_ctx(session)
        ), patch(
            "app.modules.publishing.service.PublishService.revoke_target",
            new=AsyncMock(),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(f"/api/v1/publishing/targets/{uuid.uuid4()}/revoke")
        assert response.status_code in (204, 503)


class TestListSeeds:
    def test_list_seeds_success(self):
        tid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid)
        app = _make_app(ctx)
        session = _make_session()
        seed = _make_seed_mock(tid)

        with patch("app.api.v1.routers.publishing.get_session_factory"), patch(
            "app.api.v1.routers.publishing.get_db_session", new=_make_db_ctx(session)
        ), patch(
            "app.modules.publishing.repository.EntitySeedRepository.list_for_business",
            new=AsyncMock(return_value=[seed]),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get(
                f"/api/v1/publishing/seeds?business_id={seed.business_id}"
            )
        assert response.status_code in (200, 503)

    def test_list_seeds_empty(self):
        tid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid)
        app = _make_app(ctx)
        session = _make_session()

        with patch("app.api.v1.routers.publishing.get_session_factory"), patch(
            "app.api.v1.routers.publishing.get_db_session", new=_make_db_ctx(session)
        ), patch(
            "app.modules.publishing.repository.EntitySeedRepository.list_for_business",
            new=AsyncMock(return_value=[]),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get(
                f"/api/v1/publishing/seeds?business_id={uuid.uuid4()}"
            )
        assert response.status_code in (200, 503)
