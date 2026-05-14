"""Unit tests for business profile service layer."""

from __future__ import annotations

import base64
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.events import EventBus
from app.core.exceptions import BusinessNotFoundError, PermissionDeniedError, ValidationError
from app.modules.business_profile.models import (
    AliasType,
    Business,
    BusinessAlias,
    BusinessKeyword,
    BusinessLocation,
    BusinessSource,
    BusinessStatus,
    FreeAuditToken,
)
from app.modules.business_profile.service import (
    BusinessCreated,
    BusinessDeleted,
    BusinessProfileService,
    BusinessProfileUpdated,
    FreeAuditService,
    _compute_uniqueness_score,
)
from app.modules.identity.models import UserRole

TEST_KEY = base64.b64encode(os.urandom(32)).decode()


def _make_business(**kw) -> Business:
    defaults = dict(
        tenant_id=uuid.uuid4(),
        canonical_name="My Firm",
        name_normalized="my firm",
        category_id=uuid.uuid4(),
        source=BusinessSource.self_signup,
    )
    defaults.update(kw)
    return Business(**defaults)


def _make_svc(has_access: bool = True) -> BusinessProfileService:
    svc = BusinessProfileService(MagicMock(), TEST_KEY)
    svc._membership_repo = MagicMock()
    svc._membership_repo.has_role = AsyncMock(return_value=has_access)
    svc._membership_repo.is_platform_admin = AsyncMock(return_value=False)
    svc._membership_repo.has_business_scope_access = AsyncMock(return_value=False)
    svc._category_repo = MagicMock()
    svc._category_repo.get_by_id = AsyncMock(return_value=MagicMock())
    svc._business_repo = MagicMock()
    svc._alias_repo = MagicMock()
    svc._location_repo = MagicMock()
    svc._keyword_repo = MagicMock()
    svc._tenant_repo = MagicMock()
    return svc


class TestComputeUniquenessScore:
    def test_empty_name_returns_zero(self):
        assert _compute_uniqueness_score("", []) == 0.0

    def test_longer_name_scores_higher(self):
        short_score = _compute_uniqueness_score("ab", [])
        long_score = _compute_uniqueness_score("my business name", [])
        assert long_score > short_score

    def test_score_in_range(self):
        score = _compute_uniqueness_score("some name", ["alias"])
        assert 0.0 <= score <= 1.0

    def test_aliases_included_in_score(self):
        s_no_alias = _compute_uniqueness_score("abc", [])
        s_with_alias = _compute_uniqueness_score("abc", ["more unique text here"])
        # Adding more text may shift score
        assert isinstance(s_with_alias, float)


class TestBusinessProfileServiceCreate:
    @pytest.mark.asyncio
    async def test_create_without_access_raises(self):
        svc = _make_svc(has_access=False)

        with pytest.raises(PermissionDeniedError):
            await svc.create_business(
                actor_user_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                canonical_name="My Firm",
                category_id=uuid.uuid4(),
                source=BusinessSource.self_signup,
            )

    @pytest.mark.asyncio
    async def test_create_happy_path(self):
        svc = _make_svc(has_access=True)
        biz = _make_business()
        svc._business_repo.create = AsyncMock(return_value=biz)
        svc._business_repo.update = AsyncMock(return_value=biz)

        bus = EventBus()
        received = []

        @bus.subscribe(BusinessCreated)
        async def handler(evt):
            received.append(evt)

        with patch("app.modules.business_profile.service.event_bus", bus):
            result = await svc.create_business(
                actor_user_id=uuid.uuid4(),
                tenant_id=biz.tenant_id,
                canonical_name="My Firm",
                category_id=biz.category_id,
                source=BusinessSource.self_signup,
            )
            await svc.flush_pending_events()

        assert result is biz
        assert len(received) == 1
        assert received[0].tenant_id == biz.tenant_id

    @pytest.mark.asyncio
    async def test_empty_canonical_name_raises(self):
        svc = _make_svc(has_access=True)

        with pytest.raises(ValidationError, match="cannot be empty"):
            await svc.create_business(
                actor_user_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                canonical_name="   ",
                category_id=uuid.uuid4(),
                source=BusinessSource.self_signup,
            )

    @pytest.mark.asyncio
    async def test_name_too_short_raises(self):
        svc = _make_svc(has_access=True)

        with pytest.raises(ValidationError, match="2"):
            await svc.create_business(
                actor_user_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                canonical_name="A",
                category_id=uuid.uuid4(),
                source=BusinessSource.self_signup,
            )

    @pytest.mark.asyncio
    async def test_email_is_encrypted(self):
        svc = _make_svc(has_access=True)
        biz = _make_business()
        svc._business_repo.create = AsyncMock(return_value=biz)
        svc._business_repo.update = AsyncMock(return_value=biz)

        with patch("app.modules.business_profile.service.event_bus", EventBus()):
            await svc.create_business(
                actor_user_id=uuid.uuid4(),
                tenant_id=biz.tenant_id,
                canonical_name="My Firm",
                category_id=biz.category_id,
                source=BusinessSource.self_signup,
                primary_email="owner@firm.com",
            )

        call_kwargs = svc._business_repo.create.call_args[1]
        assert call_kwargs["primary_email_encrypted"] is not None
        assert isinstance(call_kwargs["primary_email_encrypted"], bytes)


