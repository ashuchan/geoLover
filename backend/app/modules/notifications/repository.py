"""Repository layer for the Notifications & Recrawl module."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.models import (
    BouncedAddress,
    CitationDelta,
    Notification,
    NotificationPreference,
    NotificationStatus,
    NotificationTemplate,
    OutboundDeliveryLog,
    RecrawlSchedule,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RecrawlScheduleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, **kwargs) -> RecrawlSchedule:
        obj = RecrawlSchedule(**kwargs)
        self._session.add(obj)
        await self._session.flush()
        return obj

    async def get(self, schedule_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[RecrawlSchedule]:
        result = await self._session.execute(
            select(RecrawlSchedule).where(
                RecrawlSchedule.id == schedule_id,
                RecrawlSchedule.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_business(self, business_id: uuid.UUID) -> Optional[RecrawlSchedule]:
        result = await self._session.execute(
            select(RecrawlSchedule).where(RecrawlSchedule.business_id == business_id)
        )
        return result.scalar_one_or_none()

    async def list_bucket(self, day_of_week: int, hour_local: int) -> list[RecrawlSchedule]:
        result = await self._session.execute(
            select(RecrawlSchedule).where(
                RecrawlSchedule.day_of_week == day_of_week,
                RecrawlSchedule.hour_local == hour_local,
                RecrawlSchedule.enabled == True,  # noqa: E712
            )
        )
        return list(result.scalars().all())

    async def update_run(
        self,
        schedule_id: uuid.UUID,
        last_run_at: datetime,
        next_run_at: datetime,
    ) -> None:
        await self._session.execute(
            update(RecrawlSchedule)
            .where(RecrawlSchedule.id == schedule_id)
            .values(last_run_at=last_run_at, next_run_at=next_run_at, updated_at=_utcnow())
        )


class CitationDeltaRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, **kwargs) -> CitationDelta:
        obj = CitationDelta(**kwargs)
        self._session.add(obj)
        await self._session.flush()
        return obj

    async def list_for_audit_run(self, audit_run_id: uuid.UUID) -> list[CitationDelta]:
        result = await self._session.execute(
            select(CitationDelta).where(CitationDelta.audit_run_id == audit_run_id)
        )
        return list(result.scalars().all())

    async def list_for_business(
        self,
        tenant_id: uuid.UUID,
        business_id: uuid.UUID,
        limit: int = 50,
    ) -> list[CitationDelta]:
        result = await self._session.execute(
            select(CitationDelta)
            .where(
                CitationDelta.tenant_id == tenant_id,
                CitationDelta.business_id == business_id,
            )
            .limit(limit)
        )
        return list(result.scalars().all())


class NotificationTemplateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, **kwargs) -> NotificationTemplate:
        obj = NotificationTemplate(**kwargs)
        self._session.add(obj)
        await self._session.flush()
        return obj

    async def get_active(
        self,
        template_key: str,
        channel: str,
        locale: str = "en-IN",
    ) -> Optional[NotificationTemplate]:
        result = await self._session.execute(
            select(NotificationTemplate).where(
                NotificationTemplate.template_key == template_key,
                NotificationTemplate.channel == channel,
                NotificationTemplate.locale == locale,
                NotificationTemplate.active == True,  # noqa: E712
            )
        )
        return result.scalar_one_or_none()


class NotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, **kwargs) -> Notification:
        obj = Notification(**kwargs)
        self._session.add(obj)
        await self._session.flush()
        return obj

    async def get_by_idempotency_key(self, key: str) -> Optional[Notification]:
        result = await self._session.execute(
            select(Notification).where(Notification.idempotency_key == key)
        )
        return result.scalar_one_or_none()

    async def get(self, notification_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[Notification]:
        result = await self._session.execute(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        limit: int = 50,
    ) -> list[Notification]:
        result = await self._session.execute(
            select(Notification)
            .where(
                Notification.tenant_id == tenant_id,
                Notification.recipient_user_id == user_id,
            )
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_sent_today(
        self,
        user_id: uuid.UUID,
        business_id: uuid.UUID,
        date_iso: str,
    ) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(Notification).where(
                Notification.recipient_user_id == user_id,
                Notification.business_id == business_id,
                Notification.status != NotificationStatus.suppressed,
                func.date(Notification.created_at) == date_iso,
            )
        )
        return result.scalar() or 0

    async def update_status(
        self,
        notification_id: uuid.UUID,
        status: NotificationStatus,
        **kwargs,
    ) -> None:
        vals: dict = {"status": status, **kwargs}
        await self._session.execute(
            update(Notification).where(Notification.id == notification_id).values(**vals)
        )


class NotificationPreferenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self,
        user_id: uuid.UUID,
        tenant_id: uuid.UUID,
        notification_type: str,
        channels_enabled: list,
        cadence: str,
    ) -> NotificationPreference:
        stmt = (
            pg_insert(NotificationPreference)
            .values(
                id=uuid.uuid4(),
                user_id=user_id,
                tenant_id=tenant_id,
                notification_type=notification_type,
                channels_enabled=channels_enabled,
                cadence=cadence,
                updated_at=_utcnow(),
            )
            .on_conflict_do_update(
                index_elements=["user_id", "tenant_id", "notification_type"],
                set_={
                    "channels_enabled": channels_enabled,
                    "cadence": cadence,
                    "updated_at": _utcnow(),
                },
            )
        )
        await self._session.execute(stmt)
        result = await self._session.execute(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user_id,
                NotificationPreference.tenant_id == tenant_id,
                NotificationPreference.notification_type == notification_type,
            )
        )
        return result.scalar_one()

    async def get(
        self,
        user_id: uuid.UUID,
        tenant_id: uuid.UUID,
        notification_type: str,
    ) -> Optional[NotificationPreference]:
        result = await self._session.execute(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user_id,
                NotificationPreference.tenant_id == tenant_id,
                NotificationPreference.notification_type == notification_type,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self,
        user_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> list[NotificationPreference]:
        result = await self._session.execute(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user_id,
                NotificationPreference.tenant_id == tenant_id,
            )
        )
        return list(result.scalars().all())


class OutboundDeliveryLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, **kwargs) -> OutboundDeliveryLog:
        obj = OutboundDeliveryLog(**kwargs)
        self._session.add(obj)
        await self._session.flush()
        return obj

    async def list_for_notification(self, notification_id: uuid.UUID) -> list[OutboundDeliveryLog]:
        result = await self._session.execute(
            select(OutboundDeliveryLog).where(
                OutboundDeliveryLog.notification_id == notification_id
            )
        )
        return list(result.scalars().all())


class BouncedAddressRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, email_normalized: str, bounce_type: str) -> BouncedAddress:
        stmt = (
            pg_insert(BouncedAddress)
            .values(
                email_normalized=email_normalized,
                bounce_type=bounce_type,
                bounced_at=_utcnow(),
            )
            .on_conflict_do_update(
                index_elements=["email_normalized"],
                set_={
                    "bounce_type": bounce_type,
                    "bounced_at": _utcnow(),
                    "cleared_at": None,
                },
            )
        )
        await self._session.execute(stmt)
        result = await self._session.execute(
            select(BouncedAddress).where(BouncedAddress.email_normalized == email_normalized)
        )
        return result.scalar_one()

    async def get(self, email_normalized: str) -> Optional[BouncedAddress]:
        result = await self._session.execute(
            select(BouncedAddress).where(BouncedAddress.email_normalized == email_normalized)
        )
        return result.scalar_one_or_none()

    async def is_bounced(self, email_normalized: str) -> bool:
        result = await self._session.execute(
            select(BouncedAddress).where(
                BouncedAddress.email_normalized == email_normalized,
                BouncedAddress.cleared_at.is_(None),
            )
        )
        return result.scalar_one_or_none() is not None

    async def clear(self, email_normalized: str) -> None:
        await self._session.execute(
            update(BouncedAddress)
            .where(BouncedAddress.email_normalized == email_normalized)
            .values(cleared_at=_utcnow())
        )
