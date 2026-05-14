"""Unit tests for PII redactor."""

from __future__ import annotations

import pytest

from app.modules.content.pii import PIIRedactor


class TestPIIRedactor:
    def test_redacts_email(self):
        r = PIIRedactor()
        result = r.redact_regex("Contact us at user@example.com for help")
        assert "[REDACTED_EMAIL]" in result
        assert "user@example.com" not in result

    def test_redacts_phone_10_digits(self):
        r = PIIRedactor()
        result = r.redact_regex("Call 9876543210 now")
        assert "[REDACTED_PHONE]" in result

    def test_redacts_phone_with_plus(self):
        r = PIIRedactor()
        result = r.redact_regex("International: +919876543210")
        assert "[REDACTED_PHONE]" in result

    def test_redacts_aadhaar(self):
        r = PIIRedactor()
        result = r.redact_regex("Aadhaar: 1234 5678 9012")
        assert "[REDACTED_AADHAAR]" in result

    def test_redacts_pan(self):
        r = PIIRedactor()
        result = r.redact_regex("PAN: ABCDE1234F")
        assert "[REDACTED_PAN]" in result

    def test_no_pii(self):
        r = PIIRedactor()
        text = "This is a clean business description with no personal info."
        result = r.redact_regex(text)
        assert result == text

    def test_multiple_pii_types(self):
        r = PIIRedactor()
        text = "Email: admin@test.com, Phone: 9876543210, PAN: ABCDE1234F"
        result = r.redact_regex(text)
        assert "[REDACTED_EMAIL]" in result
        assert "[REDACTED_PHONE]" in result
        assert "[REDACTED_PAN]" in result

    @pytest.mark.asyncio
    async def test_async_redact_no_gateway(self):
        r = PIIRedactor()
        text = "Call 9876543210 for service"
        result = await r.redact(text)
        assert "[REDACTED_PHONE]" in result

    @pytest.mark.asyncio
    async def test_async_redact_with_none_gateway(self):
        r = PIIRedactor()
        text = "email: test@test.com"
        result = await r.redact(text, llm_gateway=None)
        assert "[REDACTED_EMAIL]" in result
