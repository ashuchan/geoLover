"""Unit tests for API Pydantic v2 schemas."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.api.v1.schemas import (
    AliasCreate,
    BusinessCreate,
    BusinessUpdate,
    FreeAuditStartRequest,
    KeywordsAdd,
    LocationCreate,
    MemberInvite,
    TenantCreate,
    TenantUpdate,
)
from app.modules.business_profile.models import AliasType, BusinessSource
from app.modules.identity.models import TenantType, UserRole


class TestTenantCreate:
    def test_valid(self):
        t = TenantCreate(
            type=TenantType.agency,
            display_name="Acme Agency",
            slug="acme-agency",
        )
        assert t.primary_country == "IN"

    def test_slug_too_short_raises(self):
        with pytest.raises(ValidationError):
            TenantCreate(type=TenantType.agency, display_name="x", slug="ab")

    def test_slug_with_uppercase_raises(self):
        with pytest.raises(ValidationError):
            TenantCreate(type=TenantType.agency, display_name="x", slug="ABC")

    def test_display_name_too_long_raises(self):
        with pytest.raises(ValidationError):
            TenantCreate(type=TenantType.agency, display_name="x" * 201, slug="abc")

    def test_invalid_country_code_raises(self):
        with pytest.raises(ValidationError):
            TenantCreate(
                type=TenantType.agency,
                display_name="x",
                slug="abc",
                primary_country="IND",  # 3 chars, invalid
            )


class TestTenantUpdate:
    def test_all_optional(self):
        u = TenantUpdate()
        assert u.display_name is None
        assert u.primary_country is None

    def test_partial_update(self):
        u = TenantUpdate(display_name="New Name")
        assert u.display_name == "New Name"


class TestBusinessCreate:
    def test_valid(self):
        b = BusinessCreate(
            canonical_name="My Firm",
            category_id=uuid.uuid4(),
        )
        assert b.source == BusinessSource.self_signup
        assert b.locale == "en-IN"
        assert b.subcategory_ids == []

    def test_name_too_short_raises(self):
        with pytest.raises(ValidationError):
            BusinessCreate(canonical_name="A", category_id=uuid.uuid4())

    def test_name_too_long_raises(self):
        with pytest.raises(ValidationError):
            BusinessCreate(canonical_name="x" * 201, category_id=uuid.uuid4())

    def test_valid_email_accepted(self):
        b = BusinessCreate(canonical_name="Firm", category_id=uuid.uuid4(), primary_email="info@firm.com")
        assert b.primary_email == "info@firm.com"

    def test_invalid_email_raises(self):
        with pytest.raises(ValidationError):
            BusinessCreate(canonical_name="Firm", category_id=uuid.uuid4(), primary_email="not-an-email")

    def test_valid_url_accepted(self):
        b = BusinessCreate(canonical_name="Firm", category_id=uuid.uuid4(), website_url="https://firm.com")
        assert b.website_url == "https://firm.com"

    def test_invalid_url_raises(self):
        with pytest.raises(ValidationError):
            BusinessCreate(canonical_name="Firm", category_id=uuid.uuid4(), website_url="ftp://bad.com")

    def test_none_email_accepted(self):
        b = BusinessCreate(canonical_name="Firm", category_id=uuid.uuid4(), primary_email=None)
        assert b.primary_email is None

    def test_none_url_accepted(self):
        b = BusinessCreate(canonical_name="Firm", category_id=uuid.uuid4(), website_url=None)
        assert b.website_url is None


class TestBusinessUpdate:
    def test_all_optional(self):
        u = BusinessUpdate()
        assert u.canonical_name is None

    def test_partial(self):
        u = BusinessUpdate(description="Updated desc")
        assert u.description == "Updated desc"

    def test_invalid_email_raises(self):
        with pytest.raises(ValidationError):
            BusinessUpdate(primary_email="badformat")

    def test_valid_email_accepted(self):
        u = BusinessUpdate(primary_email="contact@firm.in")
        assert u.primary_email == "contact@firm.in"

    def test_invalid_url_raises(self):
        with pytest.raises(ValidationError):
            BusinessUpdate(website_url="javascript:alert(1)")

    def test_valid_url_accepted(self):
        u = BusinessUpdate(website_url="http://firm.in")
        assert u.website_url == "http://firm.in"


class TestLocationCreate:
    def test_valid(self):
        loc = LocationCreate(city="Bangalore")
        assert loc.country == "IN"
        assert loc.is_primary is False

    def test_empty_city_raises(self):
        with pytest.raises(ValidationError):
            LocationCreate(city="")


class TestAliasCreate:
    def test_valid(self):
        a = AliasCreate(alias_text="Acme Ltd", alias_type=AliasType.abbreviation)
        assert a.confidence == 1.0

    def test_confidence_out_of_range_raises(self):
        with pytest.raises(ValidationError):
            AliasCreate(alias_text="x", alias_type=AliasType.colloquial, confidence=1.5)

    def test_empty_alias_text_raises(self):
        with pytest.raises(ValidationError):
            AliasCreate(alias_text="", alias_type=AliasType.colloquial)


class TestKeywordsAdd:
    def test_valid(self):
        k = KeywordsAdd(keywords=["keyword one", "keyword two"])
        assert len(k.keywords) == 2

    def test_empty_keywords_raises(self):
        with pytest.raises(ValidationError):
            KeywordsAdd(keywords=[])

    def test_whitespace_only_keywords_raises(self):
        with pytest.raises(ValidationError):
            KeywordsAdd(keywords=["   ", "  "])

    def test_mixed_valid_and_whitespace(self):
        k = KeywordsAdd(keywords=["good keyword", "   "])
        assert k.keywords == ["good keyword"]

    def test_keyword_too_long_raises(self):
        with pytest.raises(ValidationError):
            KeywordsAdd(keywords=["x" * 201])


class TestMemberInvite:
    def test_valid(self):
        m = MemberInvite(email="user@example.com", role=UserRole.agency_member)
        assert m.business_scope_ids == []

    def test_with_scope_ids(self):
        ids = [uuid.uuid4(), uuid.uuid4()]
        m = MemberInvite(email="user@example.com", role=UserRole.business_member, business_scope_ids=ids)
        assert len(m.business_scope_ids) == 2


class TestFreeAuditStartRequest:
    def test_valid(self):
        r = FreeAuditStartRequest(
            business_name="My Firm",
            city="Bangalore",
            email="user@example.com",
            category_id=uuid.uuid4(),
        )
        assert r.website_url is None

    def test_name_too_short_raises(self):
        with pytest.raises(ValidationError):
            FreeAuditStartRequest(
                business_name="A",
                city="Blore",
                email="x@y.com",
                category_id=uuid.uuid4(),
            )

    def test_invalid_email_raises(self):
        with pytest.raises(ValidationError):
            FreeAuditStartRequest(
                business_name="My Firm",
                city="Blore",
                email="not-valid",
                category_id=uuid.uuid4(),
            )

    def test_invalid_url_raises(self):
        with pytest.raises(ValidationError):
            FreeAuditStartRequest(
                business_name="My Firm",
                city="Blore",
                email="ok@example.com",
                category_id=uuid.uuid4(),
                website_url="ftp://bad.com",
            )

    def test_valid_url_accepted(self):
        r = FreeAuditStartRequest(
            business_name="My Firm",
            city="Blore",
            email="ok@example.com",
            category_id=uuid.uuid4(),
            website_url="https://myfirm.com",
        )
        assert r.website_url == "https://myfirm.com"
