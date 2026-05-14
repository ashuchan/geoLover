"""Unit tests for LLM Gateway."""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.content.gateway import BudgetExceededError, LLMGateway, LLMResult, _call_cache
from app.modules.content.models import LLMCall, LLMPurpose, PromptVersion, UsageCounter
from app.modules.content.providers import (
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    ProviderResponse,
    ProviderSafetyError,
    ProviderTimeoutError,
    StaticTemplateProvider,
)


def _make_session():
    s = MagicMock()
    s.flush = AsyncMock()
    s.add = MagicMock()
    s.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    return s


def _make_prompt_version(temperature=Decimal("0.0")):
    return PromptVersion(
        prompt_key="test_v",
        version=1,
        system_text="You are helpful.",
        user_template="Write about {{business_name}}.",
        recommended_model="claude-sonnet-4-6",
        max_tokens=500,
        temperature=temperature,
        active_flag=True,
    )


def _make_llm_call():
    return LLMCall(
        tenant_id=uuid.uuid4(),
        business_id=uuid.uuid4(),
        purpose=LLMPurpose.content_brief_gen,
        provider="static",
        model="m",
        prompt_key="k",
        status="success",
    )


def _make_usage_counter():
    return UsageCounter(
        tenant_id=uuid.uuid4(),
        business_id=uuid.uuid4(),
        period="2026-05",
        llm_cost_inr=Decimal("0"),
    )


