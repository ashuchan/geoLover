"""EngineRegistry — in-process singleton mapping engine slugs to adapter instances.

The registry is populated at startup (from DB or hardcoded descriptors for tests).
It is the only source of truth for which engines are active.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from app.modules.audit.models import EngineDescriptor, EngineHealth
from app.modules.engines.protocol import AIEngineAdapter, HealthStatus

_log = logging.getLogger(__name__)


class EngineRegistry:
    """In-process registry of AI engine adapters."""

    def __init__(self) -> None:
        self._adapters: dict[str, AIEngineAdapter] = {}  # slug → adapter
        self._descriptors: dict[str, EngineDescriptor] = {}  # slug → descriptor

    def register(self, adapter: AIEngineAdapter) -> None:
        """Register an adapter. Replaces any existing adapter for the same slug."""
        slug = adapter.descriptor.slug
        self._adapters[slug] = adapter
        self._descriptors[slug] = adapter.descriptor
        _log.debug("Registered engine adapter: %s", slug)

    def unregister(self, slug: str) -> None:
        """Remove an adapter from the registry."""
        self._adapters.pop(slug, None)
        self._descriptors.pop(slug, None)

    def get(self, slug: str) -> Optional[AIEngineAdapter]:
        """Return adapter by slug, or None if not registered."""
        return self._adapters.get(slug)

    def get_descriptor(self, slug: str) -> Optional[EngineDescriptor]:
        return self._descriptors.get(slug)

    def list_active(self) -> list[AIEngineAdapter]:
        """Return adapters whose descriptor health is healthy or degraded."""
        return [
            adapter
            for slug, adapter in self._adapters.items()
            if adapter.descriptor.health in (EngineHealth.healthy, EngineHealth.degraded)
        ]

    def list_all(self) -> list[AIEngineAdapter]:
        return list(self._adapters.values())

    def slugs(self) -> list[str]:
        return list(self._adapters.keys())

    def __len__(self) -> int:
        return len(self._adapters)

    async def refresh_health(self) -> dict[str, HealthStatus]:
        """Check health of all registered adapters and return results."""
        results: dict[str, HealthStatus] = {}
        for slug, adapter in list(self._adapters.items()):
            try:
                status = await adapter.health_check()
                results[slug] = status
            except Exception as exc:
                _log.warning("Health check failed for %s: %s", slug, exc)
                results[slug] = HealthStatus.unhealthy
        return results


# Module-level singleton — populated at app startup
engine_registry = EngineRegistry()