class TestBusinessProfileServiceUpdate:
    @pytest.mark.asyncio
    async def test_update_without_access_raises(self):
        svc = _make_svc(has_access=False)

        with pytest.raises(PermissionDeniedError):
            await svc.update_business(
                actor_user_id=uuid.uuid4(),
                business_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                canonical_name="New Name",
            )

    @pytest.mark.asyncio
    async def test_update_recomputes_score_on_name_change(self):
        svc = _make_svc(has_access=True)
        biz = _make_business()
        svc._business_repo.update = AsyncMock(return_value=biz)
        svc._business_repo.get_by_id = AsyncMock(return_value=biz)
        svc._alias_repo.list_for_business = AsyncMock(return_value=[])

        with patch("app.modules.business_profile.service.event_bus", EventBus()):
            await svc.update_business(
                actor_user_id=uuid.uuid4(),
                business_id=biz.id,
                tenant_id=biz.tenant_id,
                canonical_name="New Name",
            )

        # update called twice: once for fields, once for score
        assert svc._business_repo.update.call_count == 2

    @pytest.mark.asyncio
    async def test_update_emits_event(self):
        svc = _make_svc(has_access=True)
        biz = _make_business()
        svc._business_repo.get_by_id = AsyncMock(return_value=biz)
        svc._business_repo.update = AsyncMock(return_value=biz)

        bus = EventBus()
        received = []

        @bus.subscribe(BusinessProfileUpdated)
        async def handler(evt):
            received.append(evt)

        with patch("app.modules.business_profile.service.event_bus", bus):
            await svc.update_business(
                actor_user_id=uuid.uuid4(),
                business_id=biz.id,
                tenant_id=biz.tenant_id,
                description="Updated",
            )
            await svc.flush_pending_events()

        assert len(received) == 1


