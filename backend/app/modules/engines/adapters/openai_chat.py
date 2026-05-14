"""OpenAI Chat Completions adapter.

Uses a LLMGateway instance for all API calls — never imports openai directly.
"""

from __future__ import annotations

import uuid

from app.modules.audit.models import EngineDescriptor, EngineHealth
from app.modules.engines.protocol import (
    AIEngineAdapter,
    EngineResponse,
    HealthStatus,
    ProbeBudget,
    QueryIntent,
)


_DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful local search assistant. Answer naturally and factually "
    "based on your knowledge. Focus on the most relevant local businesses and services."
)

_ENGINE_KEY = "openai-chat-v1"
_DEFAULT_MODEL = "gpt-4o-mini"
_RATE_LIMIT_RPM = 60
_SUPPORTED_LOCALES = ["en-IN", "en-US", "en-GB"]


class OpenAIChatAdapter:
    """Adapter for OpenAI Chat Completions API."""

    def __init__(
        self,
        *,
        gateway=None,  # LLMGateway instance; injected for testability
        model: str = _DEFAULT_MODEL,
    ) -> None:
        self._gateway = gateway
        self._model = model
        self.descriptor = EngineDescriptor(
            slug=_ENGINE_KEY,
            display_name="ChatGPT",
            provider="openai",
            adapter_class="app.modules.engines.adapters.openai_chat.OpenAIChatAdapter",
            supported_locales=_SUPPORTED_LOCALES,
            health=EngineHealth.healthy,
            cost_per_query_usd=0.001,
        )

    @property
    def engine_key(self) -> str:
        return _ENGINE_KEY

    async def probe(
        self,
        query: QueryIntent,
        *,
        budget: ProbeBudget,
        timeout_override_s: float | None = None,
    ) -> EngineResponse:
        if self._gateway is None:
            return EngineResponse(
                engine_slug=_ENGINE_KEY,
                query_text=query.query_text,
                response_text="",
                latency_ms=0,
                cost_usd=0.0,
                success=False,
                error_message="No gateway configured",
            )

        timeout_s = timeout_override_s or budget.timeout_s
        return await self._gateway.complete(
            query,
            model=self._model,
            system_prompt=_DEFAULT_SYSTEM_PROMPT,
            budget=budget,
            timeout_s=timeout_s,
        )

    async def health_check(self) -> HealthStatus:
        if self._gateway is None:
            return HealthStatus.unhealthy
        try:
            resp = await self._gateway.complete(
                QueryIntent(query_text="ping", locale="en-IN"),
                model=self._model,
                system_prompt="Reply OK",
                budget=ProbeBudget(max_cost_usd=0.001, timeout_s=10.0),
            )
            return HealthStatus.healthy if resp.success else HealthStatus.degraded
        except Exception:
            return HealthStatus.unhealthy

    def supports_locale(self, locale: str) -> bool:
        return locale in _SUPPORTED_LOCALES

    def estimated_cost(self, query: QueryIntent) -> float:
        word_count = len(query.query_text.split())
        token_estimate = word_count * 1.3 + 200  # prompt overhead
        return token_estimate * 0.0000001  # gpt-4o-mini pricing approx
