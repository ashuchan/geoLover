"""Temporal workflow stubs for the Notifications & Recrawl module."""

from __future__ import annotations


class WeeklyRecrawlBucketWorkflow:
    """Temporal workflow stub — processes all businesses in a day/hour bucket."""

    async def run(self, bucket_id: str) -> None:
        raise NotImplementedError("WeeklyRecrawlBucketWorkflow requires Temporal")


class BusinessRecrawlWorkflow:
    """Temporal workflow stub — runs recrawl for a single business."""

    async def run(self, business_id: str, audit_run_id: str) -> None:
        raise NotImplementedError("BusinessRecrawlWorkflow requires Temporal")


class WeeklyDigestAssemblyWorkflow:
    """Temporal workflow stub — assembles and sends weekly digest."""

    async def run(self, business_id: str, audit_run_id: str) -> None:
        raise NotImplementedError("WeeklyDigestAssemblyWorkflow requires Temporal")


class ChannelDeliveryWorkflow:
    """Temporal workflow stub — delivers a single notification via its channel."""

    async def run(self, notification_id: str) -> None:
        raise NotImplementedError("ChannelDeliveryWorkflow requires Temporal")


class DebounceCollectorWorkflow:
    """Temporal workflow stub — collects events in a debounce window then sends one notification."""

    async def run(self, notification_type: str, user_id: str, business_id: str) -> None:
        raise NotImplementedError("DebounceCollectorWorkflow requires Temporal")
