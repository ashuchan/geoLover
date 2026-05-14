"""Unit tests for EngineRegistry."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.audit.models import EngineDescriptor, EngineHealth
from app.modules.engines.protocol import EngineResponse, HealthStatus, ProbeBudget, QueryIntent
from app.modules.engines.registry import EngineRegistry


def _make_descriptor(slug: str, health: EngineHealth = EngineHealth.healthy) -> EngineDescriptor:
    return EngineDescriptor(
        slug=slug,
        display_name=slug,
        provider="test",
        adapter_class="test.Adapter",
        health=health,
    )


def _make_adapter(slug: str, health: EngineHealth = EngineHealth.healthy):
    adapter = MagicMock()
    adapter.descriptor = _make_descriptor(slug, health)
    adapter.health_check = AsyncMock(return_value=HealthStatus.healthy)
    return adapter


class TestEngineRegistry:
    def test_register_and_get(self):
        registry = EngineRegistry()
        adapter = _make_adapter("openai-v1")
        registry.register(adapter)

        result = registry.get("openai-v1")
        assert result is adapter

    def test_get_unknown_returns_none(self):
        registry = EngineRegistry()
        assert registry.get("unknown") is None

    def test_register_replaces_existing(self):
        registry = EngineRegistry()
        a1 = _make_adapter("openai-v1")
        a2 = _make_adapter("openai-v1")
        registry.register(a1)
        registry.register(a2)

        assert registry.get("openai-v1") is a2

    def test_unregister(self):
        registry = EngineRegistry()
        adapter = _make_adapter("openai-v1")
        registry.register(adapter)
        registry.unregister("openai-v1")

        assert registry.get("openai-v1") is None

    def test_list_active_filters_unhealthy(self):
        registry = EngineRegistry()
        healthy = _make_adapter("openai-v1", EngineHealth.healthy)
        degraded = _make_adapter("perplexity-v1", EngineHealth.degraded)
        unhealthy = _make_adapter("google-v1", EngineHealth.unhealthy)
        paused = _make_adapter("bing-v1", EngineHealth.paused)

        for a in [healthy, degraded, unhealthy, paused]:
            registry.register(a)

        active = registry.list_active()
        slugs = [a.descriptor.slug for a in active]
        assert "openai-v1" in slugs
        assert "perplexity-v1" in slugs
        assert "google-v1" not in slugs
        assert "bing-v1" not in slugs

    def test_list_all_returns_all(self):
        registry = EngineRegistry()
        for slug in ["a", "b", "c"]:
            registry.register(_make_adapter(slug))

        assert len(registry.list_all()) == 3

    def test_slugs(self):
        registry = EngineRegistry()
        registry.register(_make_adapter("openai-v1"))
        registry.register(_make_adapter("perplexity-v1"))

        slugs = registry.slugs()
        assert "openai-v1" in slugs
        assert "perplexity-v1" in slugs

    def test_len(self):
        registry = EngineRegistry()
        assert len(registry) == 0
        registry.register(_make_adapter("openai-v1"))
        assert len(registry) == 1

    @pytest.mark.asyncio
    async def test_refresh_health_returns_statuses(self):
        registry = EngineRegistry()
        adapter = _make_adapter("openai-v1")
        registry.register(adapter)

        statuses = await registry.refresh_health()
        assert "openai-v1" in statuses
        assert statuses["openai-v1"] == HealthStatus.healthy

    @pytest.mark.asyncio
    async def test_refresh_health_handles_exception(self):
        registry = EngineRegistry()
        adapter = _make_adapter("openai-v1")
        adapter.health_check = AsyncMock(side_effect=Exception("Connection error"))
        registry.register(adapter)

        statuses = await registry.refresh_health()
        assert statuses["openai-v1"] == HealthStatus.unhealthy

    def test_get_descriptor(self):
        registry = EngineRegistry()
        adapter = _make_adapter("openai-v1")
        registry.register(adapter)

        desc = registry.get_descriptor("openai-v1")
        assert desc is adapter.descriptor
