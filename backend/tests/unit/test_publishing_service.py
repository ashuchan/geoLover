"""Unit tests for PublishService."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.publishing.adapters import PublishResult
from app.modules.publishing.models import (
    EntitySeed,
    EntitySeedStatus,
    PublishAttempt,
    PublishAttemptStatus,
    PublishTarget,
    PublishTargetStatus,
    VerificationPoll,
)
from app.modules.publishing.service import (
    EntitySeedSubmitted,
    OAuthTokenRefreshFailed,
    PublishAttemptFailed,
    PublishAttemptSucceeded,
    PublishService,
    PublishTargetConnected,
)


def _make_session():
    s = MagicMock()
    s.flush = AsyncMock()
    s.add = MagicMock()
    s.execute = AsyncMock()
    return s


def _make_target(**kwargs):
    t = MagicMock(spec=PublishTarget)
    t.id = kwargs.get("id", uuid.uuid4())
    t.tenant_id = kwargs.get("tenant_id", uuid.uuid4())
    t.business_id = kwargs.get("business_id", uuid.uuid4())
    t.channel = kwargs.get("channel", "wordpress")
    t.status = kwargs.get("status", PublishTargetStatus.pending_oauth)
    t.meta = {}
    t.publish_authorized_at = None
    t.revoked_at = None
    t.updated_at = None
    return t


def _make_seed(**kwargs):
    s = MagicMock(spec=EntitySeed)
    s.id = kwargs.get("id", uuid.uuid4())
    s.tenant_id = kwargs.get("tenant_id", uuid.uuid4())
    s.directory_id = kwargs.get("directory_id", uuid.uuid4())
    s.first_verified_at = kwargs.get("first_verified_at", None)
    return s


def _make_attempt(**kwargs):
    a = MagicMock(spec=PublishAttempt)
    a.id = kwargs.get("id", uuid.uuid4())
    a.idempotency_key = kwargs.get("idempotency_key", "key123")
    return a


class TestConnectTarget:
    @pytest.mark.asyncio
    async def test_creates_target_in_pending_oauth(self):
        session = _make_session()
        tenant_id = uuid.uuid4()
        business_id = uuid.uuid4()
        target = _make_target(tenant_id=tenant_id, business_id=business_id)

        with patch(
            "app.modules.publishing.service.PublishTargetRepository.create",
            new=AsyncMock(return_value=target),
        ):
            svc = PublishService(session)
            result = await svc.connect_target(
                tenant_id=tenant_id,
                business_id=business_id,
                channel="wordpress",
                redirect_uri="https://example.com/cb",
            )

        assert result == target
        assert len(svc.pending_events) == 1
        event = svc.pending_events[0]
        assert isinstance(event, PublishTargetConnected)
        assert event.tenant_id == tenant_id
        assert event.channel == "wordpress"

    @pytest.mark.asyncio
    async def test_emits_publish_target_connected(self):
        session = _make_session()
        target = _make_target()

        with patch(
            "app.modules.publishing.service.PublishTargetRepository.create",
            new=AsyncMock(return_value=target),
        ):
            svc = PublishService(session)
            await svc.connect_target(
                tenant_id=uuid.uuid4(),
                business_id=uuid.uuid4(),
                channel="google_business_profile",
                redirect_uri="",
            )

        assert svc.pending_events[0].name == "PublishTargetConnected"


class TestAuthorizePublish:
    @pytest.mark.asyncio
    async def test_sets_publish_authorized_at(self):
        session = _make_session()
        target = _make_target()

        with patch(
            "app.modules.publishing.service.PublishTargetRepository.update_status",
            new=AsyncMock(),
        ), patch(
            "app.modules.publishing.service.PublishTargetRepository.get",
            new=AsyncMock(return_value=target),
        ):
            svc = PublishService(session)
            result = await svc.authorize_publish(
                target_id=target.id,
                tenant_id=target.tenant_id,
            )

        assert result == target
        # publish_authorized_at should have been set on the mock
        assert target.publish_authorized_at is not None


class TestRevokeTarget:
    @pytest.mark.asyncio
    async def test_revoke_calls_update_status_with_revoked_at(self):
        session = _make_session()
        target_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        update_mock = AsyncMock()
        with patch(
            "app.modules.publishing.service.PublishTargetRepository.update_status",
            new=update_mock,
        ):
            svc = PublishService(session)
            await svc.revoke_target(target_id=target_id, tenant_id=tenant_id)

        update_mock.assert_called_once()
        call_kwargs = update_mock.call_args
        assert call_kwargs[0][1] == PublishTargetStatus.revoked
        assert call_kwargs[1]["revoked_at"] is not None

    @pytest.mark.asyncio
    async def test_revoke_emits_no_events(self):
        session = _make_session()

        with patch(
            "app.modules.publishing.service.PublishTargetRepository.update_status",
            new=AsyncMock(),
        ):
            svc = PublishService(session)
            await svc.revoke_target(target_id=uuid.uuid4(), tenant_id=uuid.uuid4())

        assert len(svc.pending_events) == 0


class TestInitiatePublish:
    @pytest.mark.asyncio
    async def test_creates_attempt_with_idempotency_key(self):
        session = _make_session()
        target_id = uuid.uuid4()
        content_asset_id = uuid.uuid4()
        attempt = _make_attempt()
        expected_key = hashlib.sha256(f"{target_id}:{content_asset_id}".encode()).hexdigest()

        with patch(
            "app.modules.publishing.service.PublishAttemptRepository.get_by_idempotency_key",
            new=AsyncMock(return_value=None),
        ), patch(
            "app.modules.publishing.service.PublishAttemptRepository.create",
            new=AsyncMock(return_value=attempt),
        ) as create_mock:
            svc = PublishService(session)
            result = await svc.initiate_publish(
                tenant_id=uuid.uuid4(),
                business_id=uuid.uuid4(),
                target_id=target_id,
                content_asset_id=content_asset_id,
                brief_id=uuid.uuid4(),
            )

        assert result == attempt
        create_mock.assert_called_once()
        call_kwargs = create_mock.call_args[1]
        assert call_kwargs["idempotency_key"] == expected_key

    @pytest.mark.asyncio
    async def test_returns_existing_attempt_on_duplicate(self):
        session = _make_session()
        existing_attempt = _make_attempt()

        with patch(
            "app.modules.publishing.service.PublishAttemptRepository.get_by_idempotency_key",
            new=AsyncMock(return_value=existing_attempt),
        ), patch(
            "app.modules.publishing.service.PublishAttemptRepository.create",
            new=AsyncMock(),
        ) as create_mock:
            svc = PublishService(session)
            result = await svc.initiate_publish(
                tenant_id=uuid.uuid4(),
                business_id=uuid.uuid4(),
                target_id=uuid.uuid4(),
                content_asset_id=uuid.uuid4(),
                brief_id=uuid.uuid4(),
            )

        assert result == existing_attempt
        create_mock.assert_not_called()


class TestRecordPublishResult:
    @pytest.mark.asyncio
    async def test_success_emits_succeeded_event(self):
        session = _make_session()
        attempt_id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        result = PublishResult(
            success=True,
            external_object_id="ext-123",
            public_url="https://mybusiness.google.com/...",
            failure_reason=None,
            is_retryable=False,
        )

        with patch(
            "app.modules.publishing.service.PublishAttemptRepository.update_status",
            new=AsyncMock(),
        ):
            svc = PublishService(session)
            await svc.record_publish_result(
                attempt_id=attempt_id,
                tenant_id=tenant_id,
                result=result,
            )

        assert len(svc.pending_events) == 1
        event = svc.pending_events[0]
        assert isinstance(event, PublishAttemptSucceeded)
        assert event.attempt_id == attempt_id
        assert event.public_url == "https://mybusiness.google.com/..."

    @pytest.mark.asyncio
    async def test_failure_retryable_emits_failed_event(self):
        session = _make_session()
        result = PublishResult(
            success=False,
            external_object_id=None,
            public_url=None,
            failure_reason="Timeout",
            is_retryable=True,
        )

        with patch(
            "app.modules.publishing.service.PublishAttemptRepository.update_status",
            new=AsyncMock(),
        ) as update_mock:
            svc = PublishService(session)
            await svc.record_publish_result(
                attempt_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                result=result,
            )

        event = svc.pending_events[0]
        assert isinstance(event, PublishAttemptFailed)
        assert event.is_terminal is False
        # Verify status was failed_retryable
        call_args = update_mock.call_args
        assert call_args[0][1] == PublishAttemptStatus.failed_retryable

    @pytest.mark.asyncio
    async def test_failure_terminal_emits_failed_event(self):
        session = _make_session()
        result = PublishResult(
            success=False,
            external_object_id=None,
            public_url=None,
            failure_reason="Invalid credentials",
            is_retryable=False,
        )

        with patch(
            "app.modules.publishing.service.PublishAttemptRepository.update_status",
            new=AsyncMock(),
        ) as update_mock:
            svc = PublishService(session)
            await svc.record_publish_result(
                attempt_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                result=result,
            )

        event = svc.pending_events[0]
        assert isinstance(event, PublishAttemptFailed)
        assert event.is_terminal is True
        call_args = update_mock.call_args
        assert call_args[0][1] == PublishAttemptStatus.failed_terminal


class TestCreateEntitySeed:
    @pytest.mark.asyncio
    async def test_creates_seed_and_emits_event(self):
        session = _make_session()
        seed = _make_seed()

        with patch(
            "app.modules.publishing.service.EntitySeedRepository.create",
            new=AsyncMock(return_value=seed),
        ):
            svc = PublishService(session)
            result = await svc.create_entity_seed(
                tenant_id=uuid.uuid4(),
                business_id=uuid.uuid4(),
                directory_id=uuid.uuid4(),
                submission_payload={"name": "My Business"},
            )

        assert result == seed
        assert len(svc.pending_events) == 1
        event = svc.pending_events[0]
        assert isinstance(event, EntitySeedSubmitted)
        assert event.seed_id == seed.id


class TestRecordSeedSubmitted:
    @pytest.mark.asyncio
    async def test_updates_to_submitted_with_timestamp(self):
        session = _make_session()
        seed_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        with patch(
            "app.modules.publishing.service.EntitySeedRepository.update_status",
            new=AsyncMock(),
        ) as update_mock:
            svc = PublishService(session)
            await svc.record_seed_submitted(
                seed_id=seed_id,
                tenant_id=tenant_id,
                external_listing_id="ext-456",
            )

        update_mock.assert_called_once()
        call_args = update_mock.call_args
        assert call_args[0][1] == EntitySeedStatus.submitted
        assert "submitted_at" in call_args[1]
        assert "external_listing_id" in call_args[1]


class TestRecordSeedVerified:
    @pytest.mark.asyncio
    async def test_first_verification_sets_first_verified_at(self):
        session = _make_session()
        seed_id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        seed = _make_seed(id=seed_id, tenant_id=tenant_id, first_verified_at=None)

        with patch(
            "app.modules.publishing.service.EntitySeedRepository.get",
            new=AsyncMock(return_value=seed),
        ), patch(
            "app.modules.publishing.service.EntitySeedRepository.update_status",
            new=AsyncMock(),
        ) as update_mock:
            svc = PublishService(session)
            await svc.record_seed_verified(seed_id=seed_id, tenant_id=tenant_id)

        call_kwargs = update_mock.call_args[1]
        assert "first_verified_at" in call_kwargs
        assert "last_verified_at" in call_kwargs

    @pytest.mark.asyncio
    async def test_second_verification_only_updates_last_verified_at(self):
        session = _make_session()
        seed_id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        already_verified = datetime(2026, 1, 1, tzinfo=timezone.utc)
        seed = _make_seed(
            id=seed_id,
            tenant_id=tenant_id,
            first_verified_at=already_verified,
        )

        with patch(
            "app.modules.publishing.service.EntitySeedRepository.get",
            new=AsyncMock(return_value=seed),
        ), patch(
            "app.modules.publishing.service.EntitySeedRepository.update_status",
            new=AsyncMock(),
        ) as update_mock:
            svc = PublishService(session)
            await svc.record_seed_verified(seed_id=seed_id, tenant_id=tenant_id)

        call_kwargs = update_mock.call_args[1]
        assert "last_verified_at" in call_kwargs
        assert "first_verified_at" not in call_kwargs


class TestScheduleVerificationPolls:
    @pytest.mark.asyncio
    async def test_creates_3_polls(self):
        session = _make_session()
        base_time = datetime.now(timezone.utc)
        polls_created = []

        async def mock_create(self_repo, **kwargs):
            poll = MagicMock(spec=VerificationPoll)
            poll.scheduled_for = kwargs["scheduled_for"]
            poll.attempt_index = kwargs["attempt_index"]
            polls_created.append(poll)
            return poll

        with patch(
            "app.modules.publishing.service.VerificationPollRepository.create",
            new=mock_create,
        ):
            svc = PublishService(session)
            polls = await svc.schedule_verification_polls(
                tenant_id=uuid.uuid4(),
                publish_attempt_id=uuid.uuid4(),
                base_time=base_time,
            )

        assert len(polls) == 3
        from datetime import timedelta
        assert polls[0].scheduled_for == base_time + timedelta(minutes=15)
        assert polls[1].scheduled_for == base_time + timedelta(hours=1)
        assert polls[2].scheduled_for == base_time + timedelta(hours=24)


class TestScheduleSeedVerificationPolls:
    @pytest.mark.asyncio
    async def test_creates_5_polls(self):
        session = _make_session()
        base_time = datetime.now(timezone.utc)
        polls_created = []

        async def mock_create(self_repo, **kwargs):
            poll = MagicMock(spec=VerificationPoll)
            poll.scheduled_for = kwargs["scheduled_for"]
            poll.attempt_index = kwargs["attempt_index"]
            polls_created.append(poll)
            return poll

        with patch(
            "app.modules.publishing.service.VerificationPollRepository.create",
            new=mock_create,
        ):
            svc = PublishService(session)
            polls = await svc.schedule_seed_verification_polls(
                tenant_id=uuid.uuid4(),
                seed_id=uuid.uuid4(),
                base_time=base_time,
            )

        assert len(polls) == 5
        from datetime import timedelta
        assert polls[0].scheduled_for == base_time + timedelta(hours=24)
        assert polls[1].scheduled_for == base_time + timedelta(hours=72)
        assert polls[2].scheduled_for == base_time + timedelta(days=7)
        assert polls[3].scheduled_for == base_time + timedelta(days=14)
        assert polls[4].scheduled_for == base_time + timedelta(days=30)


class TestDomainEvents:
    def test_publish_target_connected(self):
        e = PublishTargetConnected(uuid.uuid4(), uuid.uuid4(), "wordpress")
        assert e.name == "PublishTargetConnected"

    def test_publish_attempt_succeeded(self):
        e = PublishAttemptSucceeded(uuid.uuid4(), uuid.uuid4(), "https://example.com")
        assert e.name == "PublishAttemptSucceeded"

    def test_publish_attempt_failed(self):
        e = PublishAttemptFailed(uuid.uuid4(), uuid.uuid4(), "timeout", True)
        assert e.name == "PublishAttemptFailed"

    def test_entity_seed_submitted(self):
        e = EntitySeedSubmitted(uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
        assert e.name == "EntitySeedSubmitted"

    def test_oauth_token_refresh_failed(self):
        e = OAuthTokenRefreshFailed(uuid.uuid4(), uuid.uuid4(), False)
        assert e.name == "OAuthTokenRefreshFailed"
