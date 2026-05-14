"""LLMGateway and ProxyGateway — the only entry points for external AI calls.

All engine adapters call through these gateways. This gives a single place
for cost metering, caching, rate limiting, and kill switches.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from app.modules.engines.protocol import EngineResponse, ProbeBudget, QueryIntent

_log = logging.getLogger(__name__)


class LLMGateway:
    """Gateway for LLM API calls (OpenAI, Anthropic, Perplexity, etc.)."""

    def __init__(self, *, api_key: Optional[str] = None, provider: str = "openai") -> None:
        self._api_key = api_key
        self._provider = provider
        self._total_cost_usd = 0.0

    async def complete(
        self,
        query: QueryIntent,
        *,
        model: str,
        system_prompt: str,
        budget: ProbeBudget,
        timeout_s: float = 30.0,
    ) -> EngineResponse:
        """Call the LLM API with budget enforcement.

        This is a stub implementation for testing; real implementation would
        call the provider API (openai, anthropic, etc.).
        """
        estimated_cost = 0.001  # stub estimate
        if estimated_cost > budget.max_cost_usd:
            from app.modules.engines.protocol import EngineBudgetExceededError
            raise EngineBudgetExceededError(
                f"Estimated cost ${estimated_cost:.4f} exceeds budget ${budget.max_cost_usd:.4f}"
            )

        if self._api_key is None:
            _log.warning("LLMGateway: no API key configured, returning stub response")
            return EngineResponse(
                engine_slug=self._provider,
                query_text=query.query_text,
                response_text=f"[stub response for: {query.query_text}]",
                latency_ms=0,
                cost_usd=0.0,
                success=True,
            )

        start = time.monotonic()
        try:
            response_text = await self._call_api(query, model=model, system_prompt=system_prompt, timeout_s=timeout_s)
            latency_ms = int((time.monotonic() - start) * 1000)
            cost = self._estimate_cost(response_text, model)
            self._total_cost_usd += cost
            return EngineResponse(
                engine_slug=self._provider,
                query_text=query.query_text,
                response_text=response_text,
                latency_ms=latency_ms,
                cost_usd=cost,
                success=True,
            )
        except Exception as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            _log.error("LLMGateway error: %s", exc)
            return EngineResponse(
                engine_slug=self._provider,
                query_text=query.query_text,
                response_text="",
                latency_ms=latency_ms,
                cost_usd=0.0,
                success=False,
                error_message=str(exc),
            )

    async def _call_api(self, query: QueryIntent, *, model: str, system_prompt: str, timeout_s: float) -> str:
        """Internal API call — override in subclasses or tests."""
        raise NotImplementedError("LLMGateway._call_api must be implemented by subclass")

    def _estimate_cost(self, response_text: str, model: str) -> float:
        """Estimate cost based on approximate token count."""
        token_estimate = len(response_text.split()) * 1.3
        cost_per_token = 0.000001 if "mini" in model else 0.00001
        return token_estimate * cost_per_token

    @property
    def total_cost_usd(self) -> float:
        return self._total_cost_usd


class ProxyGateway:
    """Gateway for scraping-based engines via a proxy pool."""

    def __init__(self, *, proxy_url: Optional[str] = None, api_key: Optional[str] = None) -> None:
        self._proxy_url = proxy_url
        self._api_key = api_key
        self._total_cost_usd = 0.0

    async def fetch(
        self,
        url: str,
        *,
        budget: ProbeBudget,
        timeout_s: float = 30.0,
        extra_headers: Optional[dict] = None,
    ) -> dict:
        """Fetch a URL through the proxy pool with budget enforcement.

        Returns a dict with 'content', 'status_code', 'latency_ms', 'cost_usd'.
        This is a stub for testing; real implementation uses Playwright + proxy.
        """
        estimated_cost = 0.01  # stub estimate
        if estimated_cost > budget.max_cost_usd:
            from app.modules.engines.protocol import EngineBudgetExceededError
            raise EngineBudgetExceededError(
                f"Estimated fetch cost ${estimated_cost:.4f} exceeds budget ${budget.max_cost_usd:.4f}"
            )

        if self._proxy_url is None:
            _log.warning("ProxyGateway: no proxy URL configured, returning stub response")
            return {
                "content": f"[stub page content for: {url}]",
                "status_code": 200,
                "latency_ms": 0,
                "cost_usd": 0.0,
            }

        start = time.monotonic()
        try:
            content = await self._fetch_via_proxy(url, timeout_s=timeout_s, extra_headers=extra_headers)
            latency_ms = int((time.monotonic() - start) * 1000)
            cost = 0.001  # flat estimate per request
            self._total_cost_usd += cost
            return {
                "content": content,
                "status_code": 200,
                "latency_ms": latency_ms,
                "cost_usd": cost,
            }
        except Exception as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            _log.error("ProxyGateway error: %s", exc)
            return {
                "content": "",
                "status_code": 0,
                "latency_ms": latency_ms,
                "cost_usd": 0.0,
                "error": str(exc),
            }

    async def _fetch_via_proxy(self, url: str, *, timeout_s: float, extra_headers: Optional[dict]) -> str:
        """Internal proxy fetch — override in subclasses or tests."""
        raise NotImplementedError("ProxyGateway._fetch_via_proxy must be implemented by subclass")

    @property
    def total_cost_usd(self) -> float:
        return self._total_cost_usd
