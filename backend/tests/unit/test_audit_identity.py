"""Unit tests for BusinessIdentity value object."""

from __future__ import annotations

import uuid
import pytest

from app.modules.audit.identity import (
    BusinessIdentity,
    NormalisedAlias,
    _etld_plus_one,
    _normalize_name,
)


class TestNormalizeName:
    def test_lowercases(self):
        assert _normalize_name("Sharma Dental") == "sharma dental"

    def test_strips_diacritics(self):
        assert _normalize_name("Café") == "cafe"

    def test_collapses_whitespace(self):
        assert _normalize_name("Sharma  Dental  Clinic") == "sharma dental clinic"

    def test_strips_leading_trailing(self):
        assert _normalize_name("  hello  ") == "hello"


class TestEtldPlusOne:
    def test_strips_scheme(self):
        assert _etld_plus_one("https://sharmadental.in") == "sharmadental.in"

    def test_strips_www(self):
        assert _etld_plus_one("https://www.sharmadental.in") == "sharmadental.in"

    def test_strips_path(self):
        assert _etld_plus_one("https://sharmadental.in/about") == "sharmadental.in"

    def test_strips_query(self):
        assert _etld_plus_one("https://sharmadental.in?q=1") == "sharmadental.in"

    def test_empty_returns_none(self):
        assert _etld_plus_one("") is None

    def test_http_scheme(self):
        assert _etld_plus_one("http://example.com") == "example.com"


class TestBusinessIdentityBuild:
    def test_basic_build(self):
        bid = uuid.uuid4()
        identity = BusinessIdentity.build(
            business_id=bid,
            canonical_name="Sharma Dental Clinic",
            primary_city="Bengaluru",
            primary_locality="Koramangala",
        )
        assert identity.business_id == bid
        assert identity.canonical_name == "Sharma Dental Clinic"
        assert identity.name_normalized == "sharma dental clinic"
        assert identity.primary_city == "Bengaluru"

    def test_website_url_parsed_to_etld(self):
        identity = BusinessIdentity.build(
            business_id=uuid.uuid4(),
            canonical_name="Test",
            website_url="https://www.sharmadental.in/home",
        )
        assert identity.website_etld_plus_one == "sharmadental.in"

    def test_signal_set_populated(self):
        identity = BusinessIdentity.build(
            business_id=uuid.uuid4(),
            canonical_name="Sharma Dental",
            primary_city="Bengaluru",
            primary_locality="Koramangala",
        )
        assert len(identity.identity_signal_set) > 0
        assert "sharma" in identity.identity_signal_set
        assert "dental" in identity.identity_signal_set

    def test_aliases_included(self):
        alias = NormalisedAlias(text="SDC", text_normalized="sdc", alias_type="abbreviation")
        identity = BusinessIdentity.build(
            business_id=uuid.uuid4(),
            canonical_name="Sharma Dental Clinic",
            aliases=[alias],
        )
        assert len(identity.aliases) == 1
        assert identity.aliases[0].text == "SDC"

    def test_default_uniqueness_score(self):
        identity = BusinessIdentity.build(
            business_id=uuid.uuid4(),
            canonical_name="Test",
        )
        assert identity.name_uniqueness_score == 0.5

    def test_keywords_stored(self):
        identity = BusinessIdentity.build(
            business_id=uuid.uuid4(),
            canonical_name="Test",
            keywords=["dental", "teeth"],
        )
        assert "dental" in identity.keywords
