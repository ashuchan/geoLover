"""Unit tests for business profile repository layer — mock-based, no live DB."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import BusinessNotFoundError
from app.modules.business_profile.models import (
    AliasType,
    Business,
    BusinessAlias,
    BusinessKeyword,
    BusinessLocation,
    BusinessSource,
    BusinessStatus,
    CompetitorSource,
    FreeAuditToken,
    KeywordSource,
)
from app.modules.business_profile.repository import (
    BusinessAliasRepository,
    BusinessKeywordRepository,
    BusinessLocationRepository,
    BusinessRepository,
    CategoryRepository,
    FreeAuditTokenRepository,
)
from app.modules.categories.models import Category


def _mock_session() -> MagicMock:
    s = MagicMock()
    s.execute = AsyncMock()
    s.flush = AsyncMock()
    s.delete = AsyncMock()
    s.add = MagicMock()
    return s


def _scalar_result(value):
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


def _scalars_result(values):
    r = MagicMock()
    r.scalars.return_value.all.return_value = values
    return r


def _make_business(**kw) -> Business:
    defaults = dict(
        tenant_id=uuid.uuid4(),
        canonical_name="Acme Corp",
        name_normalized="acme corp",
        category_id=uuid.uuid4(),
        source=BusinessSource.self_signup,
    )
    defaults.update(kw)
    return Business(**defaults)


# ── BusinessRepository ────────────────────────────────────────────────────────


class TestBusinessRepository:
    @pytest.mark.asyncio
    async def test_get_by_id_found(self):
        repo = BusinessRepository(_mock_session())
        biz = _make_business()
        repo._session.execute = AsyncMock(return_value=_scalar_result(biz))

        result = await repo.get_by_id(biz.id)
        assert result is biz

    @pytest.mark.asyncio
    async def test_get_by_id_not_found_raises(self):
        repo = BusinessRepository(_mock_session())
        repo._session.execute = AsyncMock(return_value=_scalar_result(None))

        with pytest.raises(BusinessNotFoundError):
            await repo.get_by_id(uuid.uuid4())

    @pytest.mark.asyncio
    async def test_list_for_tenant_no_status_filter(self):
        repo = BusinessRepository(_mock_session())
        biz = _make_business()
        repo._session.execute = AsyncMock(return_value=_scalars_result([biz]))

        result = await repo.list_for_tenant(biz.tenant_id)
        assert result == [biz]

    @pytest.mark.asyncio
    async def test_list_for_tenant_with_status_filter(self):
        repo = BusinessRepository(_mock_session())
        biz = _make_business()
        repo._session.execute = AsyncMock(return_value=_scalars_result([biz]))

        result = await repo.list_for_tenant(biz.tenant_id, status=BusinessStatus.trial)
        assert result == [biz]

    @pytest.mark.asyncio
    async def test_create_business(self):
        repo = BusinessRepository(_mock_session())
        repo._session.flush = AsyncMock()

        result = await repo.create(
            tenant_id=uuid.uuid4(),
            canonical_name="My Firm",
            name_normalized="my firm",
            category_id=uuid.uuid4(),
            source=BusinessSource.self_signup,
        )
        repo._session.add.assert_called_once()
        repo._session.flush.assert_called_once()
        assert isinstance(result, Business)

    @pytest.mark.asyncio
    async def test_create_business_with_email(self):
        repo = BusinessRepository(_mock_session())
        repo._session.flush = AsyncMock()

        result = await repo.create(
            tenant_id=uuid.uuid4(),
            canonical_name="My Firm",
            name_normalized="my firm",
            category_id=uuid.uuid4(),
            source=BusinessSource.self_signup,
            primary_email_encrypted=b"encrypted",
        )
        assert result.primary_email_encrypted == b"encrypted"

    @pytest.mark.asyncio
    async def test_update_canonical_name(self):
        repo = BusinessRepository(_mock_session())
        biz = _make_business()
        repo._session.execute = AsyncMock(return_value=_scalar_result(biz))
        repo._session.flush = AsyncMock()

        result = await repo.update(biz.id, canonical_name="New Name")
        assert result.canonical_name == "New Name"

    @pytest.mark.asyncio
    async def test_update_status(self):
        repo = BusinessRepository(_mock_session())
        biz = _make_business()
        repo._session.execute = AsyncMock(return_value=_scalar_result(biz))
        repo._session.flush = AsyncMock()

        result = await repo.update(biz.id, status=BusinessStatus.active)
        assert result.status == BusinessStatus.active

    @pytest.mark.asyncio
    async def test_update_uniqueness_score(self):
        repo = BusinessRepository(_mock_session())
        biz = _make_business()
        repo._session.execute = AsyncMock(return_value=_scalar_result(biz))
        repo._session.flush = AsyncMock()

        result = await repo.update(biz.id, identity_uniqueness_score=0.75)
        assert result.identity_uniqueness_score == 0.75

    @pytest.mark.asyncio
    async def test_update_all_fields(self):
        repo = BusinessRepository(_mock_session())
        biz = _make_business()
        repo._session.execute = AsyncMock(return_value=_scalar_result(biz))
        repo._session.flush = AsyncMock()
        loc_id = uuid.uuid4()

        result = await repo.update(
            biz.id,
            canonical_name="Updated",
            name_normalized="updated",
            description="A firm",
            website_url="https://firm.com",
            status=BusinessStatus.active,
            primary_email_encrypted=b"enc",
            primary_phone_encrypted=b"phone",
            identity_uniqueness_score=0.9,
            primary_location_id=loc_id,
        )
        assert result.canonical_name == "Updated"
        assert result.description == "A firm"
        assert result.primary_location_id == loc_id

    @pytest.mark.asyncio
    async def test_soft_delete(self):
        repo = BusinessRepository(_mock_session())
        biz = _make_business()
        repo._session.execute = AsyncMock(return_value=_scalar_result(biz))
        repo._session.flush = AsyncMock()

        result = await repo.soft_delete(biz.id)
        assert result.deleted_at is not None
        assert result.status == BusinessStatus.deleted


# ── BusinessAliasRepository ───────────────────────────────────────────────────


class TestBusinessAliasRepository:
    @pytest.mark.asyncio
    async def test_list_for_business(self):
        repo = BusinessAliasRepository(_mock_session())
        biz_id = uuid.uuid4()
        alias = BusinessAlias(
            business_id=biz_id,
            tenant_id=uuid.uuid4(),
            alias_text="Acme Ltd",
            alias_text_normalized="acme ltd",
            alias_type=AliasType.abbreviation,
        )
        repo._session.execute = AsyncMock(return_value=_scalars_result([alias]))

        result = await repo.list_for_business(biz_id)
        assert result == [alias]

    @pytest.mark.asyncio
    async def test_create_alias(self):
        repo = BusinessAliasRepository(_mock_session())
        repo._session.flush = AsyncMock()

        result = await repo.create(
            business_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            alias_text="Acme Ltd",
            alias_text_normalized="acme ltd",
            alias_type=AliasType.colloquial,
            confidence=0.9,
        )
        repo._session.add.assert_called_once()
        repo._session.flush.assert_called_once()
        assert isinstance(result, BusinessAlias)
        assert result.confidence == 0.9

    @pytest.mark.asyncio
    async def test_delete_alias(self):
        repo = BusinessAliasRepository(_mock_session())
        alias = BusinessAlias(
            business_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            alias_text="Old",
            alias_text_normalized="old",
            alias_type=AliasType.former_name,
        )
        repo._session.execute = AsyncMock(return_value=_scalar_result(alias))
        repo._session.flush = AsyncMock()

        await repo.delete(alias.id, tenant_id=alias.tenant_id)
        repo._session.delete.assert_called_once_with(alias)
        repo._session.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_alias_not_found_raises(self):
        repo = BusinessAliasRepository(_mock_session())
        repo._session.execute = AsyncMock(return_value=_scalar_result(None))

        with pytest.raises(BusinessNotFoundError):
            await repo.delete(uuid.uuid4(), tenant_id=uuid.uuid4())


# ── BusinessLocationRepository ────────────────────────────────────────────────


class TestBusinessLocationRepository:
    @pytest.mark.asyncio
    async def test_list_for_business(self):
        repo = BusinessLocationRepository(_mock_session())
        biz_id = uuid.uuid4()
        loc = BusinessLocation(business_id=biz_id, tenant_id=uuid.uuid4(), city="Mumbai")
        repo._session.execute = AsyncMock(return_value=_scalars_result([loc]))

        result = await repo.list_for_business(biz_id)
        assert result == [loc]

    @pytest.mark.asyncio
    async def test_create_location_minimal(self):
        repo = BusinessLocationRepository(_mock_session())
        repo._session.flush = AsyncMock()

        result = await repo.create(
            business_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            city="Chennai",
        )
        repo._session.add.assert_called_once()
        repo._session.flush.assert_called_once()
        assert isinstance(result, BusinessLocation)
        assert result.city == "Chennai"

    @pytest.mark.asyncio
    async def test_create_location_full(self):
        repo = BusinessLocationRepository(_mock_session())
        repo._session.flush = AsyncMock()

        result = await repo.create(
            business_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            city="Bangalore",
            is_primary=True,
            label="HQ",
            locality="Koramangala",
            address_line_1="100 MG Road",
            postal_code="560001",
            state="Karnataka",
            country="IN",
            geo_lat=12.9716,
            geo_lng=77.5946,
        )
        assert result.is_primary is True
        assert result.label == "HQ"


# ── BusinessKeywordRepository ─────────────────────────────────────────────────


class TestBusinessKeywordRepository:
    @pytest.mark.asyncio
    async def test_list_for_business(self):
        repo = BusinessKeywordRepository(_mock_session())
        biz_id = uuid.uuid4()
        kw = BusinessKeyword(
            business_id=biz_id,
            tenant_id=uuid.uuid4(),
            keyword="ca firm",
            keyword_normalized="ca firm",
        )
        repo._session.execute = AsyncMock(return_value=_scalars_result([kw]))

        result = await repo.list_for_business(biz_id)
        assert result == [kw]

    @pytest.mark.asyncio
    async def test_create_batch(self):
        repo = BusinessKeywordRepository(_mock_session())
        repo._session.flush = AsyncMock()

        biz_id = uuid.uuid4()
        result = await repo.create_batch(
            business_id=biz_id,
            tenant_id=uuid.uuid4(),
            keywords=[("CA Firm", "ca firm"), ("Tax Filing", "tax filing")],
            source=KeywordSource.user,
        )
        assert repo._session.add.call_count == 2
        repo._session.flush.assert_called_once()
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_create_batch_empty(self):
        repo = BusinessKeywordRepository(_mock_session())
        repo._session.flush = AsyncMock()

        result = await repo.create_batch(
            business_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            keywords=[],
        )
        assert result == []
        repo._session.flush.assert_called_once()


# ── FreeAuditTokenRepository ──────────────────────────────────────────────────


class TestFreeAuditTokenRepository:
    def _make_token(self, **kw) -> FreeAuditToken:
        defaults = dict(
            token="tok123",
            business_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            expires_at=datetime.now(timezone.utc) + timedelta(days=14),
        )
        defaults.update(kw)
        return FreeAuditToken(**defaults)

    @pytest.mark.asyncio
    async def test_get_by_token_found(self):
        repo = FreeAuditTokenRepository(_mock_session())
        fat = self._make_token()
        repo._session.execute = AsyncMock(return_value=_scalar_result(fat))

        result = await repo.get_by_token("tok123")
        assert result is fat

    @pytest.mark.asyncio
    async def test_get_by_token_not_found(self):
        repo = FreeAuditTokenRepository(_mock_session())
        repo._session.execute = AsyncMock(return_value=_scalar_result(None))

        result = await repo.get_by_token("expired")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_active_for_business_found(self):
        repo = FreeAuditTokenRepository(_mock_session())
        fat = self._make_token()
        repo._session.execute = AsyncMock(return_value=_scalar_result(fat))

        result = await repo.get_active_for_business(fat.business_id)
        assert result is fat

    @pytest.mark.asyncio
    async def test_create_token(self):
        repo = FreeAuditTokenRepository(_mock_session())
        repo._session.flush = AsyncMock()
        expires = datetime.now(timezone.utc) + timedelta(days=14)

        result = await repo.create(
            token="newtoken",
            business_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            expires_at=expires,
        )
        repo._session.add.assert_called_once()
        repo._session.flush.assert_called_once()
        assert result.token == "newtoken"

    @pytest.mark.asyncio
    async def test_mark_claimed_sets_claimed_at(self):
        repo = FreeAuditTokenRepository(_mock_session())
        fat = self._make_token()
        repo._session.execute = AsyncMock(return_value=_scalar_result(fat))
        repo._session.flush = AsyncMock()

        result = await repo.mark_claimed("tok123")
        assert result is fat
        assert result.claimed_at is not None

    @pytest.mark.asyncio
    async def test_mark_claimed_not_found_returns_none(self):
        repo = FreeAuditTokenRepository(_mock_session())
        repo._session.execute = AsyncMock(return_value=_scalar_result(None))

        result = await repo.mark_claimed("missing")
        assert result is None


# ── CategoryRepository ────────────────────────────────────────────────────────


class TestCategoryRepository:
    @pytest.mark.asyncio
    async def test_get_by_id_found(self):
        repo = CategoryRepository(_mock_session())
        cat = Category(name="Legal Services", slug="legal-services")
        repo._session.execute = AsyncMock(return_value=_scalar_result(cat))

        result = await repo.get_by_id(cat.id)
        assert result is cat

    @pytest.mark.asyncio
    async def test_get_by_id_not_found_raises(self):
        repo = CategoryRepository(_mock_session())
        repo._session.execute = AsyncMock(return_value=_scalar_result(None))

        with pytest.raises(BusinessNotFoundError):
            await repo.get_by_id(uuid.uuid4())

    @pytest.mark.asyncio
    async def test_list_root(self):
        repo = CategoryRepository(_mock_session())
        cat = Category(name="Legal", slug="legal")
        repo._session.execute = AsyncMock(return_value=_scalars_result([cat]))

        result = await repo.list_root()
        assert result == [cat]

    @pytest.mark.asyncio
    async def test_list_children(self):
        repo = CategoryRepository(_mock_session())
        parent_id = uuid.uuid4()
        child = Category(
            name="Tax Law",
            slug="tax-law",
            parent_category_id=parent_id,
        )
        repo._session.execute = AsyncMock(return_value=_scalars_result([child]))

        result = await repo.list_children(parent_id)
        assert result == [child]
