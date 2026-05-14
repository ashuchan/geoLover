"""Unit tests for Notifications models."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

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


class TestEnums:
    def test_citation_delta_type_values(self):
        assert CitationDeltaType.won == "won"
        assert CitationDeltaType.lost == "lost"
        assert CitationDeltaType.improved == "improved"
        assert CitationDeltaType.declined == "declined"

    def test_notification_priority_values(self):
        assert NotificationPriority.urgent == "urgent"
        assert NotificationPriority.standard == "standard"
        assert NotificationPriority.digestible == "digestible"

    def test_notification_status_values(self):
        assert NotificationStatus.queued == "queued"
        assert NotificationStatus.sending == "sending"
        assert NotificationStatus.delivered == "delivered"
        assert NotificationStatus.bounced == "bounced"
        assert NotificationStatus.failed == "failed"
        assert NotificationStatus.suppressed == "suppressed"

    def test_notification_cadence_values(self):
        assert NotificationCadence.immediate == "immediate"
        assert NotificationCadence.daily_digest == "daily_digest"
        assert NotificationCadence.weekly_digest == "weekly_digest"
        assert NotificationCadence.only_when_active == "only_when_active"
        assert NotificationCadence.off == "off"


class TestRecrawlScheduleModel:
    def test_defaults(self):
        obj = RecrawlSchedule(
            tenant_id=uuid.uuid4(),
            business_id=uuid.uuid4(),
        )
        assert obj.id is not None
        assert obj.cadence == "weekly"
        assert obj.day_of_week == 0
        assert obj.hour_local == 6
        assert obj.enabled is True
        assert obj.created_at is not None
        assert obj.updated_at is not None

    def test_custom_values(self):
        bid = uuid.uuid4()
        tid = uuid.uuid4()
        obj = RecrawlSchedule(
            tenant_id=tid,
            business_id=bid,
            day_of_week=3,
            hour_local=9,
            enabled=False,
        )
        assert obj.day_of_week == 3
        assert obj.hour_local == 9
        assert obj.enabled is False


class TestCitationDeltaModel:
    def test_defaults(self):
        obj = CitationDelta(
            tenant_id=uuid.uuid4(),
            business_id=uuid.uuid4(),
            audit_run_id=uuid.uuid4(),
            query_id=uuid.uuid4(),
            engine="chatgpt",
            delta_type=CitationDeltaType.won,
            current_state={"cited": True},
        )
        assert obj.id is not None
        assert obj.created_at is not None
        assert obj.prior_state is None
        assert obj.prior_audit_run_id is None


class TestNotificationTemplateModel:
    def test_defaults(self):
        obj = NotificationTemplate(
            template_key="citation_won",
            version=1,
            channel="email",
            body_template="You were cited!",
        )
        assert obj.id is not None
        assert obj.locale == "en-IN"
        assert obj.variables_schema == {}
        assert obj.active is False
        assert obj.created_at is not None


class TestNotificationModel:
    def test_defaults(self):
        obj = Notification(
            tenant_id=uuid.uuid4(),
            recipient_user_id=uuid.uuid4(),
            notification_type="citation_won",
            channel="email",
            idempotency_key="abc123",
        )
        assert obj.id is not None
        assert obj.priority == NotificationPriority.standard
        assert obj.render_payload == {}
        assert obj.status == NotificationStatus.queued
        assert obj.send_attempts == 0
        assert obj.created_at is not None


class TestNotificationPreferenceModel:
    def test_defaults(self):
        obj = NotificationPreference(
            user_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            notification_type="citation_won",
        )
        assert obj.id is not None
        assert obj.channels_enabled == []
        assert obj.cadence == NotificationCadence.immediate
        assert obj.updated_at is not None


class TestOutboundDeliveryLogModel:
    def test_defaults(self):
        obj = OutboundDeliveryLog(
            notification_id=uuid.uuid4(),
            provider="resend",
            event="delivered",
            event_time=datetime.now(timezone.utc),
        )
        assert obj.id is not None
        assert obj.created_at is not None
        assert obj.event_details is None


class TestBouncedAddressModel:
    def test_text_pk(self):
        obj = BouncedAddress(
            email_normalized="test@example.com",
            bounce_type="hard",
        )
        # email_normalized is the PK (Text, not UUID)
        assert obj.email_normalized == "test@example.com"
        assert obj.bounce_type == "hard"
        assert obj.bounced_at is not None
        assert obj.cleared_at is None

    def test_custom_bounced_at(self):
        now = datetime.now(timezone.utc)
        obj = BouncedAddress(
            email_normalized="foo@bar.com",
            bounce_type="soft",
            bounced_at=now,
        )
        assert obj.bounced_at == now
