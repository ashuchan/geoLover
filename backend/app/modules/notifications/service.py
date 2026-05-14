"""Service layer for the Notifications & Recrawl module."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

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
from app.modules.notifications.repository import (
    BouncedAddressRepository,
    CitationDeltaRepository,
    NotificationPreferenceRepository,
    NotificationRepository,
    NotificationTemplateRepository,
    OutboundDeliveryLogRepository,
    RecrawlScheduleRepository,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Domain Events ──────────────────────────────────────────────────────────────


@dataclass
class CitationDeltaDetected:
    name = "CitationDeltaDetected"
    delta_id: uuid.UUID
    tenant_id: uuid.UUID
    delta_type: str


@dataclass
class NotificationQueued:
    name = "NotificationQueued"
    notification_id: uuid.UUID
    tenant_id: uuid.UUID
    notification_type: str


@dataclass
class NotificationDelivered:
    name = "NotificationDelivered"
    notification_id: uuid.UUID


@dataclass
class BounceRecorded:
    name = "BounceRecorded"
    email_normalized: str
    bounce_type: str


# ── Services ──────────────────────────────────────────────────────────────────


class RecrawlService:
    """Manages recrawl schedules and citation deltas."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._pending_events: list = []
        self._schedule_repo = RecrawlScheduleRepository(session)
        self._delta_repo = CitationDeltaRepository(session)

    @property
    def pending_events(self) -> list:
        return list(self._pending_events)

    async def create_schedule(
        self,
        *,
        tenant_id: uuid.UUID,
        business_id: uuid.UUID,
        day_of_week: int = 0,
        hour_local: int = 6,
    ) -> RecrawlSchedule:
        """Create a recrawl schedule with next_run_at set to the next occurrence."""
        next_run = self.compute_next_run(day_of_week, hour_local)
        schedule = await self._schedule_repo.create(
            tenant_id=tenant_id,
            business_id=business_id,
            day_of_week=day_of_week,
            hour_local=hour_local,
            next_run_at=next_run,
        )
        return schedule

    async def update_schedule(
        self,
        *,
        schedule_id: uuid.UUID,
        tenant_id: uuid.UUID,
        day_of_week: int,
        hour_local: int,
        enabled: bool,
    ) -> None:
        """Atomically update a recrawl schedule."""
        next_run = self.compute_next_run(day_of_week, hour_local)
        from sqlalchemy import update
        await self._session.execute(
            update(RecrawlSchedule)
            .where(
                RecrawlSchedule.id == schedule_id,
                RecrawlSchedule.tenant_id == tenant_id,
            )
            .values(
                day_of_week=day_of_week,
                hour_local=hour_local,
                enabled=enabled,
                next_run_at=next_run,
                updated_at=_utcnow(),
            )
        )

    async def record_run_complete(
        self,
        *,
        schedule_id: uuid.UUID,
        algorithm_version_baseline: str,
    ) -> None:
        """Record a completed run and recompute next_run_at."""
        schedule = await self._session.get(RecrawlSchedule, schedule_id)
        now = _utcnow()
        if schedule is not None:
            next_run = self.compute_next_run(schedule.day_of_week, schedule.hour_local)
            await self._schedule_repo.update_run(
                schedule_id,
                last_run_at=now,
                next_run_at=next_run,
            )
            from sqlalchemy import update
            await self._session.execute(
                update(RecrawlSchedule)
                .where(RecrawlSchedule.id == schedule_id)
                .values(algorithm_version_baseline=algorithm_version_baseline)
            )

    def compute_next_run(self, day_of_week: int, hour_local: int) -> datetime:
        """Compute the next datetime for this day/hour combination (forward from now)."""
        now = _utcnow()
        # day_of_week: 0=Monday, 6=Sunday (Python weekday convention)
        current_dow = now.weekday()
        days_ahead = day_of_week - current_dow
        if days_ahead < 0:
            days_ahead += 7
        elif days_ahead == 0 and now.hour >= hour_local:
            days_ahead = 7
        candidate = now.replace(hour=hour_local, minute=0, second=0, microsecond=0) + timedelta(days=days_ahead)
        return candidate

    async def record_citation_delta(
        self,
        *,
        tenant_id: uuid.UUID,
        business_id: uuid.UUID,
        audit_run_id: uuid.UUID,
        prior_audit_run_id: Optional[uuid.UUID],
        query_id: uuid.UUID,
        engine: str,
        delta_type: CitationDeltaType,
        prior_state: Optional[dict],
        current_state: dict,
        source_publish_attempt_id: Optional[uuid.UUID] = None,
    ) -> CitationDelta:
        """Create a citation delta and emit CitationDeltaDetected event."""
        delta = await self._delta_repo.create(
            tenant_id=tenant_id,
            business_id=business_id,
            audit_run_id=audit_run_id,
            prior_audit_run_id=prior_audit_run_id,
            query_id=query_id,
            engine=engine,
            delta_type=delta_type,
            prior_state=prior_state,
            current_state=current_state,
            source_publish_attempt_id=source_publish_attempt_id,
        )
        self._pending_events.append(
            CitationDeltaDetected(
                delta_id=delta.id,
                tenant_id=tenant_id,
                delta_type=delta_type if isinstance(delta_type, str) else delta_type.value,
            )
        )
        return delta


