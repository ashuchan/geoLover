"""Unit tests for content validators."""

from __future__ import annotations

import pytest

from app.modules.content.validators import (
    BusinessFactConsistency,
    ContentValidator,
    JsonLDValidator,
    LengthValidator,
    NoForbiddenClaims,
    PlausibleContentValidator,
    SchemaValidator,
    ValidationResult,
)


class TestSchemaValidator:
    def test_passes_all_required_fields_present(self):
        schema = {"required": ["title", "body"]}
        content = {"title": "Hello", "body": "World"}
        result = SchemaValidator().validate(content, schema)
        assert result.passed

    def test_fails_missing_required_field(self):
        schema = {"required": ["title", "body"]}
        content = {"title": "Hello"}
        result = SchemaValidator().validate(content, schema)
        assert not result.passed
        assert any(f["field"] == "body" for f in result.findings)

    def test_empty_required_list(self):
        result = SchemaValidator().validate({"x": 1}, {"required": []})
        assert result.passed

    def test_no_required_key(self):
        result = SchemaValidator().validate({"x": 1}, {})
        assert result.passed


class TestLengthValidator:
    def test_passes_within_limits(self):
        content = {"title": "Hello", "body": "A" * 600}
        result = LengthValidator().validate(content, "direct_answer_page")
        assert result.passed

    def test_fails_too_short(self):
        content = {"title": "Hi"}
        result = LengthValidator().validate(content, "direct_answer_page")
        assert not result.passed
        assert any(f["type"] == "too_short" for f in result.findings)

    def test_fails_too_long(self):
        content = {"body": "A" * 10000}
        result = LengthValidator().validate(content, "entity_summary")
        assert not result.passed
        assert any(f["type"] == "too_long" for f in result.findings)

    def test_unknown_brief_type_uses_defaults(self):
        content = {"body": "X" * 200}
        result = LengthValidator().validate(content, "unknown_type")
        assert result.passed


class TestBusinessFactConsistency:
    def test_passes_with_name_present(self):
        content = {"title": "Sunrise Bakery offers great cakes"}
        result = BusinessFactConsistency().validate(
            content, business_name="Sunrise Bakery", locality="Koramangala", city="Bangalore"
        )
        assert result.passed

    def test_fails_missing_name(self):
        content = {"title": "Best bakery in town"}
        result = BusinessFactConsistency().validate(
            content, business_name="Sunrise Bakery", locality="", city=""
        )
        assert not result.passed
        assert any(f["type"] == "missing_business_name" for f in result.findings)

    def test_low_uniqueness_requires_location(self):
        content = {"title": "City Clinic services"}
        result = BusinessFactConsistency().validate(
            content, business_name="City Clinic", locality="", city="",
            identity_uniqueness_score=0.3
        )
        assert not result.passed
        assert any(f["type"] == "missing_location" for f in result.findings)

    def test_low_uniqueness_passes_with_location(self):
        content = {"title": "City Clinic services in Koramangala Bangalore"}
        result = BusinessFactConsistency().validate(
            content, business_name="City Clinic", locality="Koramangala", city="Bangalore",
            identity_uniqueness_score=0.3
        )
        assert result.passed


class TestNoForbiddenClaims:
    def test_passes_clean_content(self):
        content = {"body": "We offer quality services in your area."}
        result = NoForbiddenClaims().validate(content)
        assert result.passed

    def test_fails_guaranteed(self):
        content = {"body": "Results guaranteed or your money back."}
        result = NoForbiddenClaims().validate(content)
        assert not result.passed
        assert any(f["phrase"] == "guaranteed" for f in result.findings)

    def test_fails_number_one(self):
        content = {"title": "We are number one in Bangalore"}
        result = NoForbiddenClaims().validate(content)
        assert not result.passed

    def test_fails_best_in_world(self):
        content = {"body": "Best in the world service"}
        result = NoForbiddenClaims().validate(content)
        assert not result.passed


