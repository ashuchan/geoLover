"""Google AI Overviews scrape adapter (stub).

Real implementation uses Playwright + residential proxy pool.
This stub implements the interface and degrades gracefully when
Playwright is not available (CI/test environment).
"""

from __future__ import annotations

import logging

from app.modules.audit.models import EngineDescriptor, EngineHealth
from app.modules.engines.protocol import (
    EngineResponse,
    EngineError,
    HealthStatus,
    ProbeBudget,
    QueryIntent,
)

_ENGINE_KEY = "google-ai-overviews-v1"
_SUPPORTED_LOCALES = ["en-IN"]
_log = logging.getLogger(__name__)

_GOOGLE_SEARCH_URL = "https://www.google.com/search?q={query}&hl=en-IN&gl=IN"

# CSS selectors for AI Overview block (primary + fallback)
_AI_OVERVIEW_SELECTORS = [
    "[data-attrid='wa:/description']",  # primary
    ".ILfuVd",                           # fallback 1
    ".kno-rdesc span",                   # fallback 2
]


class GoogleAIOverviewsScrapeAdapter:
    """Scrape adapter for Google AI Overviews.

    Production use requires Playwright + proxy pool via ProxyGateway.
    In test/CI environments without Playwright, returns a stub response.
    """

    def __init__(self, *, gateway=None) -> None:
        self._gateway = gateway  # ProxyGateway instance
        self.descriptor = EngineDescriptor(
            slug=_ENGINE_KEY,
            display_name="Google AI Overviews",
            provider="google",
            adapter_class=(
                "app.modules.engines.adapters.google_ai_overviews"
                ".GoogleAIOverviewsScrapeAdapter"
            ),
            supported_locales=_SUPPORTED_LOCALES,
            health=EngineHealth.healthy,
            cost_per_query_usd=0.008,  # proxy bandwidth estimate
        )
        self._playwright_available = self._check_playwright()

    @staticmethod
    def _check_playwright() -> bool:
        try:
            import playwright  # noqa: F401
            return True
        except ImportError:
            return False

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
        if not self._playwright_available:
            _log.warning(
                "GoogleAIOverviewsScrapeAdapter: Playwright not available, returning stub"
            )
            return EngineResponse(
                engine_slug=_ENGINE_KEY,
                query_text=query.query_text,
                response_text="",
                latency_ms=0,
                cost_usd=0.0,
                success=False,
                error_message="Playwright not available in this environment",
            )

        if self._gateway is None:
            return EngineResponse(
                engine_slug=_ENGINE_KEY,
                query_text=query.query_text,
                response_text="",
                latency_ms=0,
                cost_usd=0.0,
                success=False,
                error_message="No proxy gateway configured",
            )

        import urllib.parse
        url = _GOOGLE_SEARCH_URL.format(query=urllib.parse.quote_plus(query.query_text))
        timeout_s = timeout_override_s or budget.timeout_s

        try:
            fetch_result = await self._gateway.fetch(
                url,
                budget=budget,
                timeout_s=timeout_s,
            )

            if not fetch_result.get("content"):
                return EngineResponse(
                    engine_slug=_ENGINE_KEY,
                    query_text=query.query_text,
                    response_text="",
                    latency_ms=fetch_result.get("latency_ms", 0),
                    cost_usd=fetch_result.get("cost_usd", 0.0),
                    success=False,
                    error_message="Empty response from proxy",
                )

            overview_text = self._extract_ai_overview(fetch_result["content"])
            return EngineResponse(
                engine_slug=_ENGINE_KEY,
                query_text=query.query_text,
                response_text=overview_text or "",
                latency_ms=fetch_result.get("latency_ms", 0),
                cost_usd=fetch_result.get("cost_usd", 0.0),
                success=bool(overview_text),
                error_message=None if overview_text else "No AI Overview found on page",
            )

        except Exception as exc:
            _log.error("GoogleAIOverviewsScrapeAdapter probe failed: %s", exc)
            raise EngineError(f"Scrape failed: {exc}", retryable=True) from exc

    def _extract_ai_overview(self, html_content: str) -> str | None:
        """Extract AI Overview text from HTML. Returns None if not found."""
        # In production, use BeautifulSoup or lxml; here use a simple heuristic
        import re
        # Look for AI Overview marker patterns
        for marker in ["AI Overview", "ai-overview", "data-attrid"]:
            if marker.lower() in html_content.lower():
                # Extract text between markers (simplified)
                pattern = re.compile(r"<p[^>]*>(.*?)</p>", re.DOTALL | re.IGNORECASE)
                matches = pattern.findall(html_content)
                if matches:
                    # Clean HTML tags
                    clean = re.compile(r"<[^>]+>")
                    texts = [clean.sub("", m).strip() for m in matches[:3]]
                    return " ".join(t for t in texts if len(t) > 20)
        return None

    async def health_check(self) -> HealthStatus:
        if not self._playwright_available:
            return HealthStatus.degraded
        if self._gateway is None:
            return HealthStatus.unhealthy
        try:
            result = await self._gateway.fetch(
                "https://www.google.com",
                budget=ProbeBudget(max_cost_usd=0.01, timeout_s=10.0),
            )
            return HealthStatus.healthy if result.get("status_code") == 200 else HealthStatus.degraded
        except Exception:
            return HealthStatus.unhealthy

    def supports_locale(self, locale: str) -> bool:
        return locale in _SUPPORTED_LOCALES

    def estimated_cost(self, query: QueryIntent) -> float:
        return 0.008  # proxy bandwidth estimate per request
