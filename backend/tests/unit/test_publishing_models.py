"""Unit tests for Publishing & Entity Seeding models."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.modules.publishing.models import (
    DirectoryRegistry,
    EntitySeed,
    EntitySeedStatus,
    OAuthToken,
    PublishAttempt,
    PublishAttemptStatus,
    PublishChannel,
    PublishTarget,
    PublishTargetStatus,
    VerificationPoll,
)


class TestPublishChannel:
    def test_all_values(self):
        assert PublishChannel.google_business_profile == "google_business_profile"
        assert PublishChannel.wordpress == "wordpress"
        assert PublishChannel.website_snippet == "website_snippet"
        assert PublishChannel.justdial == "justdial"
        assert PublishChannel.indiamart == "indiamart"
        assert PublishChannel.sulekha == "sulekha"

    def test_is_str(self):
        assert isinstance(PublishChannel.wordpress, str)


class TestPublishTargetStatus:
    def test_all_values(self):
        assert PublishTargetStatus.pending_oauth == "pending_oauth"
        assert PublishTargetStatus.connected == "connected"
        assert PublishTargetStatus.failed == "failed"
        assert PublishTargetStatus.revoked == "revoked"
        assert PublishTargetStatus.disabled == "disabled"


class TestPublishAttemptStatus:
    def test_all_values(self):
        assert PublishAttemptStatus.queued == "queued"
        assert PublishAttemptStatus.in_progress == "in_progress"
        assert PublishAttemptStatus.succeeded == "succeeded"
        assert PublishAttemptStatus.failed_retryable == "failed_retryable"
        assert PublishAttemptStatus.failed_terminal == "failed_terminal"
        assert PublishAttemptStatus.verified == "verified"
        assert PublishAttemptStatus.verification_failed == "verification_failed"
        assert PublishAttemptStatus.awaiting_customer_publish == "awaiting_customer_publish"


class TestEntitySeedStatus:
    def test_all_values(self):
        assert EntitySeedStatus.pending_submission == "pending_submission"
        assert EntitySeedStatus.submitted == "submitted"
        assert EntitySeedStatus.rejected == "rejected"
        assert EntitySeedStatus.verified == "verified"
        assert EntitySeedStatus.lost_visibility == "lost_visibility"
        assert EntitySeedStatus.submission_unconfirmed == "submission_unconfirmed"
        assert EntitySeedStatus.submission_unverified == "submission_unverified"


class TestDirectoryRegistry:
    def test_defaults(self):
        dr = DirectoryRegistry(
            slug="justdial",
            name="JustDial",
            submission_method="api",
            verification_method="scrape",
        )
        assert dr.id is not None
        assert dr.active is True
        assert dr.known_indexed_by_ai is False
        assert dr.verification_config == {}
        assert dr.created_at is not None

    def test_explicit_values(self):
        dr = DirectoryRegistry(
            slug="test-dir",
            name="Test Dir",
            submission_method="manual",
            verification_method="manual",
            active=False,
            known_indexed_by_ai=True,
            notes="some notes",
        )
        assert dr.active is False
        assert dr.known_indexed_by_ai is True
        assert dr.notes == "some notes"


class TestOAuthToken:
    def test_defaults(self):
        now = datetime.now(timezone.utc)
        token = OAuthToken(
            tenant_id=uuid.uuid4(),
            provider="google",
            access_token_encrypted=b"ciphertext",
            refresh_token_encrypted=b"refresh_cipher",
            wrapped_dek=b"wrapped",
            kms_key_version="v1",
            access_token_expires_at=now,
            scope="profile email",
        )
        assert token.id is not None
        assert token.created_at is not None
        assert token.updated_at is not None
        assert token.last_refreshed_at is None


class TestPublishTarget:
    def test_defaults(self):
        target = PublishTarget(
            tenant_id=uuid.uuid4(),
            business_id=uuid.uuid4(),
            channel=PublishChannel.wordpress,
        )
        assert target.id is not None
        assert target.status == PublishTargetStatus.pending_oauth
        assert target.meta == {}
        assert target.created_at is not None
        assert target.updated_at is not None

    def test_custom_status(self):
        target = PublishTarget(
            tenant_id=uuid.uuid4(),
            business_id=uuid.uuid4(),
            channel=PublishChannel.google_business_profile,
            status=PublishTargetStatus.connected,
        )
        assert target.status == PublishTargetStatus.connected


class TestPublishAttempt:
    def test_defaults(self):
        attempt = PublishAttempt(
            tenant_id=uuid.uuid4(),
            business_id=uuid.uuid4(),
            target_id=uuid.uuid4(),
            content_asset_id=uuid.uuid4(),
            brief_id=uuid.uuid4(),
            idempotency_key="abc123",
        )
        assert attempt.id is not None
        assert attempt.status == PublishAttemptStatus.queued
        assert attempt.attempts_count == 0
        assert attempt.created_at is not None


class TestEntitySeed:
    def test_defaults(self):
        seed = EntitySeed(
            tenant_id=uuid.uuid4(),
            business_id=uuid.uuid4(),
            directory_id=uuid.uuid4(),
            submission_payload={"name": "Test Business"},
        )
        assert seed.id is not None
        assert seed.status == EntitySeedStatus.pending_submission
        assert seed.verification_failures == 0
        assert seed.profile_snapshot == {}
        assert seed.created_at is not None
        assert seed.updated_at is not None


class TestVerificationPoll:
    def test_instantiation(self):
        now = datetime.now(timezone.utc)
        poll = VerificationPoll(
            tenant_id=uuid.uuid4(),
            scheduled_for=now,
            attempt_index=0,
        )
        assert poll.id is not None
        assert poll.attempted_at is None
        assert poll.outcome is None