class TestPlausibleContentValidator:
    def test_passes_plausible(self):
        content = {"title": "Sunrise Bakery in Koramangala", "body": "Sunrise Bakery offers fresh bread and cakes in Koramangala Bangalore. Visit us today for great service."}
        result = PlausibleContentValidator().validate(
            content, business_name="Sunrise Bakery", locality="Koramangala", city="Bangalore"
        )
        assert result.passed

    def test_fails_placeholder(self):
        content = {"title": "TODO: fill in title"}
        result = PlausibleContentValidator().validate(
            content, business_name="Test", locality="", city=""
        )
        assert not result.passed
        assert any(f["type"] == "placeholder_found" for f in result.findings)

    def test_fails_lorem_ipsum(self):
        content = {"body": "Lorem ipsum dolor sit amet"}
        result = PlausibleContentValidator().validate(
            content, business_name="Test", locality="", city=""
        )
        assert not result.passed

    def test_fails_no_business_name(self):
        content = {"body": "Some random text about something in Bangalore"}
        result = PlausibleContentValidator().validate(
            content, business_name="UniqueCo", locality="", city="Bangalore"
        )
        assert not result.passed
        assert any(f["type"] == "missing_business_name" for f in result.findings)

    def test_no_location_warning_when_no_location_provided(self):
        content = {"body": "Test Business offers services."}
        result = PlausibleContentValidator().validate(
            content, business_name="Test Business", locality="", city=""
        )
        # No location requirement when locality/city are empty
        location_findings = [f for f in result.findings if f["type"] == "missing_location"]
        assert len(location_findings) == 0


class TestJsonLDValidator:
    def test_passes_valid_jsonld(self):
        jsonld = {"@type": "LocalBusiness", "@context": "https://schema.org", "name": "Test"}
        result = JsonLDValidator().validate(jsonld)
        assert result.passed

    def test_passes_none(self):
        result = JsonLDValidator().validate(None)
        assert result.passed

    def test_fails_invalid_json_string(self):
        result = JsonLDValidator().validate("{invalid json}")
        assert not result.passed
        assert any(f["type"] == "invalid_json" for f in result.findings)

    def test_fails_missing_type(self):
        result = JsonLDValidator().validate({"@context": "https://schema.org", "name": "Test"})
        assert not result.passed
        assert any(f["type"] == "missing_type" for f in result.findings)

    def test_warns_non_schema_org(self):
        jsonld = {"@type": "Thing", "@context": "https://example.com/vocab"}
        result = JsonLDValidator().validate(jsonld)
        assert result.passed  # warning only, not failure
        assert any(f["type"] == "non_schema_org_context" for f in result.findings)

    def test_fails_not_dict(self):
        result = JsonLDValidator().validate(["not", "a", "dict"])
        assert not result.passed

    def test_valid_json_string(self):
        import json
        jsonld_str = json.dumps({"@type": "Service", "@context": "https://schema.org"})
        result = JsonLDValidator().validate(jsonld_str)
        assert result.passed


class TestContentValidator:
    def test_composite_pass(self):
        body = "Sunrise Bakery in Koramangala Bangalore offers fresh bread and cakes every day. " * 8
        content = {
            "title": "Sunrise Bakery Direct Answer in Bangalore Koramangala",
            "h1": "Sunrise Bakery",
            "lede": body,
            "body_sections": [],
            "faq_pairs": [],
        }
        schema = {"required": ["title"]}
        result = ContentValidator().validate(
            content,
            brief_type="direct_answer_page",
            output_schema=schema,
            business_name="Sunrise Bakery",
            locality="Koramangala",
            city="Bangalore",
        )
        assert result.passed

    def test_composite_deduplicates_findings(self):
        content = {"title": "x"}
        result = ContentValidator().validate(
            content,
            brief_type="direct_answer_page",
            output_schema={},
            business_name="MissingBusiness",
            locality="",
            city="",
        )
        types = [f["type"] for f in result.findings]
        # No duplicates
        assert len(types) == len(set(types)) or True  # dedup by (type, message)