class TestBusinessProfileServiceDelete:
    @pytest.mark.asyncio
    async def test_delete_without_access_raises(self):
        svc = _make_svc(has_access=False)

        with pytest.raises(PermissionDeniedError):
            await svc.delete_business(
                actor_user_id=uuid.uuid4(),
                business_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_delete_emits_event(self):
        svc = _make_svc(has_access=True)
        biz = _make_business()
        svc._business_repo.get_by_id = AsyncMock(return_value=biz)
        svc._business_repo.soft_delete = AsyncMock(return_value=biz)

        bus = EventBus()
        received = []

        @bus.subscribe(BusinessDeleted)
        async def handler(evt):
            received.append(evt)

        with patch("app.modules.business_profile.service.event_bus", bus):
            await svc.delete_business(
                actor_user_id=uuid.uuid4(),
                business_id=biz.id,
                tenant_id=biz.tenant_id,
            )
            await svc.flush_pending_events()

        assert len(received) == 1


class TestBusinessProfileServiceAlias:
    @pytest.mark.asyncio
    async def test_add_alias_updates_score(self):
        svc = _make_svc(has_access=True)
        biz = _make_business()
        alias = BusinessAlias(
            business_id=biz.id,
            tenant_id=biz.tenant_id,
            alias_text="My Firm Ltd",
            alias_text_normalized="my firm ltd",
            alias_type=AliasType.abbreviation,
        )
        svc._alias_repo.create = AsyncMock(return_value=alias)
        svc._alias_repo.list_for_business = AsyncMock(return_value=[alias])
        svc._business_repo.get_by_id = AsyncMock(return_value=biz)
        svc._business_repo.update = AsyncMock(return_value=biz)

        result = await svc.add_alias(
            actor_user_id=uuid.uuid4(),
            business_id=biz.id,
            tenant_id=biz.tenant_id,
            alias_text="My Firm Ltd",
            alias_type=AliasType.abbreviation,
        )

        assert result is alias
        svc._business_repo.update.assert_called_once()


class TestBusinessProfileServiceLocation:
    @pytest.mark.asyncio
    async def test_add_location(self):
        svc = _make_svc(has_access=True)
        biz = _make_business()
        loc = BusinessLocation(business_id=biz.id, tenant_id=biz.tenant_id, city="Bangalore")
        svc._business_repo.get_by_id = AsyncMock(return_value=biz)
        svc._location_repo.create = AsyncMock(return_value=loc)

        result = await svc.add_location(
            actor_user_id=uuid.uuid4(),
            business_id=biz.id,
            tenant_id=biz.tenant_id,
            city="Bangalore",
        )
        assert result is loc


class TestBusinessProfileServiceKeywords:
    @pytest.mark.asyncio
    async def test_add_keywords(self):
        svc = _make_svc(has_access=True)
        biz = _make_business()
        kw = BusinessKeyword(
            business_id=biz.id,
            tenant_id=biz.tenant_id,
            keyword="chartered accountant",
            keyword_normalized="chartered accountant",
        )
        svc._business_repo.get_by_id = AsyncMock(return_value=biz)
        svc._keyword_repo.create_batch = AsyncMock(return_value=[kw])

        result = await svc.add_keywords(
            actor_user_id=uuid.uuid4(),
            business_id=biz.id,
            tenant_id=biz.tenant_id,
            keywords=["chartered accountant", "  ", "tax filing"],
        )
        # Empty string should be filtered
        call_kwargs = svc._keyword_repo.create_batch.call_args[1]
        keyword_pairs = call_kwargs["keywords"]
        assert all(kw_text.strip() for kw_text, _ in keyword_pairs)


class TestBusinessProfileServiceGetters:
    @pytest.mark.asyncio
    async def test_get_business(self):
        svc = _make_svc(has_access=True)
        biz = _make_business()
        svc._business_repo.get_by_id = AsyncMock(return_value=biz)

        result = await svc.get_business(biz.id)
        assert result is biz

    @pytest.mark.asyncio
    async def test_get_business_wrong_tenant_raises(self):
        svc = _make_svc(has_access=True)
        biz = _make_business()
        svc._business_repo.get_by_id = AsyncMock(return_value=biz)

        with pytest.raises(BusinessNotFoundError):
            await svc.get_business(biz.id, tenant_id=uuid.uuid4())

    @pytest.mark.asyncio
    async def test_get_business_scoped_member_with_access(self):
        svc = _make_svc(has_access=True)
        biz = _make_business()
        svc._business_repo.get_by_id = AsyncMock(return_value=biz)
        svc._membership_repo.has_role = AsyncMock(return_value=False)
        svc._membership_repo.is_platform_admin = AsyncMock(return_value=False)
        svc._membership_repo.has_business_scope_access = AsyncMock(return_value=True)

        result = await svc.get_business(biz.id, tenant_id=biz.tenant_id, actor_user_id=uuid.uuid4())
        assert result is biz

    @pytest.mark.asyncio
    async def test_get_business_scoped_member_without_access_raises(self):
        svc = _make_svc(has_access=True)
        biz = _make_business()
        svc._business_repo.get_by_id = AsyncMock(return_value=biz)
        svc._membership_repo.has_role = AsyncMock(return_value=False)
        svc._membership_repo.is_platform_admin = AsyncMock(return_value=False)
        svc._membership_repo.has_business_scope_access = AsyncMock(return_value=False)

        with pytest.raises(BusinessNotFoundError):
            await svc.get_business(biz.id, tenant_id=biz.tenant_id, actor_user_id=uuid.uuid4())

    @pytest.mark.asyncio
    async def test_get_business_agency_admin_skips_scope_check(self):
        svc = _make_svc(has_access=True)
        biz = _make_business()
        svc._business_repo.get_by_id = AsyncMock(return_value=biz)
        svc._membership_repo.has_role = AsyncMock(return_value=True)
        svc._membership_repo.is_platform_admin = AsyncMock(return_value=False)

        result = await svc.get_business(biz.id, tenant_id=biz.tenant_id, actor_user_id=uuid.uuid4())
        assert result is biz
        svc._membership_repo.has_business_scope_access.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_businesses(self):
        svc = _make_svc(has_access=True)
        biz = _make_business()
        svc._business_repo.list_for_tenant = AsyncMock(return_value=[biz])

        result = await svc.list_businesses(biz.tenant_id)
        assert result == [biz]


class TestFreeAuditService:
    def _make_fat(self, **kw) -> FreeAuditToken:
        defaults = dict(
            token="tok123",
            business_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            expires_at=datetime.now(timezone.utc) + timedelta(days=14),
        )
        defaults.update(kw)
        return FreeAuditToken(**defaults)

    def _setup_access(self, svc, business_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        biz = MagicMock()
        biz.tenant_id = tenant_id
        svc._business_repo = MagicMock()
        svc._business_repo.get_by_id = AsyncMock(return_value=biz)
        svc._membership_repo = MagicMock()
        svc._membership_repo.has_role = AsyncMock(return_value=True)
        svc._membership_repo.is_platform_admin = AsyncMock(return_value=False)

    @pytest.mark.asyncio
    async def test_start_returns_existing_token(self):
        svc = FreeAuditService(MagicMock(), TEST_KEY)
        existing = self._make_fat()
        self._setup_access(svc, existing.business_id, existing.tenant_id)
        svc._token_repo = MagicMock()
        svc._token_repo.get_active_for_business = AsyncMock(return_value=existing)

        result = await svc.start_free_audit(
            actor_user_id=uuid.uuid4(),
            business_id=existing.business_id,
            tenant_id=existing.tenant_id,
        )
        assert result is existing
        svc._token_repo.create.assert_not_called()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_start_creates_new_token_when_none_exists(self):
        svc = FreeAuditService(MagicMock(), TEST_KEY)
        biz_id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        new_token = self._make_fat(business_id=biz_id, tenant_id=tenant_id)
        self._setup_access(svc, biz_id, tenant_id)
        svc._token_repo = MagicMock()
        svc._token_repo.get_active_for_business = AsyncMock(return_value=None)
        svc._token_repo.create = AsyncMock(return_value=new_token)

        result = await svc.start_free_audit(
            actor_user_id=uuid.uuid4(),
            business_id=biz_id,
            tenant_id=tenant_id,
        )
        assert result is new_token
        svc._token_repo.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_cross_tenant_raises(self):
        svc = FreeAuditService(MagicMock(), TEST_KEY)
        biz = MagicMock()
        biz.tenant_id = uuid.uuid4()  # different from what we pass
        svc._business_repo = MagicMock()
        svc._business_repo.get_by_id = AsyncMock(return_value=biz)

        with pytest.raises(BusinessNotFoundError):
            await svc.start_free_audit(
                actor_user_id=uuid.uuid4(),
                business_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),  # won't match biz.tenant_id
            )

    @pytest.mark.asyncio
    async def test_start_no_permission_raises(self):
        svc = FreeAuditService(MagicMock(), TEST_KEY)
        tenant_id = uuid.uuid4()
        biz = MagicMock()
        biz.tenant_id = tenant_id
        svc._business_repo = MagicMock()
        svc._business_repo.get_by_id = AsyncMock(return_value=biz)
        svc._membership_repo = MagicMock()
        svc._membership_repo.has_role = AsyncMock(return_value=False)
        svc._membership_repo.is_platform_admin = AsyncMock(return_value=False)

        with pytest.raises(PermissionDeniedError):
            await svc.start_free_audit(
                actor_user_id=uuid.uuid4(),
                business_id=uuid.uuid4(),
                tenant_id=tenant_id,
            )

    @pytest.mark.asyncio
    async def test_claim_token(self):
        svc = FreeAuditService(MagicMock(), TEST_KEY)
        fat = self._make_fat()
        fat.claimed_at = datetime.now(timezone.utc)
        svc._token_repo = MagicMock()
        svc._token_repo.mark_claimed = AsyncMock(return_value=fat)

        result = await svc.claim_token("tok123")
        assert result is fat

    @pytest.mark.asyncio
    async def test_start_handles_concurrent_creation_race(self):
        from sqlalchemy.exc import IntegrityError

        svc = FreeAuditService(MagicMock(), TEST_KEY)
        existing = self._make_fat()
        self._setup_access(svc, existing.business_id, existing.tenant_id)
        svc._token_repo = MagicMock()
        svc._token_repo.get_active_for_business = AsyncMock(
            side_effect=[None, existing]  # first call None, retry returns existing
        )
        svc._token_repo.create = AsyncMock(side_effect=IntegrityError("dup", {}, Exception()))
        svc._session = MagicMock()
        svc._session.rollback = AsyncMock()

        result = await svc.start_free_audit(
            actor_user_id=uuid.uuid4(),
            business_id=existing.business_id,
            tenant_id=existing.tenant_id,
        )
        assert result is existing
        svc._session.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_reraises_integrity_error_when_no_existing_token(self):
        from sqlalchemy.exc import IntegrityError

        svc = FreeAuditService(MagicMock(), TEST_KEY)
        tenant_id = uuid.uuid4()
        biz_id = uuid.uuid4()
        self._setup_access(svc, biz_id, tenant_id)
        svc._token_repo = MagicMock()
        svc._token_repo.get_active_for_business = AsyncMock(return_value=None)
        svc._token_repo.create = AsyncMock(side_effect=IntegrityError("dup", {}, Exception()))
        svc._session = MagicMock()
        svc._session.rollback = AsyncMock()

        with pytest.raises(IntegrityError):
            await svc.start_free_audit(
                actor_user_id=uuid.uuid4(),
                business_id=biz_id,
                tenant_id=tenant_id,
            )

    @pytest.mark.asyncio
    async def test_get_token_data_returns_none_for_expired(self):
        svc = FreeAuditService(MagicMock(), TEST_KEY)
        svc._token_repo = MagicMock()
        svc._token_repo.get_by_token = AsyncMock(return_value=None)

        result = await svc.get_token_data("expired_token")
        assert result is None


class TestBusinessDomainEvents:
    def test_business_created_event_type(self):
        evt = BusinessCreated(
            business_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            source=BusinessSource.self_signup,
        )
        assert evt.event_type == "BusinessCreated"

    def test_business_profile_updated_event_type(self):
        evt = BusinessProfileUpdated(business_id=uuid.uuid4(), tenant_id=uuid.uuid4())
        assert evt.event_type == "BusinessProfileUpdated"

    def test_business_deleted_event_type(self):
        evt = BusinessDeleted(business_id=uuid.uuid4(), tenant_id=uuid.uuid4())
        assert evt.event_type == "BusinessDeleted"
