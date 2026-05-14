"""LLM provider abstractions for the Content module."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Protocol, runtime_checkable


@dataclass
class ProviderResponse:
    text: str
    input_tokens: int
    output_tokens: int
    model: str
    duration_ms: int


class ProviderRateLimitError(Exception):
    pass


class ProviderTimeoutError(Exception):
    pass


class ProviderSafetyError(Exception):
    pass


class ProviderAuthError(Exception):
    pass


class ProviderError(Exception):
    pass


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    async def call(
        self,
        *,
        system: str,
        user: str,
        model: str,
        temperature: float,
        max_tokens: int,
        timeout_s: float,
    ) -> ProviderResponse:
        ...

    def estimate_cost(
        self, input_tokens: int, output_tokens: int, model: str
    ) -> Decimal:
        ...


class AnthropicProvider:
    name = "anthropic"
    # Rough cost rates (INR per token)
    _COST_PER_TOKEN_INR: dict[str, Decimal] = {
        "claude-opus-4-7": Decimal("0.004"),
        "claude-sonnet-4-6": Decimal("0.001"),
    }

    async def call(
        self,
        *,
        system: str,
        user: str,
        model: str,
        temperature: float,
        max_tokens: int,
        timeout_s: float,
    ) -> ProviderResponse:
        raise NotImplementedError("AnthropicProvider.call not implemented (requires API key)")

    def estimate_cost(self, input_tokens: int, output_tokens: int, model: str) -> Decimal:
        rate = self._COST_PER_TOKEN_INR.get(model, Decimal("0.001"))
        return rate * (input_tokens + output_tokens)


class OpenAIProvider:
    name = "openai"
    _COST_PER_TOKEN_INR: dict[str, Decimal] = {
        "gpt-4o": Decimal("0.0005"),
        "gpt-4o-mini": Decimal("0.00005"),
    }

    async def call(
        self,
        *,
        system: str,
        user: str,
        model: str,
        temperature: float,
        max_tokens: int,
        timeout_s: float,
    ) -> ProviderResponse:
        raise NotImplementedError("OpenAIProvider.call not implemented (requires API key)")

    def estimate_cost(self, input_tokens: int, output_tokens: int, model: str) -> Decimal:
        rate = self._COST_PER_TOKEN_INR.get(model, Decimal("0.0005"))
        return rate * (input_tokens + output_tokens)


class StaticTemplateProvider:
    name = "fallback_static"

    _TEMPLATES: dict[str, dict] = {
        "direct_answer_page": {
            "title": "Direct Answer Page",
            "h1": "Your Question Answered",
            "lede": "Here is a comprehensive answer to your question.",
            "body_sections": [],
            "faq_pairs": [],
            "jsonld": {},
        },
        "faq_cluster": {
            "qas": [
                {"question": "What services do you offer?", "answer": "We offer a wide range of professional services."},
                {"question": "Where are you located?", "answer": "We are conveniently located to serve you."},
                {"question": "How can I contact you?", "answer": "You can reach us through our website or phone."},
                {"question": "What are your hours?", "answer": "We are open during standard business hours."},
                {"question": "Do you offer consultations?", "answer": "Yes, we offer free initial consultations."},
            ]
        },
        "comparison_page": {
            "title": "Comparison Guide",
            "criteria": [],
            "comparison_table": [],
            "jsonld": {},
        },
        "entity_summary": {
            "description": "A professional business providing quality services.",
            "services": [],
            "audience": "",
            "jsonld": {},
        },
        "default": {
            "title": "Content Page",
            "h1": "Welcome",
            "lede": "Content generated for your business.",
            "body_sections": [],
            "faq_pairs": [],
            "jsonld": {},
        },
    }

    def _detect_brief_type(self, user_text: str) -> str:
        """Search for brief type keywords in the user prompt text."""
        lower = user_text.lower()
        if "faq_cluster" in lower or "faq cluster" in lower:
            return "faq_cluster"
        if "comparison_page" in lower or "comparison page" in lower:
            return "comparison_page"
        if "entity_summary" in lower or "entity summary" in lower:
            return "entity_summary"
        if "direct_answer_page" in lower or "direct answer page" in lower:
            return "direct_answer_page"
        return "default"

    async def call(
        self,
        *,
        system: str,
        user: str,
        model: str,
        temperature: float,
        max_tokens: int,
        timeout_s: float,
    ) -> ProviderResponse:
        brief_type = self._detect_brief_type(user)
        template = self._TEMPLATES.get(brief_type, self._TEMPLATES["default"])
        text = json.dumps(template)
        # Approximate token count: 1 token ≈ 4 characters
        approx_tokens = max(1, len(text) // 4)
        return ProviderResponse(
            text=text,
            input_tokens=0,
            output_tokens=approx_tokens,
            model=model,
            duration_ms=0,
        )

    def estimate_cost(self, input_tokens: int, output_tokens: int, model: str) -> Decimal:
        return Decimal("0")
