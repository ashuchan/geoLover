"""Quota limit definitions per plan tier."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class QuotaLimits:
    businesses: int
    audits_per_month: int
    content_briefs_per_month: int
    llm_spend_inr_per_month: int
    publish_channels: int
    bulk_import_rows_per_upload: int


_PLAN_LIMITS: dict[str, QuotaLimits] = {
    "free": QuotaLimits(
        businesses=1,
        audits_per_month=1,
        content_briefs_per_month=0,
        llm_spend_inr_per_month=0,
        publish_channels=0,
        bulk_import_rows_per_upload=0,
    ),
    "starter": QuotaLimits(
        businesses=3,
        audits_per_month=12,
        content_briefs_per_month=10,
        llm_spend_inr_per_month=500,
        publish_channels=2,
        bulk_import_rows_per_upload=50,
    ),
    "growth": QuotaLimits(
        businesses=10,
        audits_per_month=50,
        content_briefs_per_month=50,
        llm_spend_inr_per_month=2000,
        publish_channels=10,
        bulk_import_rows_per_upload=200,
    ),
    "agency": QuotaLimits(
        businesses=100,
        audits_per_month=500,
        content_briefs_per_month=500,
        llm_spend_inr_per_month=10000,
        publish_channels=100,
        bulk_import_rows_per_upload=500,
    ),
    "enterprise": QuotaLimits(
        businesses=10000,
        audits_per_month=100000,
        content_briefs_per_month=10000,
        llm_spend_inr_per_month=100000,
        publish_channels=10000,
        bulk_import_rows_per_upload=500,
    ),
}


def get_limits(plan_slug: str) -> QuotaLimits:
    """Get quota limits for a plan. Returns enterprise limits for unknown plans."""
    return _PLAN_LIMITS.get(plan_slug, _PLAN_LIMITS["enterprise"])


def get_all_plans() -> list[str]:
    return list(_PLAN_LIMITS.keys())


def is_enforcement_enabled() -> bool:
    """
    Whether quota enforcement is active. In production this reads from a feature flag.
    For testing, returns True.
    """
    return True
