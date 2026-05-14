"""Unit tests for whitelabel sanitizer module."""

from __future__ import annotations

import pytest

from app.modules.whitelabel.sanitizer import (
    check_color_contrast,
    compute_wcag_contrast_ratio,
    parse_csv_row,
    sanitize_svg,
    scan_for_branding_leak,
    validate_font_family,
    validate_hex_color,
)


class TestSanitizeSvg:
    def test_clean_svg_returns_safe(self):
        svg = '<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0"/></svg>'
        is_safe, content, warnings = sanitize_svg(svg)
        assert is_safe is True
        assert content == svg
        assert warnings == []

    def test_script_tag_rejected(self):
        svg = '<svg><script>alert(1)</script></svg>'
        is_safe, content, warnings = sanitize_svg(svg)
        assert is_safe is False
        assert content == ''
        assert len(warnings) == 1

    def test_script_tag_case_insensitive(self):
        svg = '<svg><SCRIPT>alert(1)</SCRIPT></svg>'
        is_safe, content, warnings = sanitize_svg(svg)
        assert is_safe is False

    def test_on_handler_rejected(self):
        svg = '<svg onload="alert(1)"><path/></svg>'
        is_safe, content, warnings = sanitize_svg(svg)
        assert is_safe is False

    def test_javascript_protocol_rejected(self):
        svg = '<svg><a xlink:href="javascript:alert(1)"><text>click</text></a></svg>'
        is_safe, content, warnings = sanitize_svg(svg)
        assert is_safe is False

    def test_foreign_object_rejected(self):
        svg = '<svg><foreignObject><html/></foreignObject></svg>'
        is_safe, content, warnings = sanitize_svg(svg)
        assert is_safe is False

    def test_xlink_external_href_rejected(self):
        svg = '<svg><use xlink:href="https://evil.com/sprite.svg#icon"/></svg>'
        is_safe, content, warnings = sanitize_svg(svg)
        assert is_safe is False


class TestScanForBrandingLeak:
    def test_finds_citedby_token(self):
        findings = scan_for_branding_leak("Welcome to CitedBy platform")
        assert any(f["token"] == "CitedBy" for f in findings)

    def test_finds_citedby_app_token(self):
        findings = scan_for_branding_leak("Visit citedby.app for more info")
        assert any(f["token"] == "citedby.app" for f in findings)

    def test_finds_lowercase_citedby(self):
        findings = scan_for_branding_leak("powered by citedby")
        assert any(f["token"] == "citedby" for f in findings)

    def test_clean_content_returns_empty(self):
        findings = scan_for_branding_leak("Welcome to our platform, powered by Acme Corp")
        assert findings == []

    def test_finding_has_required_keys(self):
        findings = scan_for_branding_leak("CitedBy is great")
        assert len(findings) >= 1
        f = findings[0]
        assert "token" in f
        assert "location" in f
        assert "severity" in f


class TestValidateHexColor:
    def test_valid_hex_colors(self):
        assert validate_hex_color("#2A6FDB") is True
        assert validate_hex_color("#000000") is True
        assert validate_hex_color("#FFFFFF") is True
        assert validate_hex_color("#abcdef") is True

    def test_invalid_hex_colors(self):
        assert validate_hex_color("2A6FDB") is False   # missing #
        assert validate_hex_color("#2A6FD") is False   # too short
        assert validate_hex_color("#2A6FDBXX") is False  # too long
        assert validate_hex_color("#GGGGGG") is False  # invalid chars
        assert validate_hex_color("") is False
        assert validate_hex_color("red") is False


class TestValidateFontFamily:
    def test_valid_fonts(self):
        assert validate_font_family("Inter") is True
        assert validate_font_family("Roboto") is True
        assert validate_font_family("Open Sans") is True
        assert validate_font_family("Montserrat") is True

    def test_invalid_fonts(self):
        assert validate_font_family("Comic Sans") is False
        assert validate_font_family("Arial") is False
        assert validate_font_family("") is False
        assert validate_font_family("inter") is False  # case-sensitive


