"""Temporal workflow stubs for Publishing & Entity Seeding."""

from __future__ import annotations


class PublishWorkflow:
    """Temporal workflow stub for publishing content to targets."""

    async def run(self, brief_id: str, target_ids: list[str]) -> None:
        raise NotImplementedError("PublishWorkflow requires Temporal")


class EntitySeedingWorkflow:
    """Temporal workflow stub for entity seeding."""

    async def run(self, business_id: str) -> None:
        raise NotImplementedError("EntitySeedingWorkflow requires Temporal")


class TokenRefreshSweepWorkflow:
    """Temporal workflow stub for token refresh sweep."""

    async def run(self) -> None:
        raise NotImplementedError("TokenRefreshSweepWorkflow requires Temporal")
