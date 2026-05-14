"""Unit tests for business profile module — models and enums."""

from __future__ import annotations

import uuid

import pytest

from app.modules.business_profile.models import (
    AliasType,
    Business,
    BusinessAlias,
    BusinessCompetitor,
    BusinessKeyword,
    BusinessLocation,
    BusinessSource,
    BusinessStatus,
    CompetitorSource,
    CompetitorStatus,
    FreeAuditToken,
    KeywordSource,
)


class TestBusinessStatusEnum:
    def test_values(self):
        assert set(s.value for s in BusinessStatus) == {"trial", "active", "suspended", "deleted"}


class TestBusinessSourceEnum:
    def test_values(self):
        assert set(s.value for s in BusinessSource) == {
            "self_signup", "agency_created", "free_audit"
        }


class TestAliasTypeEnum:
    def test_values(self):
        expected = {
            "former_name", "translit_hindi", "translit_kannada",
            "abbreviation", "colloquial", "auto_generated",
        }
        assert set(t.value for t in AliasType) == expected


class TestKeywordSourceEnum:
    def test_values(self):
        assert set(s.value for s in KeywordSource) == {
            "user", "category_suggested", "audit_discovered"
        }


class TestBusinessInstantiation:
    def test_defaults(self):
        biz = Business(
            tenant_id=uuid.uuid4(),
            canonical_name="My Business",
            name_normalized="my business",
            category_id=uuid.uuid4(),
            source=BusinessSource.self_signup,
        )
        assert biz.status == BusinessStatus.trial
        assert biz.subcategory_ids == []
        assert biz.deleted_at is None
        assert biz.identity_uniqueness_score is None
        assert biz.primary_location_id is None

    def test_id_is_uuid(self):
        biz = Business(
            tenant_id=uuid.uuid4(),
            canonical_name="Biz",
            name_normalized="biz",
            category_id=uuid.uuid4(),
            source=BusinessSource.agency_created,
        )
        assert isinstance(biz.id, uuid.UUID)


class TestBusinessAliasInstantiation:
    def test_defaults(self):
        alias = BusinessAlias(
            business_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            alias_text="My Biz",
            alias_text_normalized="my biz",
            alias_type=AliasType.colloquial,
        )
        assert alias.confidence == 1.0


class TestBusinessLocationInstantiation:
    def test_defaults(self):
        loc = BusinessLocation(
            business_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            city="Bangalore",
        )
        assert loc.is_primary is False
        assert loc.country == "IN"
        assert loc.geo_lat is None
        assert loc.geo_lng is None


class TestBusinessKeywordInstantiation:
    def test_defaults(self):
        kw = BusinessKeyword(
            business_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            keyword="chartered accountant",
            keyword_normalized="chartered accountant",
        )
        assert kw.source == KeywordSource.user
        assert kw.priority == 100


class TestBusinessCompetitorInstantiation:
    def test_defaults(self):
        comp = BusinessCompetitor(
            business_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            competitor_name="Rival Inc",
            competitor_name_normalized="rival inc",
            source=CompetitorSource.user,
        )
        assert comp.status == CompetitorStatus.tracked


class TestFreeAuditToken:
    def test_instantiation(self):
        from datetime import timedelta
        from datetime import datetime, timezone
        fat = FreeAuditToken(
            token="abc123",
            business_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            expires_at=datetime.now(timezone.utc) + timedelta(days=14),
        )
        assert fat.claimed_at is None
