"""Repository layer for the Publishing & Entity Seeding module."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.publishing.models import (
    DirectoryRegistry,
    EntitySeed,
    EntitySeedStatus,
    OAuthToken,
    PublishAttempt,
    PublishAttemptStatus,
    PublishTarget,
    PublishTargetStatus,
    VerificationPoll,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PublishTargetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, **kwargs) -> PublishTarget:
        obj = PublishTarget(**kwargs)
        self._session.add(obj)
        await self._session.flush()
        return obj

    async def get(self, target_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[PublishTarget]:
        result = await self._session.execute(
            select(PublishTarget).where(
                PublishTarget.id == target_id,
                PublishTarget.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_business(self, tenant_id: uuid.UUID, business_id: uuid.UUID) -> list[PublishTarget]:
        result = await self._session.execute(
            select(PublishTarget).where(
                PublishTarget.tenant_id == tenant_id,
                PublishTarget.business_id == business_id,
            )
        )
        return list(result.scalars().all())

    async def update_status(
        self,
        target_id: uuid.UUID,
        status: PublishTargetStatus,
        *,
        revoked_at: Optional[datetime] = None,
        last_publish_at: Optional[datetime] = None,
    ) -> None:
        vals: dict = {"status": status, "updated_at": _utcnow()}
        if revoked_at is not None:
            vals["revoked_at"] = revoked_at
        if last_publish_at is not None:
            vals["last_publish_at"] = last_publish_at
        await self._session.execute(
            update(PublishTarget).where(PublishTarget.id == target_id).values(**vals)
        )


class OAuthTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, **kwargs) -> OAuthToken:
        obj = OAuthToken(**kwargs)
        self._session.add(obj)
        await self._session.flush()
        return obj

    async def get(self, token_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[OAuthToken]:
        result = await self._session.execute(
            select(OAuthToken).where(
                OAuthToken.id == token_id,
                OAuthToken.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_expiring_soon(self, before: datetime) -> list[OAuthToken]:
        result = await self._session.execute(
            select(OAuthToken).where(OAuthToken.access_token_expires_at < before)
        )
        return list(result.scalars().all())

    async def update_after_refresh(self, token_id: uuid.UUID, **kwargs) -> None:
        vals = {**kwargs, "updated_at": _utcnow(), "last_refreshed_at": _utcnow()}
        await self._session.execute(
            update(OAuthToken).where(OAuthToken.id == token_id).values(**vals)
        )


class PublishAttemptRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, **kwargs) -> PublishAttempt:
        obj = PublishAttempt(**kwargs)
        self._session.add(obj)
        await self._session.flush()
        return obj

    async def get_by_idempotency_key(self, key: str) -> Optional[PublishAttempt]:
        result = await self._session.execute(
            select(PublishAttempt).where(PublishAttempt.idempotency_key == key)
        )
        return result.scalar_one_or_none()

    async def get(self, attempt_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[PublishAttempt]:
        result = await self._session.execute(
            select(PublishAttempt).where(
                PublishAttempt.id == attempt_id,
                PublishAttempt.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_target(self, target_id: uuid.UUID) -> list[PublishAttempt]:
        result = await self._session.execute(
            select(PublishAttempt).where(PublishAttempt.target_id == target_id)
        )
        return list(result.scalars().all())

    async def update_status(
        self,
        attempt_id: uuid.UUID,
        status: PublishAttemptStatus,
        **kwargs,
    ) -> None:
        vals = {"status": status, **kwargs}
        await self._session.execute(
            update(PublishAttempt).where(PublishAttempt.id == attempt_id).values(**vals)
        )


class EntitySeedRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, **kwargs) -> EntitySeed:
        obj = EntitySeed(**kwargs)
        self._session.add(obj)
        await self._session.flush()
        return obj

    async def get(self, seed_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[EntitySeed]:
        result = await self._session.execute(
            select(EntitySeed).where(
                EntitySeed.id == seed_id,
                EntitySeed.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_business_directory(
        self, business_id: uuid.UUID, directory_id: uuid.UUID
    ) -> Optional[EntitySeed]:
        result = await self._session.execute(
            select(EntitySeed).where(
                EntitySeed.business_id == business_id,
                EntitySeed.directory_id == directory_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_business(self, tenant_id: uuid.UUID, business_id: uuid.UUID) -> list[EntitySeed]:
        result = await self._session.execute(
            select(EntitySeed).where(
                EntitySeed.tenant_id == tenant_id,
                EntitySeed.business_id == business_id,
            )
        )
        return list(result.scalars().all())

    async def update_status(
        self,
        seed_id: uuid.UUID,
        status: EntitySeedStatus,
        **kwargs,
    ) -> None:
        vals = {"status": status, "updated_at": _utcnow(), **kwargs}
        await self._session.execute(
            update(EntitySeed).where(EntitySeed.id == seed_id).values(**vals)
        )


class DirectoryRegistryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_active(self) -> list[DirectoryRegistry]:
        result = await self._session.execute(
            select(DirectoryRegistry).where(DirectoryRegistry.active == True)  # noqa: E712
        )
        return list(result.scalars().all())

    async def get_by_slug(self, slug: str) -> Optional[DirectoryRegistry]:
        result = await self._session.execute(
            select(DirectoryRegistry).where(DirectoryRegistry.slug == slug)
        )
        return result.scalar_one_or_none()

    async def create(self, **kwargs) -> DirectoryRegistry:
        obj = DirectoryRegistry(**kwargs)
        self._session.add(obj)
        await self._session.flush()
        return obj


class VerificationPollRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, **kwargs) -> VerificationPoll:
        obj = VerificationPoll(**kwargs)
        self._session.add(obj)
        await self._session.flush()
        return obj

    async def list_due(self, before: datetime) -> list[VerificationPoll]:
        result = await self._session.execute(
            select(VerificationPoll).where(
                VerificationPoll.scheduled_for <= before,
                VerificationPoll.attempted_at.is_(None),
            )
        )
        return list(result.scalars().all())

    async def mark_attempted(self, poll_id: uuid.UUID, outcome: str) -> None:
        await self._session.execute(
            update(VerificationPoll).where(VerificationPoll.id == poll_id).values(
                attempted_at=_utcnow(),
                outcome=outcome,
            )
        )

    async def list_for_seed(self, seed_id: uuid.UUID) -> list[VerificationPoll]:
        result = await self._session.execute(
            select(VerificationPoll).where(VerificationPoll.seed_id == seed_id)
        )
        return list(result.scalars().all())
