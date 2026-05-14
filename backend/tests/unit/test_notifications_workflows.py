"""Unit tests for Temporal workflow stubs."""

from __future__ import annotations

import pytest

from app.modules.notifications.workflows import (
    BusinessRecrawlWorkflow,
    ChannelDeliveryWorkflow,
    DebounceCollectorWorkflow,
    WeeklyDigestAssemblyWorkflow,
    WeeklyRecrawlBucketWorkflow,
)


class TestWeeklyRecrawlBucketWorkflow:
    @pytest.mark.asyncio
    async def test_run_raises_not_implemented(self):
        wf = WeeklyRecrawlBucketWorkflow()
        with pytest.raises(NotImplementedError):
            await wf.run("bucket-0-6")


class TestBusinessRecrawlWorkflow:
    @pytest.mark.asyncio
    async def test_run_raises_not_implemented(self):
        wf = BusinessRecrawlWorkflow()
        with pytest.raises(NotImplementedError):
            await wf.run(str(__import__("uuid").uuid4()), str(__import__("uuid").uuid4()))


class TestWeeklyDigestAssemblyWorkflow:
    @pytest.mark.asyncio
    async def test_run_raises_not_implemented(self):
        wf = WeeklyDigestAssemblyWorkflow()
        with pytest.raises(NotImplementedError):
            await wf.run(str(__import__("uuid").uuid4()), str(__import__("uuid").uuid4()))


class TestChannelDeliveryWorkflow:
    @pytest.mark.asyncio
    async def test_run_raises_not_implemented(self):
        wf = ChannelDeliveryWorkflow()
        with pytest.raises(NotImplementedError):
            await wf.run(str(__import__("uuid").uuid4()))


class TestDebounceCollectorWorkflow:
    @pytest.mark.asyncio
    async def test_run_raises_not_implemented(self):
        wf = DebounceCollectorWorkflow()
        with pytest.raises(NotImplementedError):
            await wf.run("citation_won", str(__import__("uuid").uuid4()), str(__import__("uuid").uuid4()))
