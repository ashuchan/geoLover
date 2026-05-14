"""Unit tests for LLMGateway and ProxyGateway."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.modules.engines.gateway import LLMGateway, ProxyGateway
from app.modules.engines.protocol import EngineBudgetExceededError, ProbeBudget, QueryIntent


def _make_query(text: str = "test query") -> QueryIntent:
    return QueryIntent(query_text=text, locale="en-IN")


def _make_budget(max_cost: float = 1.0) -> ProbeBudget:
    return ProbeBudget(max_cost_usd=max_cost, timeout_s=30.0)


class TestLLMGateway:
    @pytest.mark.asyncio
    async def test_stub_response_without_api_key(self):
        gw = LLMGateway(provider="openai")
        resp = await gw.complete(
            _make_query(),
            model="gpt-4o-mini",
            system_prompt="Be helpful",
            budget=_make_budget(),
        )
        assert resp.success is True
        assert "stub response" in resp.response_text

    @pytest.mark.asyncio
    async def test_budget_exceeded_raises(self):
        gw = LLMGateway(api_key="fake-key")
        with pytest.raises(EngineBudgetExceededError):
            await gw.complete(
                _make_query(),
                model="gpt-4o-mini",
                system_prompt="Test",
                budget=_make_budget(max_cost=0.0),  # zero budget → always exceeded
            )

    @pytest.mark.asyncio
    async def test_call_api_not_implemented_returns_error_response(self):
        gw = LLMGateway(api_key="fake-key", provider="openai")
        resp = await gw.complete(
            _make_query(),
            model="gpt-4o-mini",
            system_prompt="Test",
            budget=_make_budget(max_cost=10.0),
        )
        assert resp.success is False
        assert "NotImplementedError" in resp.error_message or resp.error_message

    def test_total_cost_starts_zero(self):
        gw = LLMGateway()
        assert gw.total_cost_usd == 0.0

    def test_estimate_cost_mini_model(self):
        gw = LLMGateway()
        cost = gw._estimate_cost("hello world response text here", "gpt-4o-mini")
        assert cost > 0

    def test_estimate_cost_larger_model(self):
        gw = LLMGateway()
        mini_cost = gw._estimate_cost("same text", "gpt-4o-mini")
        large_cost = gw._estimate_cost("same text", "gpt-4o")
        assert large_cost > mini_cost


class TestProxyGateway:
    @pytest.mark.asyncio
    async def test_stub_response_without_proxy_url(self):
        gw = ProxyGateway()
        result = await gw.fetch("https://example.com", budget=_make_budget())
        assert result["status_code"] == 200
        assert "stub" in result["content"].lower()

    @pytest.mark.asyncio
    async def test_budget_exceeded_raises(self):
        gw = ProxyGateway(proxy_url="http://proxy.example.com")
        with pytest.raises(EngineBudgetExceededError):
            await gw.fetch(
                "https://example.com",
                budget=_make_budget(max_cost=0.0),
            )

    @pytest.mark.asyncio
    async def test_fetch_via_proxy_not_implemented_returns_error(self):
        gw = ProxyGateway(proxy_url="http://proxy.example.com")
        result = await gw.fetch(
            "https://example.com",
            budget=_make_budget(max_cost=10.0),
        )
        assert result["status_code"] == 0
        assert "error" in result

    def test_total_cost_starts_zero(self):
        gw = ProxyGateway()
        assert gw.total_cost_usd == 0.0


class TestLLMGatewaySubclass:
    """Test a subclass that implements _call_api."""

    @pytest.mark.asyncio
    async def test_successful_api_call_via_subclass(self):
        class FakeLLMGateway(LLMGateway):
            async def _call_api(self, query, *, model, system_prompt, timeout_s):
                return f"Response for: {query.query_text}"

        gw = FakeLLMGateway(api_key="test-key", provider="openai")
        resp = await gw.complete(
            _make_query("Best dental clinic"),
            model="gpt-4o-mini",
            system_prompt="Be helpful",
            budget=_make_budget(),
        )
        assert resp.success is True
        assert "Response for: Best dental clinic" == resp.response_text
        assert resp.cost_usd > 0
        assert gw.total_cost_usd > 0


class TestProxyGatewaySubclass:
    """Test a subclass that implements _fetch_via_proxy."""

    @pytest.mark.asyncio
    async def test_successful_fetch_via_subclass(self):
        class FakeProxyGateway(ProxyGateway):
            async def _fetch_via_proxy(self, url, *, timeout_s, extra_headers):
                return f"HTML content from {url}"

        gw = FakeProxyGateway(proxy_url="http://proxy.example.com")
        result = await gw.fetch(
            "https://example.com",
            budget=_make_budget(),
        )
        assert result["status_code"] == 200
        assert "HTML content" in result["content"]
        assert result["cost_usd"] == 0.001
        assert gw.total_cost_usd == 0.001
