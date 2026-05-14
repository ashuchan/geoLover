"""AI engine adapter Protocol and value objects.

All AI engine adapters must implement AIEngineAdapter.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Protocol, runtime_checkable

from app.core.exceptions import CitedByError
from app.modules.audit.models import EngineDescriptor, EngineHealth


class EngineBudgetExceededError(CitedByError):
    """Raised when a query would exceed the configured cost budget."""
    error_code = "engine_budget_exceeded"


class EngineError(CitedByError):
    """Raised when an engine adapter encounters a retriable or permanent error."""

    error_code = "engine_error"

    def __init__(self, message: str, *, retryable: bool = False, **kwargs) -> None:
        super().__init__(message, **kwargs)
        self.retryable = retryable


class HealthStatus(str, Enum):
    healthy = "healthy"
    degraded = "degraded"
    unhealthy = "unhealthy"
    paused = "paused"


@dataclass(frozen=True)
class QueryIntent:
    """A single query to be sent to an AI engine."""

    query_text: str
    locale: str = "en-IN"
    query_id: Optional[str] = None  # optional correlation ID


@dataclass(frozen=True)
class ProbeBudget:
    """Cost/time constraints for a single probe."""

    max_cost_usd: float = 0.10
    timeout_s: float = 30.0
    max_retries: int = 2


@dataclass
class EngineResponse:
    """Response from an AI engine."""

    engine_slug: str
    query_text: str
    response_text: str
    latency_ms: int
    cost_usd: float
    success: bool
    error_message: Optional[str] = None
    raw_response: Optional[dict] = field(default=None, compare=False)


@runtime_checkable
class AIEngineAdapter(Protocol):
    """Protocol that all AI engine adapters must satisfy."""

    descriptor: EngineDescriptor

    async def probe(
        self,
        query: QueryIntent,
        *,
        budget: ProbeBudget,
        timeout_override_s: float | None = None,
    ) -> EngineResponse:
        """Send a probe query to the engine and return the response."""
        ...

    async def health_check(self) -> HealthStatus:
        """Check the health of the engine endpoint."""
        ...

    def supports_locale(self, locale: str) -> bool:
        """Return True if this engine supports the given locale."""
        ...

    def estimated_cost(self, query: QueryIntent) -> float:
        """Estimated USD cost for this query (may be 0.0 if unknown)."""
        ...
