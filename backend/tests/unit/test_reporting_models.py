"""Unit tests for Reporting module ORM models."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.modules.reporting.models import (
    EffortEstimate,
    QuickWinActionType,
    Report,
    ReportStatus,
    ShareLink,
)


class TestReportStatusEnum:
    def test_values(self):
        assert ReportStatus.generating.value == "generating"
        assert ReportStatus.ready.value == "ready"
        assert ReportStatus.failed.value == "failed"

    def test_is_str_enum(self):
        assert ReportStatus.ready == "ready"


class TestQuickWinActionTypeEnum:
    def test_all_values_exist(self):
        expected = {
            "add_alias", "add_keyword", "update_gbp_description",
            "add_location_detail", "generate_faq_content",
            "seed_directory", "clarify_service_offering",
        }
        actual = {t.value for t in QuickWinActionType}
        assert actual == expected


class TestEffortEstimateEnum:
    def test_values(self):
        assert EffortEstimate.quick.value == "quick"
        assert EffortEstimate.medium.value == "medium"
        assert EffortEstimate.longer.value == "longer"


class TestReportModel:
    def test_defaults(self):
        tid = uuid.uuid4()
        bid = uuid.uuid4()
        arid = uuid.uuid4()
        report = Report(
            tenant_id=tid,
            business_id=bid,
            audit_run_id=arid,
            web_view_token="abc123",
        )
        assert isinstance(report.id, uuid.UUID)
        assert report.version == 1
        assert report.status == ReportStatus.generating
        assert report.template_version == "v1"
        assert isinstance(report.created_at, datetime)
        assert report.score is None
        assert report.quick_wins is None

    def test_custom_values(self):
        tid = uuid.uuid4()
        bid = uuid.uuid4()
        arid = uuid.uuid4()
        report = Report(
            tenant_id=tid,
            business_id=bid,
            audit_run_id=arid,
            web_view_token="token123",
            version=2,
            status=ReportStatus.ready,
            score=75.5,
            confidence_band="high",
            completeness_pct=0.95,
        )
        assert report.version == 2
        assert report.status == ReportStatus.ready
        assert report.score == 75.5
        assert report.confidence_band == "high"
        assert report.completeness_pct == 0.95

    def test_explicit_id(self):
        fixed_id = uuid.uuid4()
        report = Report(
            id=fixed_id,
            tenant_id=uuid.uuid4(),
            business_id=uuid.uuid4(),
            audit_run_id=uuid.uuid4(),
            web_view_token="tok",
        )
        assert report.id == fixed_id


class TestShareLinkModel:
    def test_defaults(self):
        link = ShareLink(
            tenant_id=uuid.uuid4(),
            business_id=uuid.uuid4(),
            report_id=uuid.uuid4(),
            token="sharetoken123",
            expires_at=datetime.now(timezone.utc),
        )
        assert isinstance(link.id, uuid.UUID)
        assert link.view_count == 0
        assert link.revoked_at is None
        assert link.created_by_user_id is None
        assert isinstance(link.created_at, datetime)

    def test_custom_values(self):
        uid = uuid.uuid4()
        link = ShareLink(
            tenant_id=uuid.uuid4(),
            business_id=uuid.uuid4(),
            report_id=uuid.uuid4(),
            token="sharetoken456",
            expires_at=datetime.now(timezone.utc),
            created_by_user_id=uid,
            view_count=5,
        )
        assert link.created_by_user_id == uid
        assert link.view_count == 5
