"""Unit tests for Publishing repository layer."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
from app.modules.publishing.repository import (
    DirectoryRegistryRepository,
    EntitySeedRepository,
    OAuthTokenRepository,
    PublishAttemptRepository,
    PublishTargetRepository,
    VerificationPollRepository,
)


def _make_session():
    s = MagicMock()
    s.flush = AsyncMock()
    s.add = MagicMock()
    return s


def _make_result(obj):
    result = MagicMock()
    result.scalar_one_or_none.return_value = obj
    scalars = MagicMock()
    scalars.all.return_value = [obj] if obj else []
    result.scalars.return_value = scalars
    return result


def _make_list_result(objs):
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = objs
    result.scalars.return_value = scalars
    return result


class TestPublishTargetRepository:
    @pytest.mark.asyncio
    async def test_create(self):
        session = _make_session()
        session.execute = AsyncMock()
        repo = PublishTargetRepository(session)
        target = await repo.create(
            tenant_id=uuid.uuid4(),
            business_id=uuid.uuid4(),
            channel="wordpress",
        )
        assert isinstance(target, PublishTarget)
        session.add.assert_called_once()
        session.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_found(self):
        session = _make_session()
        target = MagicMock(spec=PublishTarget)
        session.execute = AsyncMock(return_value=_make_result(target))
        repo = PublishTargetRepository(session)
        result = await repo.get(uuid.uuid4(), uuid.uuid4())
        assert result == target

    @pytest.mark.asyncio
    async def test_get_not_found(self):
        session = _make_session()
        session.execute = AsyncMock(return_value=_make_result(None))
        repo = PublishTargetRepository(session)
        result = await repo.get(uuid.uuid4(), uuid.uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_list_for_business(self):
        session = _make_session()
        targets = [MagicMock(spec=PublishTarget), MagicMock(spec=PublishTarget)]
        session.execute = AsyncMock(return_value=_make_list_result(targets))
        repo = PublishTargetRepository(session)
        result = await repo.list_for_business(uuid.uuid4(), uuid.uuid4())
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_update_status(self):
        session = _make_session()
        session.execute = AsyncMock()
        repo = PublishTargetRepository(session)
        await repo.update_status(uuid.uuid4(), PublishTargetStatus.connected)
        session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_status_with_revoked_at(self):
        session = _make_session()
        session.execute = AsyncMock()
        repo = PublishTargetRepository(session)
        now = datetime.now(timezone.utc)
        await repo.update_status(uuid.uuid4(), PublishTargetStatus.revoked, revoked_at=now)
        session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_status_with_last_publish_at(self):
        session = _make_session()
        session.execute = AsyncMock()
        repo = PublishTargetRepository(session)
        now = datetime.now(timezone.utc)
        await repo.update_status(uuid.uuid4(), PublishTargetStatus.connected, last_publish_at=now)
        session.execute.assert_called_once()


class TestOAuthTokenRepository:
    @pytest.mark.asyncio
    async def test_create(self):
        session = _make_session()
        repo = OAuthTokenRepository(session)
        now = datetime.now(timezone.utc)
        token = await repo.create(
            tenant_id=uuid.uuid4(),
            provider="google",
            access_token_encrypted=b"enc",
            refresh_token_encrypted=b"ref",
            wrapped_dek=b"dek",
            kms_key_version="v1",
            access_token_expires_at=now,
            scope="email",
        )
        assert isinstance(token, OAuthToken)

    @pytest.mark.asyncio
    async def test_get_found(self):
        session = _make_session()
        token = MagicMock(spec=OAuthToken)
        session.execute = AsyncMock(return_value=_make_result(token))
        repo = OAuthTokenRepository(session)
        result = await repo.get(uuid.uuid4(), uuid.uuid4())
        assert result == token

    @pytest.mark.asyncio
    async def test_list_expiring_soon(self):
        session = _make_session()
        token = MagicMock(spec=OAuthToken)
        session.execute = AsyncMock(return_value=_make_list_result([token]))
        repo = OAuthTokenRepository(session)
        result = await repo.list_expiring_soon(datetime.now(timezone.utc))
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_update_after_refresh(self):
        session = _make_session()
        session.execute = AsyncMock()
        repo = OAuthTokenRepository(session)
        await repo.update_after_refresh(uuid.uuid4(), scope="email profile")
        session.execute.assert_called_once()


class TestPublishAttemptRepository:
    @pytest.mark.asyncio
    async def test_create(self):
        session = _make_session()
        repo = PublishAttemptRepository(session)
        attempt = await repo.create(
            tenant_id=uuid.uuid4(),
            business_id=uuid.uuid4(),
            target_id=uuid.uuid4(),
            content_asset_id=uuid.uuid4(),
            brief_id=uuid.uuid4(),
            idempotency_key="key123",
        )
        assert isinstance(attempt, PublishAttempt)

    @pytest.mark.asyncio
    async def test_get_by_idempotency_key_found(self):
        session = _make_session()
        attempt = MagicMock(spec=PublishAttempt)
        session.execute = AsyncMock(return_value=_make_result(attempt))
        repo = PublishAttemptRepository(session)
        result = await repo.get_by_idempotency_key("key123")
        assert result == attempt

    @pytest.mark.asyncio
    async def test_get_by_idempotency_key_not_found(self):
        session = _make_session()
        session.execute = AsyncMock(return_value=_make_result(None))
        repo = PublishAttemptRepository(session)
        result = await repo.get_by_idempotency_key("missing")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_found(self):
        session = _make_session()
        attempt = MagicMock(spec=PublishAttempt)
        session.execute = AsyncMock(return_value=_make_result(attempt))
        repo = PublishAttemptRepository(session)
        result = await repo.get(uuid.uuid4(), uuid.uuid4())
        assert result == attempt

    @pytest.mark.asyncio
    async def test_list_for_target(self):
        session = _make_session()
        attempts = [MagicMock(spec=PublishAttempt)]
        session.execute = AsyncMock(return_value=_make_list_result(attempts))
        repo = PublishAttemptRepository(session)
        result = await repo.list_for_target(uuid.uuid4())
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_update_status(self):
        session = _make_session()
        session.execute = AsyncMock()
        repo = PublishAttemptRepository(session)
        await repo.update_status(uuid.uuid4(), PublishAttemptStatus.succeeded)
        session.execute.assert_called_once()


class TestEntitySeedRepository:
    @pytest.mark.asyncio
    async def test_create(self):
        session = _make_session()
        repo = EntitySeedRepository(session)
        seed = await repo.create(
            tenant_id=uuid.uuid4(),
            business_id=uuid.uuid4(),
            directory_id=uuid.uuid4(),
            submission_payload={"name": "test"},
        )
        assert isinstance(seed, EntitySeed)

    @pytest.mark.asyncio
    async def test_get_found(self):
        session = _make_session()
        seed = MagicMock(spec=EntitySeed)
        session.execute = AsyncMock(return_value=_make_result(seed))
        repo = EntitySeedRepository(session)
        result = await repo.get(uuid.uuid4(), uuid.uuid4())
        assert result == seed

    @pytest.mark.asyncio
    async def test_get_not_found(self):
        session = _make_session()
        session.execute = AsyncMock(return_value=_make_result(None))
        repo = EntitySeedRepository(session)
        result = await repo.get(uuid.uuid4(), uuid.uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_business_directory(self):
        session = _make_session()
        seed = MagicMock(spec=EntitySeed)
        session.execute = AsyncMock(return_value=_make_result(seed))
        repo = EntitySeedRepository(session)
        result = await repo.get_by_business_directory(uuid.uuid4(), uuid.uuid4())
        assert result == seed

    @pytest.mark.asyncio
    async def test_list_for_business(self):
        session = _make_session()
        seeds = [MagicMock(spec=EntitySeed), MagicMock(spec=EntitySeed)]
        session.execute = AsyncMock(return_value=_make_list_result(seeds))
        repo = EntitySeedRepository(session)
        result = await repo.list_for_business(uuid.uuid4(), uuid.uuid4())
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_update_status(self):
        session = _make_session()
        session.execute = AsyncMock()
        repo = EntitySeedRepository(session)
        await repo.update_status(uuid.uuid4(), EntitySeedStatus.submitted)
        session.execute.assert_called_once()


class TestDirectoryRegistryRepository:
    @pytest.mark.asyncio
    async def test_list_active(self):
        session = _make_session()
        dr = MagicMock(spec=DirectoryRegistry)
        session.execute = AsyncMock(return_value=_make_list_result([dr]))
        repo = DirectoryRegistryRepository(session)
        result = await repo.list_active()
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_by_slug_found(self):
        session = _make_session()
        dr = MagicMock(spec=DirectoryRegistry)
        session.execute = AsyncMock(return_value=_make_result(dr))
        repo = DirectoryRegistryRepository(session)
        result = await repo.get_by_slug("justdial")
        assert result == dr

    @pytest.mark.asyncio
    async def test_get_by_slug_not_found(self):
        session = _make_session()
        session.execute = AsyncMock(return_value=_make_result(None))
        repo = DirectoryRegistryRepository(session)
        result = await repo.get_by_slug("missing")
        assert result is None

    @pytest.mark.asyncio
    async def test_create(self):
        session = _make_session()
        repo = DirectoryRegistryRepository(session)
        dr = await repo.create(
            slug="test-dir",
            name="Test Dir",
            submission_method="api",
            verification_method="scrape",
        )
        assert isinstance(dr, DirectoryRegistry)


class TestVerificationPollRepository:
    @pytest.mark.asyncio
    async def test_create(self):
        session = _make_session()
        repo = VerificationPollRepository(session)
        now = datetime.now(timezone.utc)
        poll = await repo.create(
            tenant_id=uuid.uuid4(),
            scheduled_for=now,
            attempt_index=0,
        )
        assert isinstance(poll, VerificationPoll)

    @pytest.mark.asyncio
    async def test_list_due(self):
        session = _make_session()
        poll = MagicMock(spec=VerificationPoll)
        session.execute = AsyncMock(return_value=_make_list_result([poll]))
        repo = VerificationPollRepository(session)
        result = await repo.list_due(datetime.now(timezone.utc))
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_mark_attempted(self):
        session = _make_session()
        session.execute = AsyncMock()
        repo = VerificationPollRepository(session)
        await repo.mark_attempted(uuid.uuid4(), "verified")
        session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_for_seed(self):
        session = _make_session()
        polls = [MagicMock(spec=VerificationPoll)]
        session.execute = AsyncMock(return_value=_make_list_result(polls))
        repo = VerificationPollRepository(session)
        result = await repo.list_for_seed(uuid.uuid4())
        assert len(result) == 1
