"""Unit tests for LLM providers."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from app.modules.content.providers import (
    AnthropicProvider,
    OpenAIProvider,
    ProviderResponse,
    StaticTemplateProvider,
)


class TestAnthropicProvider:
    def test_name(self):
        assert AnthropicProvider.name == "anthropic"

    def test_estimate_cost_known_model(self):
        p = AnthropicProvider()
        cost = p.estimate_cost(100, 100, "claude-opus-4-7")
        assert cost == Decimal("0.004") * 200

    def test_estimate_cost_unknown_model(self):
        p = AnthropicProvider()
        cost = p.estimate_cost(100, 50, "unknown-model")
        assert cost == Decimal("0.001") * 150

    @pytest.mark.asyncio
    async def test_call_raises_not_implemented(self):
        p = AnthropicProvider()
        with pytest.raises(NotImplementedError):
            await p.call(system="s", user="u", model="m", temperature=0.0, max_tokens=100, timeout_s=10.0)


class TestOpenAIProvider:
    def test_name(self):
        assert OpenAIProvider.name == "openai"

    def test_estimate_cost(self):
        p = OpenAIProvider()
        cost = p.estimate_cost(1000, 500, "gpt-4o")
        assert cost == Decimal("0.0005") * 1500

    def test_estimate_cost_mini(self):
        p = OpenAIProvider()
        cost = p.estimate_cost(100, 100, "gpt-4o-mini")
        assert cost == Decimal("0.00005") * 200

    @pytest.mark.asyncio
    async def test_call_raises_not_implemented(self):
        p = OpenAIProvider()
        with pytest.raises(NotImplementedError):
            await p.call(system="s", user="u", model="m", temperature=0.0, max_tokens=100, timeout_s=10.0)


class TestStaticTemplateProvider:
    def test_name(self):
        assert StaticTemplateProvider.name == "fallback_static"

    def test_estimate_cost_always_zero(self):
        p = StaticTemplateProvider()
        assert p.estimate_cost(1000, 1000, "any") == Decimal("0")

    @pytest.mark.asyncio
    async def test_call_direct_answer_page(self):
        p = StaticTemplateProvider()
        resp = await p.call(
            system="s",
            user="Generate a direct_answer_page for ...",
            model="claude-sonnet-4-6",
            temperature=0.0,
            max_tokens=1000,
            timeout_s=30.0,
        )
        assert isinstance(resp, ProviderResponse)
        data = json.loads(resp.text)
        assert "title" in data
        assert resp.duration_ms == 0
        assert resp.input_tokens == 0

    @pytest.mark.asyncio
    async def test_call_faq_cluster(self):
        p = StaticTemplateProvider()
        resp = await p.call(
            system="s",
            user="Generate a faq_cluster for ...",
            model="m",
            temperature=0.0,
            max_tokens=500,
            timeout_s=30.0,
        )
        data = json.loads(resp.text)
        assert "qas" in data
        assert len(data["qas"]) == 5

    @pytest.mark.asyncio
    async def test_call_comparison_page(self):
        p = StaticTemplateProvider()
        resp = await p.call(
            system="s", user="comparison_page for...", model="m", temperature=0.0, max_tokens=500, timeout_s=30.0
        )
        data = json.loads(resp.text)
        assert "criteria" in data

    @pytest.mark.asyncio
    async def test_call_entity_summary(self):
        p = StaticTemplateProvider()
        resp = await p.call(
            system="s", user="entity summary for...", model="m", temperature=0.0, max_tokens=500, timeout_s=30.0
        )
        data = json.loads(resp.text)
        assert "description" in data

    @pytest.mark.asyncio
    async def test_call_default(self):
        p = StaticTemplateProvider()
        resp = await p.call(
            system="s", user="some unknown content", model="m", temperature=0.0, max_tokens=500, timeout_s=30.0
        )
        assert resp.text is not None
        assert resp.output_tokens > 0
