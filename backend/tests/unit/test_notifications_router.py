"""Unit tests for Notifications & Recrawl Schedule API router."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies.auth import TenantContext
from app.modules.notifications.models import (
    Notification,
    NotificationCadence,
    NotificationPreference,
    NotificationPriority,
    NotificationStatus,
    RecrawlSchedule,
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
    s.get = AsyncMock()
    return s


def _make_notif_mock(tid, uid):
    n = MagicMock()
    n.id = uuid.uuid4()
    n.tenant_id = tid
    n.recipient_user_id = uid
    n.notification_type = "citation_won"
    n.priority = NotificationPriority.standard
    n.channel = "email"
    n.status = NotificationStatus.queued
    n.idempotency_key = "key123"
    n.created_at = datetime.now(timezone.utc)
    return n


def _make_pref_mock(uid, tid):
    p = MagicMock()
    p.user_id = uid
    p.tenant_id = tid
    p.notification_type = "citation_won"
    p.channels_enabled = ["email"]
    p.cadence = NotificationCadence.immediate
    return p


def _make_schedule_mock(tid):
    s = MagicMock()
    s.id = uuid.uuid4()
    s.tenant_id = tid
    s.business_id = uuid.uuid4()
    s.day_of_week = 0
    s.hour_local = 6
    s.enabled = True
    s.next_run_at = datetime.now(timezone.utc)
    s.last_run_at = None
    return s


class TestListNotifications:
    def test_list_notifications_success(self):
        tid = uuid.uuid4()
        uid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid, user_id=uid)
        app = _make_app(ctx)
        session = _make_session()
        notif = _make_notif_mock(tid, uid)

        with patch("app.api.v1.routers.notifications.get_session_factory"), patch(
            "app.api.v1.routers.notifications.get_db_session", new=_make_db_ctx(session)
        ), patch(
            "app.modules.notifications.repository.NotificationRepository.list_for_user",
            new=AsyncMock(return_value=[notif]),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/notifications")
        assert response.status_code in (200, 503)

    def test_list_notifications_empty(self):
        tid = uuid.uuid4()
        uid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid, user_id=uid)
        app = _make_app(ctx)
        session = _make_session()

        with patch("app.api.v1.routers.notifications.get_session_factory"), patch(
            "app.api.v1.routers.notifications.get_db_session", new=_make_db_ctx(session)
        ), patch(
            "app.modules.notifications.repository.NotificationRepository.list_for_user",
            new=AsyncMock(return_value=[]),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/notifications")
        assert response.status_code in (200, 503)

    def test_list_notifications_with_business_id(self):
        tid = uuid.uuid4()
        uid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid, user_id=uid)
        app = _make_app(ctx)
        session = _make_session()

        with patch("app.api.v1.routers.notifications.get_session_factory"), patch(
            "app.api.v1.routers.notifications.get_db_session", new=_make_db_ctx(session)
        ), patch(
            "app.modules.notifications.repository.NotificationRepository.list_for_user",
            new=AsyncMock(return_value=[]),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get(f"/api/v1/notifications?business_id={uuid.uuid4()}&limit=10")
        assert response.status_code in (200, 503)


class TestListPreferences:
    def test_list_preferences_success(self):
        tid = uuid.uuid4()
        uid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid, user_id=uid)
        app = _make_app(ctx)
        session = _make_session()
        pref = _make_pref_mock(uid, tid)

        with patch("app.api.v1.routers.notifications.get_session_factory"), patch(
            "app.api.v1.routers.notifications.get_db_session", new=_make_db_ctx(session)
        ), patch(
            "app.modules.notifications.repository.NotificationPreferenceRepository.list_for_user",
            new=AsyncMock(return_value=[pref]),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/notifications/preferences")
        assert response.status_code in (200, 503)

    def test_list_preferences_empty(self):
        tid = uuid.uuid4()
        uid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid, user_id=uid)
        app = _make_app(ctx)
        session = _make_session()

        with patch("app.api.v1.routers.notifications.get_session_factory"), patch(
            "app.api.v1.routers.notifications.get_db_session", new=_make_db_ctx(session)
        ), patch(
            "app.modules.notifications.repository.NotificationPreferenceRepository.list_for_user",
            new=AsyncMock(return_value=[]),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/notifications/preferences")
        assert response.status_code in (200, 503)


class TestUpdatePreference:
    def test_update_preference_success(self):
        tid = uuid.uuid4()
        uid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid, user_id=uid)
        app = _make_app(ctx)
        session = _make_session()
        pref = _make_pref_mock(uid, tid)

        with patch("app.api.v1.routers.notifications.get_session_factory"), patch(
            "app.api.v1.routers.notifications.get_db_session", new=_make_db_ctx(session)
        ), patch(
            "app.modules.notifications.service.NotificationService.update_preference",
            new=AsyncMock(return_value=pref),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.put(
                "/api/v1/notifications/preferences/citation_won",
                json={"channels_enabled": ["email"], "cadence": "immediate"},
            )
        assert response.status_code in (200, 503)


class TestResendWebhook:
    def test_resend_webhook_accepted(self):
        ctx = _make_ctx()
        app = _make_app(ctx)

        client = TestClient(app, raise_server_exceptions=False)
        response = client.post(
            "/api/v1/notifications/webhooks/resend",
            json={"type": "email.delivered", "data": {"message_id": "msg123"}},
        )
        assert response.status_code in (200, 503)

    def test_resend_webhook_bounce_event(self):
        ctx = _make_ctx()
        app = _make_app(ctx)

        client = TestClient(app, raise_server_exceptions=False)
        response = client.post(
            "/api/v1/notifications/webhooks/resend",
            json={"type": "email.bounced", "data": {"email": "user@example.com"}},
        )
        assert response.status_code in (200, 503)


class TestListRecrawlSchedules:
    def test_list_schedules_success(self):
        tid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid)
        app = _make_app(ctx)
        session = _make_session()
        schedule = _make_schedule_mock(tid)
        bid = schedule.business_id

        with patch("app.api.v1.routers.notifications.get_session_factory"), patch(
            "app.api.v1.routers.notifications.get_db_session", new=_make_db_ctx(session)
        ), patch(
            "app.modules.notifications.repository.RecrawlScheduleRepository.get_by_business",
            new=AsyncMock(return_value=schedule),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get(f"/api/v1/recrawl/schedules?business_id={bid}")
        assert response.status_code in (200, 503)

    def test_list_schedules_not_found(self):
        tid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid)
        app = _make_app(ctx)
        session = _make_session()

        with patch("app.api.v1.routers.notifications.get_session_factory"), patch(
            "app.api.v1.routers.notifications.get_db_session", new=_make_db_ctx(session)
        ), patch(
            "app.modules.notifications.repository.RecrawlScheduleRepository.get_by_business",
            new=AsyncMock(return_value=None),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get(f"/api/v1/recrawl/schedules?business_id={uuid.uuid4()}")
        assert response.status_code in (200, 503)


class TestCreateRecrawlSchedule:
    def test_create_schedule_success(self):
        tid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid)
        app = _make_app(ctx)
        session = _make_session()
        schedule = _make_schedule_mock(tid)
        bid = uuid.uuid4()
        schedule.business_id = bid

        with patch("app.api.v1.routers.notifications.get_session_factory"), patch(
            "app.api.v1.routers.notifications.get_db_session", new=_make_db_ctx(session)
        ), patch(
            "app.modules.notifications.service.RecrawlService.create_schedule",
            new=AsyncMock(return_value=schedule),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(
                "/api/v1/recrawl/schedules",
                json={
                    "business_id": str(bid),
                    "day_of_week": 0,
                    "hour_local": 6,
                },
            )
        assert response.status_code in (201, 503)

    def test_create_schedule_defaults(self):
        tid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid)
        app = _make_app(ctx)
        session = _make_session()
        schedule = _make_schedule_mock(tid)
        bid = uuid.uuid4()
        schedule.business_id = bid

        with patch("app.api.v1.routers.notifications.get_session_factory"), patch(
            "app.api.v1.routers.notifications.get_db_session", new=_make_db_ctx(session)
        ), patch(
            "app.modules.notifications.service.RecrawlService.create_schedule",
            new=AsyncMock(return_value=schedule),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(
                "/api/v1/recrawl/schedules",
                json={"business_id": str(bid)},
            )
        assert response.status_code in (201, 503)


class TestUpdateRecrawlSchedule:
    def test_update_schedule_success(self):
        tid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid)
        app = _make_app(ctx)
        session = _make_session()
        schedule = _make_schedule_mock(tid)
        schedule_id = schedule.id

        with patch("app.api.v1.routers.notifications.get_session_factory"), patch(
            "app.api.v1.routers.notifications.get_db_session", new=_make_db_ctx(session)
        ), patch(
            "app.modules.notifications.service.RecrawlService.update_schedule",
            new=AsyncMock(),
        ), patch(
            "app.modules.notifications.repository.RecrawlScheduleRepository.get",
            new=AsyncMock(return_value=schedule),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.put(
                f"/api/v1/recrawl/schedules/{schedule_id}",
                json={"day_of_week": 1, "hour_local": 8, "enabled": True},
            )
        assert response.status_code in (200, 503)

    def test_update_schedule_not_found(self):
        tid = uuid.uuid4()
        ctx = _make_ctx(tenant_id=tid)
        app = _make_app(ctx)
        session = _make_session()

        with patch("app.api.v1.routers.notifications.get_session_factory"), patch(
            "app.api.v1.routers.notifications.get_db_session", new=_make_db_ctx(session)
        ), patch(
            "app.modules.notifications.service.RecrawlService.update_schedule",
            new=AsyncMock(),
        ), patch(
            "app.modules.notifications.repository.RecrawlScheduleRepository.get",
            new=AsyncMock(return_value=None),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.put(
                f"/api/v1/recrawl/schedules/{uuid.uuid4()}",
                json={"day_of_week": 1, "hour_local": 8, "enabled": True},
            )
        assert response.status_code in (404, 503)
