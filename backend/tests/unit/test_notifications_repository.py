"""Unit tests for Notifications repository layer."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.notifications.models import (
    BouncedAddress,
    CitationDelta,
    CitationDeltaType,
    Notification,
    NotificationCadence,
    NotificationPreference,
    NotificationPriority,
    NotificationStatus,
    NotificationTemplate,
    OutboundDeliveryLog,
    RecrawlSchedule,
)
from app.modules.notifications.repository import (
    BouncedAddressRepository,
    CitationDeltaRepository,
    NotificationPreferenceRepository,
    NotificationRepository,
    NotificationTemplateRepository,
    OutboundDeliveryLogRepository,
    RecrawlScheduleRepository,
)


def _make_session():
    s = MagicMock()
    s.flush = AsyncMock()
    s.add = MagicMock()
    s.execute = AsyncMock()
    return s


def _scalar_result(value):
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    r.scalar_one.return_value = value
    r.scalar.return_value = value
    r.scalars.return_value.all.return_value = [value] if value is not None else []
    return r


def _scalars_result(values):
    r = MagicMock()
    r.scalars.return_value.all.return_value = values
    r.scalar.return_value = len(values)
    return r


class TestRecrawlScheduleRepository:
    @pytest.mark.asyncio
    async def test_create(self):
        session = _make_session()
        repo = RecrawlScheduleRepository(session)
        result = await repo.create(
            tenant_id=uuid.uuid4(),
            business_id=uuid.uuid4(),
            day_of_week=0,
            hour_local=6,
        )
        assert session.add.called
        assert session.flush.called
        assert isinstance(result, RecrawlSchedule)

    @pytest.mark.asyncio
    async def test_get_found(self):
        session = _make_session()
        schedule = MagicMock(spec=RecrawlSchedule)
        session.execute.return_value = _scalar_result(schedule)
        repo = RecrawlScheduleRepository(session)
        result = await repo.get(uuid.uuid4(), uuid.uuid4())
        assert result == schedule

    @pytest.mark.asyncio
    async def test_get_not_found(self):
        session = _make_session()
        session.execute.return_value = _scalar_result(None)
        repo = RecrawlScheduleRepository(session)
        result = await repo.get(uuid.uuid4(), uuid.uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_business(self):
        session = _make_session()
        schedule = MagicMock(spec=RecrawlSchedule)
        session.execute.return_value = _scalar_result(schedule)
        repo = RecrawlScheduleRepository(session)
        result = await repo.get_by_business(uuid.uuid4())
        assert result == schedule

    @pytest.mark.asyncio
    async def test_list_bucket(self):
        session = _make_session()
        schedules = [MagicMock(spec=RecrawlSchedule)]
        session.execute.return_value = _scalars_result(schedules)
        repo = RecrawlScheduleRepository(session)
        result = await repo.list_bucket(0, 6)
        assert result == schedules

    @pytest.mark.asyncio
    async def test_update_run(self):
        session = _make_session()
        repo = RecrawlScheduleRepository(session)
        now = datetime.now(timezone.utc)
        await repo.update_run(uuid.uuid4(), now, now)
        assert session.execute.called


class TestCitationDeltaRepository:
    @pytest.mark.asyncio
    async def test_create(self):
        session = _make_session()
        repo = CitationDeltaRepository(session)
        result = await repo.create(
            tenant_id=uuid.uuid4(),
            business_id=uuid.uuid4(),
            audit_run_id=uuid.uuid4(),
            query_id=uuid.uuid4(),
            engine="chatgpt",
            delta_type=CitationDeltaType.won,
            current_state={"cited": True},
        )
        assert session.add.called
        assert isinstance(result, CitationDelta)

    @pytest.mark.asyncio
    async def test_list_for_audit_run(self):
        session = _make_session()
        deltas = [MagicMock(spec=CitationDelta)]
        session.execute.return_value = _scalars_result(deltas)
        repo = CitationDeltaRepository(session)
        result = await repo.list_for_audit_run(uuid.uuid4())
        assert result == deltas

    @pytest.mark.asyncio
    async def test_list_for_business(self):
        session = _make_session()
        deltas = [MagicMock(spec=CitationDelta)]
        session.execute.return_value = _scalars_result(deltas)
        repo = CitationDeltaRepository(session)
        result = await repo.list_for_business(uuid.uuid4(), uuid.uuid4())
        assert result == deltas


class TestNotificationTemplateRepository:
    @pytest.mark.asyncio
    async def test_create(self):
        session = _make_session()
        repo = NotificationTemplateRepository(session)
        result = await repo.create(
            template_key="citation_won",
            version=1,
            channel="email",
            body_template="You were cited!",
        )
        assert session.add.called
        assert isinstance(result, NotificationTemplate)

    @pytest.mark.asyncio
    async def test_get_active_found(self):
        session = _make_session()
        tmpl = MagicMock(spec=NotificationTemplate)
        session.execute.return_value = _scalar_result(tmpl)
        repo = NotificationTemplateRepository(session)
        result = await repo.get_active("citation_won", "email")
        assert result == tmpl

    @pytest.mark.asyncio
    async def test_get_active_not_found(self):
        session = _make_session()
        session.execute.return_value = _scalar_result(None)
        repo = NotificationTemplateRepository(session)
        result = await repo.get_active("nonexistent", "email")
        assert result is None


class TestNotificationRepository:
    @pytest.mark.asyncio
    async def test_create(self):
        session = _make_session()
        repo = NotificationRepository(session)
        result = await repo.create(
            tenant_id=uuid.uuid4(),
            recipient_user_id=uuid.uuid4(),
            notification_type="citation_won",
            channel="email",
            idempotency_key="key123",
        )
        assert session.add.called
        assert isinstance(result, Notification)

    @pytest.mark.asyncio
    async def test_get_by_idempotency_key_found(self):
        session = _make_session()
        notif = MagicMock(spec=Notification)
        session.execute.return_value = _scalar_result(notif)
        repo = NotificationRepository(session)
        result = await repo.get_by_idempotency_key("key123")
        assert result == notif

    @pytest.mark.asyncio
    async def test_get_by_idempotency_key_not_found(self):
        session = _make_session()
        session.execute.return_value = _scalar_result(None)
        repo = NotificationRepository(session)
        result = await repo.get_by_idempotency_key("key123")
        assert result is None

    @pytest.mark.asyncio
    async def test_get(self):
        session = _make_session()
        notif = MagicMock(spec=Notification)
        session.execute.return_value = _scalar_result(notif)
        repo = NotificationRepository(session)
        result = await repo.get(uuid.uuid4(), uuid.uuid4())
        assert result == notif

    @pytest.mark.asyncio
    async def test_list_for_user(self):
        session = _make_session()
        notifs = [MagicMock(spec=Notification)]
        session.execute.return_value = _scalars_result(notifs)
        repo = NotificationRepository(session)
        result = await repo.list_for_user(uuid.uuid4(), uuid.uuid4())
        assert result == notifs

    @pytest.mark.asyncio
    async def test_count_sent_today(self):
        session = _make_session()
        count_result = MagicMock()
        count_result.scalar.return_value = 5
        session.execute.return_value = count_result
        repo = NotificationRepository(session)
        result = await repo.count_sent_today(uuid.uuid4(), uuid.uuid4(), "2026-05-14")
        assert result == 5

    @pytest.mark.asyncio
    async def test_count_sent_today_none(self):
        session = _make_session()
        count_result = MagicMock()
        count_result.scalar.return_value = None
        session.execute.return_value = count_result
        repo = NotificationRepository(session)
        result = await repo.count_sent_today(uuid.uuid4(), uuid.uuid4(), "2026-05-14")
        assert result == 0

    @pytest.mark.asyncio
    async def test_update_status(self):
        session = _make_session()
        repo = NotificationRepository(session)
        await repo.update_status(uuid.uuid4(), NotificationStatus.delivered, delivered_at=datetime.now(timezone.utc))
        assert session.execute.called


class TestNotificationPreferenceRepository:
    @pytest.mark.asyncio
    async def test_upsert(self):
        session = _make_session()
        pref = MagicMock(spec=NotificationPreference)
        # First execute (insert/upsert), second execute (select)
        execute_results = [MagicMock(), _scalar_result(pref)]
        session.execute.side_effect = execute_results
        repo = NotificationPreferenceRepository(session)
        result = await repo.upsert(
            uuid.uuid4(), uuid.uuid4(), "citation_won", ["email"], "immediate"
        )
        assert result == pref

    @pytest.mark.asyncio
    async def test_get_found(self):
        session = _make_session()
        pref = MagicMock(spec=NotificationPreference)
        session.execute.return_value = _scalar_result(pref)
        repo = NotificationPreferenceRepository(session)
        result = await repo.get(uuid.uuid4(), uuid.uuid4(), "citation_won")
        assert result == pref

    @pytest.mark.asyncio
    async def test_get_not_found(self):
        session = _make_session()
        session.execute.return_value = _scalar_result(None)
        repo = NotificationPreferenceRepository(session)
        result = await repo.get(uuid.uuid4(), uuid.uuid4(), "nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_for_user(self):
        session = _make_session()
        prefs = [MagicMock(spec=NotificationPreference)]
        session.execute.return_value = _scalars_result(prefs)
        repo = NotificationPreferenceRepository(session)
        result = await repo.list_for_user(uuid.uuid4(), uuid.uuid4())
        assert result == prefs


class TestOutboundDeliveryLogRepository:
    @pytest.mark.asyncio
    async def test_create(self):
        session = _make_session()
        repo = OutboundDeliveryLogRepository(session)
        result = await repo.create(
            notification_id=uuid.uuid4(),
            provider="resend",
            event="delivered",
            event_time=datetime.now(timezone.utc),
        )
        assert session.add.called
        assert isinstance(result, OutboundDeliveryLog)

    @pytest.mark.asyncio
    async def test_list_for_notification(self):
        session = _make_session()
        logs = [MagicMock(spec=OutboundDeliveryLog)]
        session.execute.return_value = _scalars_result(logs)
        repo = OutboundDeliveryLogRepository(session)
        result = await repo.list_for_notification(uuid.uuid4())
        assert result == logs


class TestBouncedAddressRepository:
    @pytest.mark.asyncio
    async def test_upsert(self):
        session = _make_session()
        addr = MagicMock(spec=BouncedAddress)
        execute_results = [MagicMock(), _scalar_result(addr)]
        session.execute.side_effect = execute_results
        repo = BouncedAddressRepository(session)
        result = await repo.upsert("test@example.com", "hard")
        assert result == addr

    @pytest.mark.asyncio
    async def test_get_found(self):
        session = _make_session()
        addr = MagicMock(spec=BouncedAddress)
        session.execute.return_value = _scalar_result(addr)
        repo = BouncedAddressRepository(session)
        result = await repo.get("test@example.com")
        assert result == addr

    @pytest.mark.asyncio
    async def test_get_not_found(self):
        session = _make_session()
        session.execute.return_value = _scalar_result(None)
        repo = BouncedAddressRepository(session)
        result = await repo.get("unknown@example.com")
        assert result is None

    @pytest.mark.asyncio
    async def test_is_bounced_true(self):
        session = _make_session()
        addr = MagicMock(spec=BouncedAddress)
        session.execute.return_value = _scalar_result(addr)
        repo = BouncedAddressRepository(session)
        result = await repo.is_bounced("test@example.com")
        assert result is True

    @pytest.mark.asyncio
    async def test_is_bounced_false(self):
        session = _make_session()
        session.execute.return_value = _scalar_result(None)
        repo = BouncedAddressRepository(session)
        result = await repo.is_bounced("notbounced@example.com")
        assert result is False

    @pytest.mark.asyncio
    async def test_clear(self):
        session = _make_session()
        repo = BouncedAddressRepository(session)
        await repo.clear("test@example.com")
        assert session.execute.called