class TestComputeWcagContrastRatio:
    def test_white_on_white(self):
        ratio = compute_wcag_contrast_ratio("#FFFFFF", "#FFFFFF")
        assert abs(ratio - 1.0) < 0.01

    def test_black_on_white(self):
        ratio = compute_wcag_contrast_ratio("#000000", "#FFFFFF")
        assert ratio > 20.0  # should be ~21.0

    def test_same_color_ratio_is_one(self):
        ratio = compute_wcag_contrast_ratio("#2A6FDB", "#2A6FDB")
        assert abs(ratio - 1.0) < 0.01

    def test_dark_blue_on_white_passes_aa(self):
        # #2A6FDB (CitedBy blue) should have good contrast on white
        ratio = compute_wcag_contrast_ratio("#2A6FDB")
        assert ratio > 1.0


class TestCheckColorContrast:
    def test_warns_on_light_primary_color(self):
        # Very light color - low contrast
        warnings = check_color_contrast("#EEEEEE", "#DDDDDD")
        assert len(warnings) >= 1

    def test_no_warnings_on_dark_primary(self):
        # Very dark color on white bg - high contrast
        warnings = check_color_contrast("#000000", "#000000")
        assert len(warnings) == 0

    def test_warns_below_4_5_ratio(self):
        # Light gray has low contrast
        warnings = check_color_contrast("#AAAAAA", "#2A6FDB")
        # #AAAAAA has ratio ~2.3, so should warn
        assert any("primary" in w.lower() for w in warnings)


class TestParseCsvRow:
    def test_happy_path(self):
        row = {
            "name": "Acme Shop",
            "locality": "Downtown",
            "city": "Mumbai",
            "category": "retail",
        }
        validated, error = parse_csv_row(row, 0)
        assert error is None
        assert validated is not None
        assert validated["name"] == "Acme Shop"
        assert validated["locality"] == "Downtown"
        assert validated["city"] == "Mumbai"
        assert validated["category"] == "retail"
        assert "idempotency_key" in validated
        assert len(validated["idempotency_key"]) == 32

    def test_missing_required_field_name(self):
        row = {"name": "", "locality": "Downtown", "city": "Mumbai", "category": "retail"}
        validated, error = parse_csv_row(row, 1)
        assert validated is None
        assert "name" in error
        assert "Row 1" in error

    def test_missing_required_field_locality(self):
        row = {"name": "Acme", "locality": "", "city": "Mumbai", "category": "retail"}
        validated, error = parse_csv_row(row, 2)
        assert validated is None
        assert "locality" in error

    def test_name_too_long(self):
        row = {
            "name": "A" * 201,
            "locality": "Downtown",
            "city": "Mumbai",
            "category": "retail",
        }
        validated, error = parse_csv_row(row, 3)
        assert validated is None
        assert "200" in error

    def test_name_too_short(self):
        row = {
            "name": "A",
            "locality": "Downtown",
            "city": "Mumbai",
            "category": "retail",
        }
        validated, error = parse_csv_row(row, 4)
        assert validated is None
        assert "too short" in error

    def test_optional_fields_included_when_present(self):
        row = {
            "name": "Acme Shop",
            "locality": "Downtown",
            "city": "Mumbai",
            "category": "retail",
            "website_url": "https://acme.com",
            "phone": "+91-9876543210",
        }
        validated, error = parse_csv_row(row, 0)
        assert error is None
        assert validated["website_url"] == "https://acme.com"
        assert validated["phone"] == "+91-9876543210"

    def test_optional_fields_none_when_missing(self):
        row = {"name": "Acme Shop", "locality": "Downtown", "city": "Mumbai", "category": "retail"}
        validated, error = parse_csv_row(row, 0)
        assert error is None
        assert validated["website_url"] is None
        assert validated["phone"] is None

    def test_idempotency_key_consistent(self):
        row = {"name": "Acme Shop", "locality": "Downtown", "city": "Mumbai", "category": "retail"}
        v1, _ = parse_csv_row(row, 0)
        v2, _ = parse_csv_row(row, 99)
        assert v1["idempotency_key"] == v2["idempotency_key"]
