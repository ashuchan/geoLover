"""Unit tests for Publishing workflow stubs."""

from __future__ import annotations

import pytest

from app.modules.publishing.workflows import (
    EntitySeedingWorkflow,
    PublishWorkflow,
    TokenRefreshSweepWorkflow,
)


class TestPublishWorkflow:
    @pytest.mark.asyncio
    async def test_run_raises_not_implemented(self):
        wf = PublishWorkflow()
        with pytest.raises(NotImplementedError, match="Temporal"):
            await wf.run("brief-id", ["target-1", "target-2"])


class TestEntitySeedingWorkflow:
    @pytest.mark.asyncio
    async def test_run_raises_not_implemented(self):
        wf = EntitySeedingWorkflow()
        with pytest.raises(NotImplementedError, match="Temporal"):
            await wf.run("business-id")


class TestTokenRefreshSweepWorkflow:
    @pytest.mark.asyncio
    async def test_run_raises_not_implemented(self):
        wf = TokenRefreshSweepWorkflow()
        with pytest.raises(NotImplementedError, match="Temporal"):
            await wf.run()