class NotificationService:
    """Manages notification queuing, delivery, and preferences."""

    _DAILY_LIMIT_DIGESTIBLE = 10
    _DAILY_LIMIT_URGENT = 25

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._pending_events: list = []
        self._notif_repo = NotificationRepository(session)
        self._template_repo = NotificationTemplateRepository(session)
        self._pref_repo = NotificationPreferenceRepository(session)
        self._log_repo = OutboundDeliveryLogRepository(session)
        self._bounce_repo = BouncedAddressRepository(session)

    @property
    def pending_events(self) -> list:
        return list(self._pending_events)

    async def queue(
        self,
        *,
        recipient_user_id: uuid.UUID,
        tenant_id: uuid.UUID,
        notification_type: str,
        priority: NotificationPriority,
        render_payload: dict,
        idempotency_key: str,
        business_id: Optional[uuid.UUID] = None,
    ) -> list[Notification]:
        """Queue notifications for all applicable channels. Idempotent."""
        # 1. Check idempotency
        existing = await self._notif_repo.get_by_idempotency_key(idempotency_key)
        if existing is not None:
            return [existing]

        # 2. Get preference
        pref = await self._pref_repo.get(recipient_user_id, tenant_id, notification_type)
        if pref is None:
            channels_enabled = ["email"]
            cadence = NotificationCadence.immediate
        else:
            channels_enabled = pref.channels_enabled
            cadence = pref.cadence if isinstance(pref.cadence, NotificationCadence) else NotificationCadence(pref.cadence)

        # 3. If cadence == off: suppress
        if cadence == NotificationCadence.off:
            notif = await self._notif_repo.create(
                tenant_id=tenant_id,
                recipient_user_id=recipient_user_id,
                business_id=business_id,
                notification_type=notification_type,
                priority=priority,
                channel="suppressed",
                render_payload=render_payload,
                idempotency_key=idempotency_key,
                status=NotificationStatus.suppressed,
                suppression_reason="user_preference",
            )
            return [notif]

        # 4. Rate-limit check
        today_iso = _utcnow().date().isoformat()
        if business_id is not None:
            sent_today = await self._notif_repo.count_sent_today(recipient_user_id, business_id, today_iso)
        else:
            sent_today = 0

        priority_val = priority if isinstance(priority, NotificationPriority) else NotificationPriority(priority)

        if priority_val == NotificationPriority.urgent:
            if sent_today >= self._DAILY_LIMIT_URGENT:
                notif = await self._notif_repo.create(
                    tenant_id=tenant_id,
                    recipient_user_id=recipient_user_id,
                    business_id=business_id,
                    notification_type=notification_type,
                    priority=priority,
                    channel="suppressed",
                    render_payload=render_payload,
                    idempotency_key=idempotency_key,
                    status=NotificationStatus.suppressed,
                    suppression_reason="hard_cap_reached",
                )
                return [notif]
        else:
            # digestible or standard
            if sent_today >= self._DAILY_LIMIT_DIGESTIBLE:
                notif = await self._notif_repo.create(
                    tenant_id=tenant_id,
                    recipient_user_id=recipient_user_id,
                    business_id=business_id,
                    notification_type=notification_type,
                    priority=priority,
                    channel="suppressed",
                    render_payload=render_payload,
                    idempotency_key=idempotency_key,
                    status=NotificationStatus.suppressed,
                    suppression_reason="rate_limited",
                )
                return [notif]

        # 5. Create notification per channel
        created: list[Notification] = []
        for channel in channels_enabled:
            template = await self._template_repo.get_active(notification_type, channel, "en-IN")
            if template is None:
                # No template found for this channel — skip
                continue
            notif = await self._notif_repo.create(
                tenant_id=tenant_id,
                recipient_user_id=recipient_user_id,
                business_id=business_id,
                notification_type=notification_type,
                priority=priority,
                channel=channel,
                template_version_id=template.id,
                render_payload=render_payload,
                idempotency_key=idempotency_key,
                status=NotificationStatus.queued,
            )
            created.append(notif)
            self._pending_events.append(
                NotificationQueued(
                    notification_id=notif.id,
                    tenant_id=tenant_id,
                    notification_type=notification_type,
                )
            )

        return created

    async def record_delivery(
        self,
        *,
        notification_id: uuid.UUID,
        tenant_id: uuid.UUID,
        provider: str,
        provider_message_id: Optional[str],
        event: str,
        event_time: datetime,
        event_details: Optional[dict] = None,
    ) -> None:
        """Record a delivery event and update notification status."""
        await self._log_repo.create(
            notification_id=notification_id,
            provider=provider,
            provider_message_id=provider_message_id,
            event=event,
            event_time=event_time,
            event_details=event_details,
        )

        if event == "delivered":
            await self._notif_repo.update_status(
                notification_id,
                NotificationStatus.delivered,
                delivered_at=event_time,
            )
            self._pending_events.append(NotificationDelivered(notification_id=notification_id))
        elif event in ("bounced", "complaint"):
            await self._notif_repo.update_status(
                notification_id,
                NotificationStatus.bounced,
                bounced_at=event_time,
            )
            # Fetch notification to get recipient email context (bounce recorded separately)

    async def record_bounce(
        self,
        *,
        email_normalized: str,
        bounce_type: str,
    ) -> None:
        """Record a bounced email address."""
        await self._bounce_repo.upsert(email_normalized, bounce_type)
        self._pending_events.append(
            BounceRecorded(
                email_normalized=email_normalized,
                bounce_type=bounce_type,
            )
        )

    async def update_preference(
        self,
        *,
        user_id: uuid.UUID,
        tenant_id: uuid.UUID,
        notification_type: str,
        channels_enabled: list,
        cadence: str,
    ) -> NotificationPreference:
        """Upsert notification preference for a user."""
        return await self._pref_repo.upsert(
            user_id=user_id,
            tenant_id=tenant_id,
            notification_type=notification_type,
            channels_enabled=channels_enabled,
            cadence=cadence,
        )

    @staticmethod
    def make_idempotency_key(notification_type: str, *parts: str) -> str:
        """Generate a deterministic idempotency key from notification_type and parts."""
        raw = ":".join([notification_type, *parts])
        return hashlib.sha256(raw.encode()).hexdigest()[:32]
