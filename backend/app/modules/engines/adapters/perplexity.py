"""Perplexity API adapter (online model with citation URLs)."""

from __future__ import annotations

from app.modules.audit.models import EngineDescriptor, EngineHealth
from app.modules.engines.protocol import (
    EngineResponse,
    HealthStatus,
    ProbeBudget,
    QueryIntent,
)

_ENGINE_KEY = "perplexity-online-v1"
_DEFAULT_MODEL = "pplx-online"
_SUPPORTED_LOCALES = ["en-IN", "en-US", "en-GB"]


class PerplexityAdapter:
    """Adapter for Perplexity API (online model with web citations)."""

    def __init__(self, *, gateway=None, model: str = _DEFAULT_MODEL) -> None:
        self._gateway = gateway
        self._model = model
        self.descriptor = EngineDescriptor(
            slug=_ENGINE_KEY,
            display_name="Perplexity AI",
            provider="perplexity",
            adapter_class="app.modules.engines.adapters.perplexity.PerplexityAdapter",
            supported_locales=_SUPPORTED_LOCALES,
            health=EngineHealth.healthy,
            cost_per_query_usd=0.003,
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
        system_prompt = (
            "You are a helpful assistant with access to current web information. "
            "Answer factually and cite relevant businesses or services."
        )
        response = await self._gateway.complete(
            query,
            model=self._model,
            system_prompt=system_prompt,
            budget=budget,
            timeout_s=timeout_s,
        )
        return response

    async def health_check(self) -> HealthStatus:
        if self._gateway is None:
            return HealthStatus.unhealthy
        try:
            resp = await self._gateway.complete(
                QueryIntent(query_text="test", locale="en-IN"),
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
        return 0.003  # flat estimate for Perplexity online model