class TestLLMGatewayComplete:
    def setup_method(self):
        _call_cache.clear()

    def teardown_method(self):
        _call_cache.clear()

    @pytest.mark.asyncio
    async def test_success_with_static_provider(self):
        session = _make_session()
        pv = _make_prompt_version()
        uc = _make_usage_counter()
        llm_call = _make_llm_call()

        static = StaticTemplateProvider()
        gateway = LLMGateway(session, primary_provider=static, secondary_provider=static, static_provider=static)

        with patch.object(gateway._prompt_store, "get_active_prompt", new=AsyncMock(return_value=pv)), \
             patch.object(gateway._prompt_store, "render_prompt", new=AsyncMock(return_value=("sys", "user"))), \
             patch.object(gateway._llm_call_repo, "create", new=AsyncMock(return_value=llm_call)), \
             patch.object(gateway._usage_repo, "get_or_create", new=AsyncMock(return_value=uc)), \
             patch.object(gateway._usage_repo, "increment", new=AsyncMock()):

            result = await gateway.complete(
                prompt_key="test_v",
                params={"business_name": "Test"},
                tenant_id=uuid.uuid4(),
                business_id=uuid.uuid4(),
                purpose=LLMPurpose.content_brief_gen,
            )

        assert isinstance(result, LLMResult)
        assert result.provider == "fallback_static"

    @pytest.mark.asyncio
    async def test_budget_exceeded_raises(self):
        session = _make_session()
        pv = _make_prompt_version()
        uc = UsageCounter(
            tenant_id=uuid.uuid4(),
            business_id=uuid.uuid4(),
            period="2026-05",
            llm_cost_inr=Decimal("5000"),
        )

        gateway = LLMGateway(session)

        with patch.object(gateway._prompt_store, "get_active_prompt", new=AsyncMock(return_value=pv)), \
             patch.object(gateway._usage_repo, "get_or_create", new=AsyncMock(return_value=uc)):

            with pytest.raises(BudgetExceededError):
                await gateway.complete(
                    prompt_key="test_v",
                    params={},
                    tenant_id=uuid.uuid4(),
                    business_id=uuid.uuid4(),
                    purpose=LLMPurpose.content_brief_gen,
                )

    @pytest.mark.asyncio
    async def test_audit_quick_wins_skips_budget(self):
        session = _make_session()
        pv = _make_prompt_version()
        uc = UsageCounter(
            tenant_id=uuid.uuid4(),
            business_id=uuid.uuid4(),
            period="2026-05",
            llm_cost_inr=Decimal("9999"),
        )
        llm_call = _make_llm_call()
        static = StaticTemplateProvider()

        gateway = LLMGateway(session, primary_provider=static, secondary_provider=static, static_provider=static)

        with patch.object(gateway._prompt_store, "get_active_prompt", new=AsyncMock(return_value=pv)), \
             patch.object(gateway._prompt_store, "render_prompt", new=AsyncMock(return_value=("s", "u"))), \
             patch.object(gateway._llm_call_repo, "create", new=AsyncMock(return_value=llm_call)), \
             patch.object(gateway._usage_repo, "get_or_create", new=AsyncMock(return_value=uc)), \
             patch.object(gateway._usage_repo, "increment", new=AsyncMock()):

            # Should not raise BudgetExceededError
            result = await gateway.complete(
                prompt_key="test_v",
                params={},
                tenant_id=uuid.uuid4(),
                business_id=uuid.uuid4(),
                purpose=LLMPurpose.audit_quick_wins,
            )
        assert result is not None

    @pytest.mark.asyncio
    async def test_cache_hit(self):
        session = _make_session()
        pv = _make_prompt_version(temperature=Decimal("0.0"))
        uc = _make_usage_counter()
        llm_call = _make_llm_call()

        gateway = LLMGateway(session)
        cache_key = gateway._make_cache_key("test_v", str(pv.id), {"business_name": "X"}, "en-IN")
        import time
        _call_cache[cache_key] = ("cached text", time.time())

        with patch.object(gateway._prompt_store, "get_active_prompt", new=AsyncMock(return_value=pv)), \
             patch.object(gateway._llm_call_repo, "create", new=AsyncMock(return_value=llm_call)), \
             patch.object(gateway._usage_repo, "get_or_create", new=AsyncMock(return_value=uc)):

            result = await gateway.complete(
                prompt_key="test_v",
                params={"business_name": "X"},
                tenant_id=uuid.uuid4(),
                business_id=uuid.uuid4(),
                purpose=LLMPurpose.content_brief_gen,
            )

        assert result.from_cache is True
        assert result.text == "cached text"
        assert result.cost_inr == Decimal("0")

    @pytest.mark.asyncio
    async def test_fallback_to_static_when_primary_fails(self):
        session = _make_session()
        pv = _make_prompt_version()
        uc = _make_usage_counter()
        llm_call = _make_llm_call()

        failing_provider = MagicMock()
        failing_provider.name = "anthropic"
        failing_provider.call = AsyncMock(side_effect=ProviderError("API down"))
        failing_provider.estimate_cost = MagicMock(return_value=Decimal("0"))

        static = StaticTemplateProvider()
        gateway = LLMGateway(session, primary_provider=failing_provider, secondary_provider=failing_provider, static_provider=static)

        with patch.object(gateway._prompt_store, "get_active_prompt", new=AsyncMock(return_value=pv)), \
             patch.object(gateway._prompt_store, "render_prompt", new=AsyncMock(return_value=("s", "u"))), \
             patch.object(gateway._llm_call_repo, "create", new=AsyncMock(return_value=llm_call)), \
             patch.object(gateway._usage_repo, "get_or_create", new=AsyncMock(return_value=uc)), \
             patch.object(gateway._usage_repo, "increment", new=AsyncMock()):

            result = await gateway.complete(
                prompt_key="test_v",
                params={},
                tenant_id=uuid.uuid4(),
                business_id=uuid.uuid4(),
                purpose=LLMPurpose.content_brief_gen,
            )

        assert result.is_fallback is True
        assert result.provider == "fallback_static"

    def test_make_cache_key_consistent(self):
        gw = LLMGateway.__new__(LLMGateway)
        k1 = gw._make_cache_key("key", "vid", {"a": 1, "b": 2}, "en-IN")
        k2 = gw._make_cache_key("key", "vid", {"b": 2, "a": 1}, "en-IN")
        assert k1 == k2

    @pytest.mark.asyncio
    async def test_provider_retry_on_rate_limit(self):
        session = _make_session()
        pv = _make_prompt_version()
        uc = _make_usage_counter()
        llm_call = _make_llm_call()

        call_count = {"n": 0}
        resp = ProviderResponse(text="ok", input_tokens=10, output_tokens=10, model="m", duration_ms=0)

        async def flaky_call(**kwargs):
            call_count["n"] += 1
            if call_count["n"] < 2:
                raise ProviderRateLimitError("Rate limited")
            return resp

        primary = MagicMock()
        primary.name = "anthropic"
        primary.call = flaky_call
        primary.estimate_cost = MagicMock(return_value=Decimal("0.01"))

        gateway = LLMGateway(session, primary_provider=primary)

        with patch.object(gateway._prompt_store, "get_active_prompt", new=AsyncMock(return_value=pv)), \
             patch.object(gateway._prompt_store, "render_prompt", new=AsyncMock(return_value=("s", "u"))), \
             patch.object(gateway._llm_call_repo, "create", new=AsyncMock(return_value=llm_call)), \
             patch.object(gateway._usage_repo, "get_or_create", new=AsyncMock(return_value=uc)), \
             patch.object(gateway._usage_repo, "increment", new=AsyncMock()), \
             patch("asyncio.sleep", new=AsyncMock()):

            result = await gateway.complete(
                prompt_key="test_v",
                params={},
                tenant_id=uuid.uuid4(),
                business_id=uuid.uuid4(),
                purpose=LLMPurpose.content_brief_gen,
            )

        assert result.provider == "anthropic"
        assert call_count["n"] == 2
