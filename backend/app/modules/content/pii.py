"""PII redaction utilities for the Content module.

Two-layer redaction:
1. Regex layer (always runs) - catches structured PII patterns
2. LLM layer (optional) - catches unstructured/contextual PII if gateway provided
"""

from __future__ import annotations

import re
from typing import Optional

_EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')
_PHONE_RE = re.compile(r'\+?[0-9]{10,13}')
_AADHAAR_RE = re.compile(r'\b[0-9]{4}\s?[0-9]{4}\s?[0-9]{4}\b')
_PAN_RE = re.compile(r'\b[A-Z]{5}[0-9]{4}[A-Z]\b')


class PIIRedactor:
    """Redacts PII from text using regex patterns (and optionally LLM)."""

    def redact_regex(self, text: str) -> str:
        """Apply regex-layer redaction. Always runs."""
        text = _EMAIL_RE.sub('[REDACTED_EMAIL]', text)
        text = _PHONE_RE.sub('[REDACTED_PHONE]', text)
        text = _AADHAAR_RE.sub('[REDACTED_AADHAAR]', text)
        text = _PAN_RE.sub('[REDACTED_PAN]', text)
        return text

    async def redact(self, text: str, *, llm_gateway=None) -> str:
        """Full redaction: regex always, LLM additionally if gateway provided.

        For Phase 4, only the regex layer is implemented.
        The LLM layer would call gateway with purpose='pii_redaction' if provided.
        """
        text = self.redact_regex(text)
        # LLM layer placeholder - not implemented in Phase 4
        # if llm_gateway is not None:
        #     result = await llm_gateway.complete(
        #         prompt_key="pii_redaction", params={"text": text}, ...
        #     )
        #     text = result.text
        return text
