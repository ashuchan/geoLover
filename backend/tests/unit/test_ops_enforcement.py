"""Unit tests for ops enforcement module (Phase 8)."""

from __future__ import annotations

import pytest

from app.modules.ops.enforcement import (
    QuotaLimits,
    get_all_plans,
    get_limits,
    is_enforcement_enabled,
)


class TestGetLimits:
    def test_free_plan(self):
        limits = get_limits("free")
        assert limits.businesses == 1
        assert limits.audits_per_month == 1
        assert limits.content_briefs_per_month == 0
        assert limits.llm_spend_inr_per_month == 0
        assert limits.publish_channels == 0
        assert limits.bulk_import_rows_per_upload == 0

    def test_starter_plan(self):
        limits = get_limits("starter")
        assert limits.businesses == 3
        assert limits.audits_per_month == 12
        assert limits.content_briefs_per_month == 10
        assert limits.llm_spend_inr_per_month == 500
        assert limits.publish_channels == 2
        assert limits.bulk_import_rows_per_upload == 50

    def test_growth_plan(self):
        limits = get_limits("growth")
        assert limits.businesses == 10
        assert limits.audits_per_month == 50

    def test_agency_plan(self):
        limits = get_limits("agency")
        assert limits.businesses == 100
        assert limits.audits_per_month == 500
        assert limits.content_briefs_per_month == 500
        assert limits.llm_spend_inr_per_month == 10000
        assert limits.publish_channels == 100
        assert limits.bulk_import_rows_per_upload == 500

    def test_enterprise_plan(self):
        limits = get_limits("enterprise")
        assert limits.businesses == 10000
        assert limits.audits_per_month == 100000

    def test_unknown_plan_returns_enterprise(self):
        limits = get_limits("unknown_plan")
        enterprise = get_limits("enterprise")
        assert limits.businesses == enterprise.businesses
        assert limits.audits_per_month == enterprise.audits_per_month
        assert limits.content_briefs_per_month == enterprise.content_briefs_per_month
        assert limits.llm_spend_inr_per_month == enterprise.llm_spend_inr_per_month

    def test_empty_slug_returns_enterprise(self):
        limits = get_limits("")
        enterprise = get_limits("enterprise")
        assert limits.businesses == enterprise.businesses

    def test_returns_quota_limits_instance(self):
        limits = get_limits("free")
        assert isinstance(limits, QuotaLimits)


class TestGetAllPlans:
    def test_returns_list(self):
        plans = get_all_plans()
        assert isinstance(plans, list)

    def test_contains_expected_plans(self):
        plans = get_all_plans()
        assert "free" in plans
        assert "starter" in plans
        assert "growth" in plans
        assert "agency" in plans
        assert "enterprise" in plans

    def test_plan_count(self):
        plans = get_all_plans()
        assert len(plans) == 5


class TestIsEnforcementEnabled:
    def test_returns_true(self):
        assert is_enforcement_enabled() is True

    def test_returns_bool(self):
        result = is_enforcement_enabled()
        assert isinstance(result, bool)
