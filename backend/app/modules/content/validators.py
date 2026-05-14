"""Content validators for the Content module.

Validators check generated content for quality, compliance, and correctness.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ValidationResult:
    passed: bool
    findings: list[dict] = field(default_factory=list)


def _extract_all_text(content: dict) -> str:
    """Recursively extract all string values from a nested dict/list."""
    parts: list[str] = []

    def _walk(obj: Any) -> None:
        if isinstance(obj, str):
            parts.append(obj)
        elif isinstance(obj, dict):
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(content)
    return " ".join(parts)


class SchemaValidator:
    """Validates that content dict contains all required fields from output_schema."""

    def validate(self, content: dict, output_schema: dict) -> ValidationResult:
        findings: list[dict] = []
        required = output_schema.get("required", [])
        for field_name in required:
            if field_name not in content:
                findings.append(
                    {"type": "missing_field", "field": field_name, "message": f"Required field '{field_name}' is missing"}
                )
        return ValidationResult(passed=len(findings) == 0, findings=findings)


class LengthValidator:
    """Validates that combined text length is within acceptable bounds for brief type."""

    _LIMITS: dict[str, tuple[int, int]] = {
        "direct_answer_page": (500, 5000),
        "faq_cluster": (200, 8000),
        "comparison_page": (300, 6000),
        "entity_summary": (100, 2000),
    }

    def validate(self, content: dict, brief_type: str) -> ValidationResult:
        findings: list[dict] = []
        all_text = _extract_all_text(content)
        total_len = len(all_text)

        min_len, max_len = self._LIMITS.get(brief_type, (100, 10000))

        if total_len < min_len:
            findings.append({
                "type": "too_short",
                "message": f"Content length {total_len} chars is below minimum {min_len} for {brief_type}",
            })
        if total_len > max_len:
            findings.append({
                "type": "too_long",
                "message": f"Content length {total_len} chars exceeds maximum {max_len} for {brief_type}",
            })
        return ValidationResult(passed=len(findings) == 0, findings=findings)


class BusinessFactConsistency:
    """Validates that business identity facts appear in content."""

    def validate(
        self,
        content: dict,
        *,
        business_name: str,
        locality: str,
        city: str,
        identity_uniqueness_score: float = 1.0,
    ) -> ValidationResult:
        findings: list[dict] = []
        all_text = _extract_all_text(content).lower()
        name_lower = business_name.lower()

        if name_lower not in all_text:
            findings.append({
                "type": "missing_business_name",
                "message": f"Business name '{business_name}' not found in content",
            })

        # If uniqueness score is low, also require locality or city
        if identity_uniqueness_score < 0.5:
            locality_lower = locality.lower()
            city_lower = city.lower()
            has_location = (
                (locality_lower and locality_lower in all_text) or
                (city_lower and city_lower in all_text)
            )
            if not has_location:
                findings.append({
                    "type": "missing_location",
                    "message": f"Location context (locality or city) missing; required for low-uniqueness businesses",
                })

        return ValidationResult(passed=len(findings) == 0, findings=findings)


class NoForbiddenClaims:
    """Validates that content does not contain forbidden marketing claims."""

    _FORBIDDEN = frozenset([
        "guaranteed",
        "100% success",
        "best in the world",
        "number one",
        "#1 in",
    ])

    def validate(self, content: dict) -> ValidationResult:
        findings: list[dict] = []
        all_text = _extract_all_text(content).lower()

        for phrase in self._FORBIDDEN:
            if phrase.lower() in all_text:
                findings.append({
                    "type": "forbidden_claim",
                    "phrase": phrase,
                    "message": f"Forbidden claim '{phrase}' found in content",
                })

        return ValidationResult(passed=len(findings) == 0, findings=findings)


class PlausibleContentValidator:
    """Validates that content is plausible (no placeholders, has business/location terms)."""

    _PLACEHOLDERS = frozenset([
        "TODO",
        "PLACEHOLDER",
        "[FILL IN]",
        "Example text",
        "Lorem ipsum",
    ])

    def validate(
        self,
        content: dict,
        *,
        business_name: str,
        locality: str = "",
        city: str = "",
    ) -> ValidationResult:
        findings: list[dict] = []
        all_text = _extract_all_text(content)
        all_text_lower = all_text.lower()

        # Check for placeholder phrases
        for placeholder in self._PLACEHOLDERS:
            if placeholder.lower() in all_text_lower:
                findings.append({
                    "type": "placeholder_found",
                    "phrase": placeholder,
                    "message": f"Placeholder text '{placeholder}' found in content",
                })

        # Business name must appear
        if business_name.lower() not in all_text_lower:
            findings.append({
                "type": "missing_business_name",
                "message": f"Business name '{business_name}' not found in content",
            })

        # Location term must appear
        has_location = (
            (locality and locality.lower() in all_text_lower) or
            (city and city.lower() in all_text_lower)
        )
        if not has_location and (locality or city):
            findings.append({
                "type": "missing_location",
                "message": "No location term found in content",
            })

        # Content density check: ratio of alphabetic chars to total chars should be > 0.35
        if all_text.strip():
            alpha_count = sum(1 for c in all_text if c.isalpha())
            density = alpha_count / len(all_text)
            if density < 0.35:
                findings.append({
                    "type": "low_content_density",
                    "density": round(density, 3),
                    "message": f"Content density {density:.3f} is below threshold 0.35",
                })

        return ValidationResult(passed=len(findings) == 0, findings=findings)


class JsonLDValidator:
    """Validates JSON-LD structured data."""

    def validate(self, schema_jsonld: Any) -> ValidationResult:
        findings: list[dict] = []

        if schema_jsonld is None:
            return ValidationResult(passed=True, findings=[])

        # Parse if string
        if isinstance(schema_jsonld, str):
            try:
                schema_jsonld = json.loads(schema_jsonld)
            except (json.JSONDecodeError, ValueError) as e:
                findings.append({
                    "type": "invalid_json",
                    "message": f"JSON-LD is not valid JSON: {e}",
                })
                return ValidationResult(passed=False, findings=findings)

        if not isinstance(schema_jsonld, dict):
            findings.append({
                "type": "invalid_structure",
                "message": "JSON-LD must be a JSON object",
            })
            return ValidationResult(passed=False, findings=findings)

        # Must have @type
        if "@type" not in schema_jsonld:
            findings.append({
                "type": "missing_type",
                "message": "JSON-LD missing required '@type' field",
            })

        # Warn if @context is not schema.org
        context = schema_jsonld.get("@context", "")
        if context and "schema.org" not in str(context):
            findings.append({
                "type": "non_schema_org_context",
                "severity": "warning",
                "message": f"JSON-LD @context '{context}' is not schema.org",
            })

        # Only hard-fail if @type missing
        hard_failures = [f for f in findings if f.get("type") != "non_schema_org_context"]
        return ValidationResult(passed=len(hard_failures) == 0, findings=findings)


class ContentValidator:
    """Composite validator that runs all checks."""

    def validate(
        self,
        content: dict,
        *,
        brief_type: str,
        output_schema: dict,
        business_name: str,
        locality: str,
        city: str,
        schema_jsonld: Any = None,
        identity_uniqueness_score: float = 1.0,
    ) -> ValidationResult:
        all_findings: list[dict] = []

        schema_result = SchemaValidator().validate(content, output_schema)
        all_findings.extend(schema_result.findings)

        length_result = LengthValidator().validate(content, brief_type)
        all_findings.extend(length_result.findings)

        bfc_result = BusinessFactConsistency().validate(
            content,
            business_name=business_name,
            locality=locality,
            city=city,
            identity_uniqueness_score=identity_uniqueness_score,
        )
        all_findings.extend(bfc_result.findings)

        forbidden_result = NoForbiddenClaims().validate(content)
        all_findings.extend(forbidden_result.findings)

        plausible_result = PlausibleContentValidator().validate(
            content, business_name=business_name, locality=locality, city=city
        )
        all_findings.extend(plausible_result.findings)

        if schema_jsonld is not None:
            jsonld_result = JsonLDValidator().validate(schema_jsonld)
            all_findings.extend(jsonld_result.findings)

        # Deduplicate findings by (type, message) to avoid double-reporting
        seen: set[tuple] = set()
        unique_findings: list[dict] = []
        for f in all_findings:
            key = (f.get("type"), f.get("message", ""))
            if key not in seen:
                seen.add(key)
                unique_findings.append(f)

        # Exclude warnings from pass/fail
        hard_failures = [f for f in unique_findings if f.get("severity") != "warning"]
        return ValidationResult(passed=len(hard_failures) == 0, findings=unique_findings)
