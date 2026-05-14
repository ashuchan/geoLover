"""Unit tests for Notifications service layer."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.notifications.models import (
    CitationDelta,
    CitationDeltaType,
    Notification,
    NotificationCadence,
    NotificationPreference,
    NotificationPriority,
    NotificationStatus,
    RecrawlSchedule,
)
from app.modules.notifications.service import (
    BounceRecorded,
    CitationDeltaDetected,
    NotificationDelivered,
    NotificationQueued,
    NotificationService,
    RecrawlService,
)


def _make_session():
    s = MagicMock()
    s.flush = AsyncMock()
    s.add = MagicMock()
    s.execute = AsyncMock()
    s.get = AsyncMock()
    return s


def _make_notif(
    *,
    status=NotificationStatus.queued,
    priority=NotificationPriority.standard,
    channel="email",
    suppression_reason=None,
):
    n = MagicMock(spec=Notification)
    n.id = uuid.uuid4()
    n.status = status
    n.priority = priority
    n.channel = channel
    n.suppression_reason = suppression_reason
    n.idempotency_key = "key123"
    n.notification_type = "citation_won"
    n.created_at = datetime.now(timezone.utc)
    return n


def _make_pref(cadence=NotificationCadence.immediate, channels=None):
    p = MagicMock(spec=NotificationPreference)
    p.cadence = cadence
    p.channels_enabled = channels or ["email"]
    return p


def _make_template():
    t = MagicMock()
    t.id = uuid.uuid4()
    return t


class TestRecrawlServiceCreateSchedule:
    @pytest.mark.asyncio
    async def test_create_schedule_sets_next_run_at(self):
        session = _make_session()
        svc = RecrawlService(session)
        created_schedule = MagicMock(spec=RecrawlSchedule)
        created_schedule.id = uuid.uuid4()

        mock_create = AsyncMock(return_value=created_schedule)
        with patch.object(svc._schedule_repo, "create", mock_create):
            schedule = await svc.create_schedule(
                tenant_id=uuid.uuid4(),
                business_id=uuid.uuid4(),
                day_of_week=0,
                hour_local=6,
            )
        assert schedule == created_schedule
        # Verify create was called with next_run_at
        call_kwargs = mock_create.call_args.kwargs
        assert "next_run_at" in call_kwargs
        assert call_kwargs["next_run_at"] is not None


class TestRecrawlServiceUpdateSchedule:
    @pytest.mark.asyncio
    async def test_update_schedule_executes_sql(self):
        session = _make_session()
        svc = RecrawlService(session)
        await svc.update_schedule(
            schedule_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            day_of_week=2,
            hour_local=8,
            enabled=False,
        )
        assert session.execute.called


class TestRecrawlServiceRecordRunComplete:
    @pytest.mark.asyncio
    async def test_record_run_complete_when_schedule_found(self):
        session = _make_session()
        svc = RecrawlService(session)
        schedule = MagicMock(spec=RecrawlSchedule)
        schedule.day_of_week = 0
        schedule.hour_local = 6
        session.get.return_value = schedule

        mock_update_run = AsyncMock()
        svc._schedule_repo.update_run = mock_update_run

        await svc.record_run_complete(
            schedule_id=uuid.uuid4(),
            algorithm_version_baseline="v1.2",
        )
        assert mock_update_run.called

    @pytest.mark.asyncio
    async def test_record_run_complete_when_schedule_not_found(self):
        session = _make_session()
        svc = RecrawlService(session)
        session.get.return_value = None

        mock_update_run = AsyncMock()
        svc._schedule_repo.update_run = mock_update_run

        # Should not raise even if schedule not found
        await svc.record_run_complete(
            schedule_id=uuid.uuid4(),
            algorithm_version_baseline="v1.2",
        )
        mock_update_run.assert_not_called()


class TestRecrawlServiceComputeNextRun:
    def test_returns_future_datetime(self):
        session = _make_session()
        svc = RecrawlService(session)
        now = datetime.now(timezone.utc)
        result = svc.compute_next_run(0, 6)
        assert isinstance(result, datetime)
        assert result > now

    def test_different_days(self):
        session = _make_session()
        svc = RecrawlService(session)
        for dow in range(7):
            result = svc.compute_next_run(dow, 6)
            assert result > datetime.now(timezone.utc)

    def test_returns_same_day_next_week_if_past(self):
        """If the day/hour has already passed today, it should return next week."""
        session = _make_session()
        svc = RecrawlService(session)
        now = datetime.now(timezone.utc)
        # Use hour 0 which is very likely already past
        result = svc.compute_next_run(now.weekday(), 0)
        assert result > now


class TestRecrawlServiceRecordCitationDelta:
    @pytest.mark.asyncio
    async def test_creates_delta_and_event(self):
        session = _make_session()
        svc = RecrawlService(session)
        delta = MagicMock(spec=CitationDelta)
        delta.id = uuid.uuid4()

        with patch.object(svc._delta_repo, "create", new=AsyncMock(return_value=delta)):
            tid = uuid.uuid4()
            result = await svc.record_citation_delta(
                tenant_id=tid,
                business_id=uuid.uuid4(),
                audit_run_id=uuid.uuid4(),
                prior_audit_run_id=None,
                query_id=uuid.uuid4(),
                engine="chatgpt",
                delta_type=CitationDeltaType.won,
                prior_state=None,
                current_state={"cited": True},
            )

        assert result == delta
        assert len(svc.pending_events) == 1
        event = svc.pending_events[0]
        assert isinstance(event, CitationDeltaDetected)
        assert event.delta_id == delta.id
        assert event.tenant_id == tid
        assert event.delta_type in ("won", CitationDeltaType.won)


class TestNotificationServiceQueueCadenceOff:
    @pytest.mark.asyncio
    async def test_cadence_off_returns_suppressed(self):
        session = _make_session()
        svc = NotificationService(session)
        pref = _make_pref(cadence=NotificationCadence.off)
        suppressed_notif = _make_notif(status=NotificationStatus.suppressed, suppression_reason="user_preference")

        with patch.object(svc._notif_repo, "get_by_idempotency_key", new=AsyncMock(return_value=None)), \
             patch.object(svc._pref_repo, "get", new=AsyncMock(return_value=pref)), \
             patch.object(svc._notif_repo, "create", new=AsyncMock(return_value=suppressed_notif)):
            result = await svc.queue(
                recipient_user_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                notification_type="citation_won",
                priority=NotificationPriority.standard,
                render_payload={},
                idempotency_key="key123",
            )

        assert len(result) == 1
        assert result[0].status == NotificationStatus.suppressed
        assert result[0].suppression_reason == "user_preference"


class TestNotificationServiceQueueIdempotency:
    @pytest.mark.asyncio
    async def test_existing_key_returns_existing(self):
        session = _make_session()
        svc = NotificationService(session)
        existing = _make_notif()

        with patch.object(svc._notif_repo, "get_by_idempotency_key", new=AsyncMock(return_value=existing)):
            result = await svc.queue(
                recipient_user_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                notification_type="citation_won",
                priority=NotificationPriority.standard,
                render_payload={},
                idempotency_key="key123",
            )

        assert result == [existing]


class TestNotificationServiceQueueRateLimit:
    @pytest.mark.asyncio
    async def test_digestible_at_limit_suppressed(self):
        session = _make_session()
        svc = NotificationService(session)
        pref = _make_pref(cadence=NotificationCadence.immediate, channels=["email"])
        suppressed = _make_notif(status=NotificationStatus.suppressed, suppression_reason="rate_limited")
        bid = uuid.uuid4()

        with patch.object(svc._notif_repo, "get_by_idempotency_key", new=AsyncMock(return_value=None)), \
             patch.object(svc._pref_repo, "get", new=AsyncMock(return_value=pref)), \
             patch.object(svc._notif_repo, "count_sent_today", new=AsyncMock(return_value=10)), \
             patch.object(svc._notif_repo, "create", new=AsyncMock(return_value=suppressed)):
            result = await svc.queue(
                recipient_user_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                notification_type="citation_won",
                priority=NotificationPriority.digestible,
                render_payload={},
                idempotency_key="key456",
                business_id=bid,
            )

        assert len(result) == 1
        assert result[0].suppression_reason == "rate_limited"

    @pytest.mark.asyncio
    async def test_urgent_hard_cap_suppressed(self):
        session = _make_session()
        svc = NotificationService(session)
        pref = _make_pref(cadence=NotificationCadence.immediate, channels=["email"])
        suppressed = _make_notif(status=NotificationStatus.suppressed, suppression_reason="hard_cap_reached")
        bid = uuid.uuid4()

        with patch.object(svc._notif_repo, "get_by_idempotency_key", new=AsyncMock(return_value=None)), \
             patch.object(svc._pref_repo, "get", new=AsyncMock(return_value=pref)), \
             patch.object(svc._notif_repo, "count_sent_today", new=AsyncMock(return_value=25)), \
             patch.object(svc._notif_repo, "create", new=AsyncMock(return_value=suppressed)):
            result = await svc.queue(
                recipient_user_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                notification_type="citation_urgent",
                priority=NotificationPriority.urgent,
                render_payload={},
                idempotency_key="key789",
                business_id=bid,
            )

        assert len(result) == 1
        assert result[0].suppression_reason == "hard_cap_reached"

    @pytest.mark.asyncio
    async def test_urgent_below_hard_cap_passes(self):
        """Urgent notifications bypass digestible rate limit (10) but respect hard cap (25)."""
        session = _make_session()
        svc = NotificationService(session)
        pref = _make_pref(cadence=NotificationCadence.immediate, channels=["email"])
        template = _make_template()
        queued_notif = _make_notif(status=NotificationStatus.queued)
        bid = uuid.uuid4()

        with patch.object(svc._notif_repo, "get_by_idempotency_key", new=AsyncMock(return_value=None)), \
             patch.object(svc._pref_repo, "get", new=AsyncMock(return_value=pref)), \
             patch.object(svc._notif_repo, "count_sent_today", new=AsyncMock(return_value=15)), \
             patch.object(svc._template_repo, "get_active", new=AsyncMock(return_value=template)), \
             patch.object(svc._notif_repo, "create", new=AsyncMock(return_value=queued_notif)):
            result = await svc.queue(
                recipient_user_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                notification_type="citation_urgent",
                priority=NotificationPriority.urgent,
                render_payload={},
                idempotency_key="key_urgent",
                business_id=bid,
            )

        assert len(result) == 1
        assert result[0].status == NotificationStatus.queued


class TestNotificationServiceQueueCreatesPerChannel:
    @pytest.mark.asyncio
    async def test_creates_notifications_per_channel(self):
        session = _make_session()
        svc = NotificationService(session)
        pref = _make_pref(cadence=NotificationCadence.immediate, channels=["email", "in_app"])
        template = _make_template()
        queued_notif = _make_notif(status=NotificationStatus.queued)
        call_count = 0

        async def mock_create(**kwargs):
            nonlocal call_count
            call_count += 1
            n = _make_notif()
            n.idempotency_key = kwargs.get("idempotency_key", "key")
            n.channel = kwargs.get("channel", "email")
            return n

        with patch.object(svc._notif_repo, "get_by_idempotency_key", new=AsyncMock(return_value=None)), \
             patch.object(svc._pref_repo, "get", new=AsyncMock(return_value=pref)), \
             patch.object(svc._notif_repo, "count_sent_today", new=AsyncMock(return_value=0)), \
             patch.object(svc._template_repo, "get_active", new=AsyncMock(return_value=template)), \
             patch.object(svc._notif_repo, "create", new=mock_create):
            result = await svc.queue(
                recipient_user_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                notification_type="citation_won",
                priority=NotificationPriority.standard,
                render_payload={},
                idempotency_key="key_multi",
            )

        assert len(result) == 2
        assert len(svc.pending_events) == 2
        assert all(isinstance(e, NotificationQueued) for e in svc.pending_events)

    @pytest.mark.asyncio
    async def test_skips_channel_without_template(self):
        session = _make_session()
        svc = NotificationService(session)
        pref = _make_pref(cadence=NotificationCadence.immediate, channels=["email"])

        with patch.object(svc._notif_repo, "get_by_idempotency_key", new=AsyncMock(return_value=None)), \
             patch.object(svc._pref_repo, "get", new=AsyncMock(return_value=pref)), \
             patch.object(svc._notif_repo, "count_sent_today", new=AsyncMock(return_value=0)), \
             patch.object(svc._template_repo, "get_active", new=AsyncMock(return_value=None)):
            result = await svc.queue(
                recipient_user_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                notification_type="citation_won",
                priority=NotificationPriority.standard,
                render_payload={},
                idempotency_key="key_no_tmpl",
            )

        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_uses_default_channels_when_no_pref(self):
        session = _make_session()
        svc = NotificationService(session)
        template = _make_template()
        queued_notif = _make_notif()

        with patch.object(svc._notif_repo, "get_by_idempotency_key", new=AsyncMock(return_value=None)), \
             patch.object(svc._pref_repo, "get", new=AsyncMock(return_value=None)), \
             patch.object(svc._notif_repo, "count_sent_today", new=AsyncMock(return_value=0)), \
             patch.object(svc._template_repo, "get_active", new=AsyncMock(return_value=template)), \
             patch.object(svc._notif_repo, "create", new=AsyncMock(return_value=queued_notif)):
            result = await svc.queue(
                recipient_user_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                notification_type="citation_won",
                priority=NotificationPriority.standard,
                render_payload={},
                idempotency_key="key_default",
            )

        assert len(result) == 1


class TestNotificationServiceRecordDelivery:
    @pytest.mark.asyncio
    async def test_delivered_event_updates_status(self):
        session = _make_session()
        svc = NotificationService(session)
        nid = uuid.uuid4()
        now = datetime.now(timezone.utc)

        mock_log_create = AsyncMock()
        mock_update_status = AsyncMock()
        svc._log_repo.create = mock_log_create
        svc._notif_repo.update_status = mock_update_status

        await svc.record_delivery(
            notification_id=nid,
            tenant_id=uuid.uuid4(),
            provider="resend",
            provider_message_id="msg123",
            event="delivered",
            event_time=now,
        )

        mock_update_status.assert_called_once_with(
            nid, NotificationStatus.delivered, delivered_at=now
        )
        assert len(svc.pending_events) == 1
        assert isinstance(svc.pending_events[0], NotificationDelivered)

    @pytest.mark.asyncio
    async def test_bounced_event_updates_status(self):
        session = _make_session()
        svc = NotificationService(session)
        nid = uuid.uuid4()
        now = datetime.now(timezone.utc)

        mock_log_create = AsyncMock()
        mock_update_status = AsyncMock()
        svc._log_repo.create = mock_log_create
        svc._notif_repo.update_status = mock_update_status

        await svc.record_delivery(
            notification_id=nid,
            tenant_id=uuid.uuid4(),
            provider="resend",
            provider_message_id="msg456",
            event="bounced",
            event_time=now,
        )

        mock_update_status.assert_called_once_with(
            nid, NotificationStatus.bounced, bounced_at=now
        )

    @pytest.mark.asyncio
    async def test_other_event_only_logs(self):
        session = _make_session()
        svc = NotificationService(session)
        now = datetime.now(timezone.utc)

        mock_log_create = AsyncMock()
        mock_update_status = AsyncMock()
        svc._log_repo.create = mock_log_create
        svc._notif_repo.update_status = mock_update_status

        await svc.record_delivery(
            notification_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            provider="resend",
            provider_message_id="msg789",
            event="opened",
            event_time=now,
        )

        mock_update_status.assert_not_called()


class TestNotificationServiceRecordBounce:
    @pytest.mark.asyncio
    async def test_record_bounce_creates_address_and_event(self):
        session = _make_session()
        svc = NotificationService(session)
        addr = MagicMock()

        with patch.object(svc._bounce_repo, "upsert", new=AsyncMock(return_value=addr)):
            await svc.record_bounce(email_normalized="test@example.com", bounce_type="hard")

        assert len(svc.pending_events) == 1
        event = svc.pending_events[0]
        assert isinstance(event, BounceRecorded)
        assert event.email_normalized == "test@example.com"
        assert event.bounce_type == "hard"


class TestNotificationServiceUpdatePreference:
    @pytest.mark.asyncio
    async def test_calls_upsert(self):
        session = _make_session()
        svc = NotificationService(session)
        pref = MagicMock(spec=NotificationPreference)

        mock_upsert = AsyncMock(return_value=pref)
        svc._pref_repo.upsert = mock_upsert
        result = await svc.update_preference(
            user_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            notification_type="citation_won",
            channels_enabled=["email"],
            cadence="immediate",
        )

        assert result == pref
        mock_upsert.assert_called_once()


class TestNotificationServiceMakeIdempotencyKey:
    def test_deterministic_hash(self):
        key1 = NotificationService.make_idempotency_key("citation_won", "biz123", "2026-05-14")
        key2 = NotificationService.make_idempotency_key("citation_won", "biz123", "2026-05-14")
        assert key1 == key2
        assert len(key1) == 32

    def test_different_parts_produce_different_keys(self):
        key1 = NotificationService.make_idempotency_key("citation_won", "biz123")
        key2 = NotificationService.make_idempotency_key("citation_won", "biz456")
        assert key1 != key2

    def test_no_extra_parts(self):
        key = NotificationService.make_idempotency_key("citation_won")
        assert isinstance(key, str)
        assert len(key) == 32
