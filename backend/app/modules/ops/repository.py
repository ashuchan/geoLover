"""Repository layer for the Ops/Admin module."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ops.models import (
    ImpersonationLog,
    QuotaEnforcementLog,
    StatusComponent,
    TenantGraceExtension,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class QuotaEnforcementLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, **kwargs) -> QuotaEnforcementLog:
        obj = QuotaEnforcementLog(**kwargs)
        self._session.add(obj)
        await self._session.flush()
        return obj

    async def list_for_tenant(
        self, tenant_id: uuid.UUID, limit: int = 50
    ) -> list[QuotaEnforcementLog]:
        result = await self._session.execute(
            select(QuotaEnforcementLog)
            .where(QuotaEnforcementLog.tenant_id == tenant_id)
            .order_by(QuotaEnforcementLog.triggered_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_recent(self, limit: int = 100) -> list[QuotaEnforcementLog]:
        """Platform-wide, no tenant filter."""
        result = await self._session.execute(
            select(QuotaEnforcementLog)
            .order_by(QuotaEnforcementLog.triggered_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


class TenantGraceExtensionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, **kwargs) -> TenantGraceExtension:
        obj = TenantGraceExtension(**kwargs)
        self._session.add(obj)
        await self._session.flush()
        return obj

    async def get_active(
        self, tenant_id: uuid.UUID, quota_kind: str, now: datetime
    ) -> Optional[TenantGraceExtension]:
        """Returns row where tenant_id matches, quota_kind matches, extended_until > now."""
        result = await self._session.execute(
            select(TenantGraceExtension).where(
                TenantGraceExtension.tenant_id == tenant_id,
                TenantGraceExtension.quota_kind == quota_kind,
                TenantGraceExtension.extended_until > now,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_tenant(self, tenant_id: uuid.UUID) -> list[TenantGraceExtension]:
        result = await self._session.execute(
            select(TenantGraceExtension).where(
                TenantGraceExtension.tenant_id == tenant_id
            )
        )
        return list(result.scalars().all())


class ImpersonationLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, **kwargs) -> ImpersonationLog:
        obj = ImpersonationLog(**kwargs)
        self._session.add(obj)
        await self._session.flush()
        return obj

    async def end_session(self, log_id: uuid.UUID) -> None:
        """Sets ended_at = now() via atomic UPDATE."""
        await self._session.execute(
            update(ImpersonationLog)
            .where(ImpersonationLog.id == log_id)
            .values(ended_at=_utcnow())
        )

    async def list_by_admin(
        self, admin_user_id: uuid.UUID, limit: int = 50
    ) -> list[ImpersonationLog]:
        result = await self._session.execute(
            select(ImpersonationLog)
            .where(ImpersonationLog.admin_user_id == admin_user_id)
            .order_by(ImpersonationLog.started_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_for_tenant(
        self, impersonated_tenant_id: uuid.UUID, limit: int = 50
    ) -> list[ImpersonationLog]:
        result = await self._session.execute(
            select(ImpersonationLog)
            .where(ImpersonationLog.impersonated_tenant_id == impersonated_tenant_id)
            .order_by(ImpersonationLog.started_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get(self, log_id: uuid.UUID) -> Optional[ImpersonationLog]:
        result = await self._session.execute(
            select(ImpersonationLog).where(ImpersonationLog.id == log_id)
        )
        return result.scalar_one_or_none()


class StatusComponentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, **kwargs) -> StatusComponent:
        obj = StatusComponent(**kwargs)
        self._session.add(obj)
        await self._session.flush()
        return obj

    async def get_by_name(self, name: str) -> Optional[StatusComponent]:
        result = await self._session.execute(
            select(StatusComponent).where(StatusComponent.name == name)
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> list[StatusComponent]:
        result = await self._session.execute(select(StatusComponent))
        return list(result.scalars().all())

    async def update_state(
        self, component_id: uuid.UUID, state: str, evaluated_at: datetime
    ) -> None:
        """Atomic UPDATE for component state."""
        await self._session.execute(
            update(StatusComponent)
            .where(StatusComponent.id == component_id)
            .values(last_known_state=state, last_evaluated_at=evaluated_at)
        )
