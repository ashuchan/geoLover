"""PublishService — orchestrates publishing targets, attempts, and entity seeding."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.publishing.adapters import PublisherRegistry
from app.modules.publishing.models import (
    EntitySeed,
    EntitySeedStatus,
    PublishAttempt,
    PublishAttemptStatus,
    PublishTarget,
    PublishTargetStatus,
    VerificationPoll,
)
from app.modules.publishing.repository import (
    EntitySeedRepository,
    PublishAttemptRepository,
    PublishTargetRepository,
    VerificationPollRepository,
)
from app.modules.publishing.token_vault import TokenVault


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Domain Events ──────────────────────────────────────────────────────────────


class PublishTargetConnected:
    name = "PublishTargetConnected"

    def __init__(self, target_id: uuid.UUID, tenant_id: uuid.UUID, channel: str) -> None:
        self.target_id = target_id
        self.tenant_id = tenant_id
        self.channel = channel


class PublishAttemptSucceeded:
    name = "PublishAttemptSucceeded"

    def __init__(self, attempt_id: uuid.UUID, tenant_id: uuid.UUID, public_url: Optional[str]) -> None:
        self.attempt_id = attempt_id
        self.tenant_id = tenant_id
        self.public_url = public_url


class PublishAttemptFailed:
    name = "PublishAttemptFailed"

    def __init__(
        self,
        attempt_id: uuid.UUID,
        tenant_id: uuid.UUID,
        failure_reason: Optional[str],
        is_terminal: bool,
    ) -> None:
        self.attempt_id = attempt_id
        self.tenant_id = tenant_id
        self.failure_reason = failure_reason
        self.is_terminal = is_terminal


class EntitySeedSubmitted:
    name = "EntitySeedSubmitted"

    def __init__(self, seed_id: uuid.UUID, tenant_id: uuid.UUID, directory_id: uuid.UUID) -> None:
        self.seed_id = seed_id
        self.tenant_id = tenant_id
        self.directory_id = directory_id


class OAuthTokenRefreshFailed:
    name = "OAuthTokenRefreshFailed"

    def __init__(self, target_id: uuid.UUID, tenant_id: uuid.UUID, is_revoked: bool) -> None:
        self.target_id = target_id
        self.tenant_id = tenant_id
        self.is_revoked = is_revoked


# ── Service ───────────────────────────────────────────────────────────────────


class PublishService:
    """Manages publishing targets, attempts, and entity seeding."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        registry: Optional[PublisherRegistry] = None,
        vault: Optional[TokenVault] = None,
    ) -> None:
        self._session = session
        self._registry = registry if registry is not None else PublisherRegistry()
        self._vault = vault if vault is not None else TokenVault()
        self._pending_events: list = []
        self._target_repo = PublishTargetRepository(session)
        self._attempt_repo = PublishAttemptRepository(session)
        self._seed_repo = EntitySeedRepository(session)
        self._poll_repo = VerificationPollRepository(session)

    @property
    def pending_events(self) -> list:
        return list(self._pending_events)

    async def connect_target(
        self,
        *,
        tenant_id: uuid.UUID,
        business_id: uuid.UUID,
        channel: str,
        redirect_uri: str,
        connected_account_label: str = "",
        external_identifier: str = "",
        meta: Optional[dict] = None,
    ) -> PublishTarget:
        """Create a new publish target in pending_oauth status."""
        target = await self._target_repo.create(
            tenant_id=tenant_id,
            business_id=business_id,
            channel=channel,
            status=PublishTargetStatus.pending_oauth,
            connected_account_label=connected_account_label or None,
            external_identifier=external_identifier or None,
            meta=meta or {},
        )
        self._pending_events.append(
            PublishTargetConnected(
                target_id=target.id,
                tenant_id=tenant_id,
                channel=channel,
            )
        )
        return target

    async def authorize_publish(
        self,
        *,
        target_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> PublishTarget:
        """Set publish_authorized_at and update status to connected."""
        now = _utcnow()
        await self._target_repo.update_status(
            target_id,
            PublishTargetStatus.connected,
        )
        # Fetch and update publish_authorized_at directly
        target = await self._target_repo.get(target_id, tenant_id)
        if target is not None:
            target.publish_authorized_at = now
            target.updated_at = now
            await self._session.flush()
        return target  # type: ignore[return-value]

    async def revoke_target(
        self,
        *,
        target_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> None:
        """Set revoked_at and update status to revoked."""
        now = _utcnow()
        await self._target_repo.update_status(
            target_id,
            PublishTargetStatus.revoked,
            revoked_at=now,
        )

    async def initiate_publish(
        self,
        *,
        tenant_id: uuid.UUID,
        business_id: uuid.UUID,
        target_id: uuid.UUID,
        content_asset_id: uuid.UUID,
        brief_id: uuid.UUID,
    ) -> PublishAttempt:
        """Create a publish attempt (idempotent by target+asset sha256 key)."""
        key_source = f"{target_id}:{content_asset_id}"
        idempotency_key = hashlib.sha256(key_source.encode()).hexdigest()

        existing = await self._attempt_repo.get_by_idempotency_key(idempotency_key)
        if existing is not None:
            return existing

        attempt = await self._attempt_repo.create(
            tenant_id=tenant_id,
            business_id=business_id,
            target_id=target_id,
            content_asset_id=content_asset_id,
            brief_id=brief_id,
            idempotency_key=idempotency_key,
            status=PublishAttemptStatus.queued,
        )
        return attempt

    async def record_publish_result(
        self,
        *,
        attempt_id: uuid.UUID,
        tenant_id: uuid.UUID,
        result,  # PublishResult from adapters
    ) -> None:
        """Update attempt status based on publish result."""
        if result.success:
            status = PublishAttemptStatus.succeeded
            await self._attempt_repo.update_status(
                attempt_id,
                status,
                external_object_id=result.external_object_id,
                public_url=result.public_url,
                last_attempt_at=_utcnow(),
            )
            self._pending_events.append(
                PublishAttemptSucceeded(
                    attempt_id=attempt_id,
                    tenant_id=tenant_id,
                    public_url=result.public_url,
                )
            )
        else:
            if result.is_retryable:
                status = PublishAttemptStatus.failed_retryable
            else:
                status = PublishAttemptStatus.failed_terminal
            await self._attempt_repo.update_status(
                attempt_id,
                status,
                failure_reason=result.failure_reason,
                last_attempt_at=_utcnow(),
            )
            self._pending_events.append(
                PublishAttemptFailed(
                    attempt_id=attempt_id,
                    tenant_id=tenant_id,
                    failure_reason=result.failure_reason,
                    is_terminal=not result.is_retryable,
                )
            )

    async def create_entity_seed(
        self,
        *,
        tenant_id: uuid.UUID,
        business_id: uuid.UUID,
        directory_id: uuid.UUID,
        submission_payload: dict,
        profile_snapshot: Optional[dict] = None,
    ) -> EntitySeed:
        """Create an entity seed and emit EntitySeedSubmitted event."""
        seed = await self._seed_repo.create(
            tenant_id=tenant_id,
            business_id=business_id,
            directory_id=directory_id,
            submission_payload=submission_payload,
            profile_snapshot=profile_snapshot or {},
            status=EntitySeedStatus.pending_submission,
        )
        self._pending_events.append(
            EntitySeedSubmitted(
                seed_id=seed.id,
                tenant_id=tenant_id,
                directory_id=directory_id,
            )
        )
        return seed

    async def record_seed_submitted(
        self,
        *,
        seed_id: uuid.UUID,
        tenant_id: uuid.UUID,
        external_listing_id: Optional[str] = None,
    ) -> None:
        """Update seed to submitted status with submitted_at timestamp."""
        now = _utcnow()
        kwargs: dict = {"submitted_at": now}
        if external_listing_id is not None:
            kwargs["external_listing_id"] = external_listing_id
        await self._seed_repo.update_status(
            seed_id,
            EntitySeedStatus.submitted,
            **kwargs,
        )

    async def record_seed_verified(
        self,
        *,
        seed_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> None:
        """Update seed to verified. Sets first_verified_at if not yet set."""
        now = _utcnow()
        seed = await self._seed_repo.get(seed_id, tenant_id)
        kwargs: dict = {"last_verified_at": now}
        if seed is not None and seed.first_verified_at is None:
            kwargs["first_verified_at"] = now
        await self._seed_repo.update_status(
            seed_id,
            EntitySeedStatus.verified,
            **kwargs,
        )

    async def schedule_verification_polls(
        self,
        *,
        tenant_id: uuid.UUID,
        publish_attempt_id: uuid.UUID,
        base_time: datetime,
    ) -> list[VerificationPoll]:
        """Create verification polls at T+15min, T+1h, T+24h."""
        offsets = [
            timedelta(minutes=15),
            timedelta(hours=1),
            timedelta(hours=24),
        ]
        polls = []
        for i, offset in enumerate(offsets):
            poll = await self._poll_repo.create(
                tenant_id=tenant_id,
                publish_attempt_id=publish_attempt_id,
                scheduled_for=base_time + offset,
                attempt_index=i,
            )
            polls.append(poll)
        return polls

    async def schedule_seed_verification_polls(
        self,
        *,
        tenant_id: uuid.UUID,
        seed_id: uuid.UUID,
        base_time: datetime,
    ) -> list[VerificationPoll]:
        """Create verification polls at T+24h, T+72h, T+7d, T+14d, T+30d."""
        offsets = [
            timedelta(hours=24),
            timedelta(hours=72),
            timedelta(days=7),
            timedelta(days=14),
            timedelta(days=30),
        ]
        polls = []
        for i, offset in enumerate(offsets):
            poll = await self._poll_repo.create(
                tenant_id=tenant_id,
                seed_id=seed_id,
                scheduled_for=base_time + offset,
                attempt_index=i,
            )
            polls.append(poll)
        return polls
