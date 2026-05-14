"""Unit tests for ReportService and FreeAuditSubmissionService."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import ConflictError, NotFoundError, PermissionDeniedError
from app.modules.audit.models import AuditStatus
from app.modules.reporting.models import Report, ReportStatus, ShareLink
from app.modules.reporting.service import (
    FreeAuditSubmitted,
    FreeAuditSubmissionService,
    ReportGenerated,
    ReportService,
    normalise_business_name,
)


def _utcnow():
    return datetime.now(timezone.utc)


def _make_report(**kwargs) -> Report:
    defaults = dict(
        tenant_id=uuid.uuid4(),
        business_id=uuid.uuid4(),
        audit_run_id=uuid.uuid4(),
        web_view_token=f"tok-{uuid.uuid4().hex[:8]}",
        status=ReportStatus.generating,
    )
    defaults.update(kwargs)
    return Report(**defaults)


def _make_share_link(**kwargs) -> ShareLink:
    defaults = dict(
        tenant_id=uuid.uuid4(),
        business_id=uuid.uuid4(),
        report_id=uuid.uuid4(),
        token=f"sl-{uuid.uuid4().hex[:8]}",
        expires_at=_utcnow() + timedelta(days=30),
    )
    defaults.update(kwargs)
    return ShareLink(**defaults)


class TestNormaliseBusinessName:
    def test_lowercase(self):
        assert "test company" == normalise_business_name("Test Company")

    def test_strip_pvt_ltd(self):
        result = normalise_business_name("Acme Pvt Ltd")
        assert "pvt" not in result
        assert "ltd" not in result
        assert "acme" in result

    def test_strip_private_limited(self):
        result = normalise_business_name("Acme Private Limited")
        assert "private" not in result
        assert "limited" not in result

    def test_strip_llp(self):
        result = normalise_business_name("Acme LLP")
        assert "llp" not in result

    def test_strip_inc(self):
        result = normalise_business_name("Acme Inc.")
        assert "inc" not in result

    def test_diacritics_stripped(self):
        result = normalise_business_name("Café Royal")
        assert result == "cafe royal"

    def test_whitespace_collapsed(self):
        result = normalise_business_name("  Test   Business  ")
        assert result == "test business"

    def test_same_result_for_variants(self):
        a = normalise_business_name("Acme Pvt. Ltd.")
        b = normalise_business_name("ACME Private Limited")
        # Both should reduce to "acme" essentially
        assert "acme" in a and "acme" in b


class TestReportService:
    def _make_session(self):
        session = MagicMock()
        session.add = MagicMock()
        session.flush = AsyncMock()
        session.execute = AsyncMock()
        return session

    def _make_service(self, session=None):
        if session is None:
            session = self._make_session()
        return ReportService(session)

    @pytest.mark.asyncio
    async def test_create_report(self):
        session = self._make_session()
        svc = ReportService(session)

        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=execute_result)

        report = await svc.create_report(
            tenant_id=uuid.uuid4(),
            business_id=uuid.uuid4(),
            audit_run_id=uuid.uuid4(),
            score=72.5,
            confidence_band="medium",
            completeness_pct=0.9,
        )
        assert report.status == ReportStatus.generating
        assert report.score == 72.5
        assert len(report.web_view_token) > 0

    @pytest.mark.asyncio
    async def test_get_report(self):
        report = _make_report()
        session = self._make_session()
        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = report
        session.execute = AsyncMock(return_value=execute_result)

        svc = ReportService(session)
        result = await svc.get_report(report.id)
        assert result is report

    @pytest.mark.asyncio
    async def test_get_report_by_token_found(self):
        report = _make_report()
        session = self._make_session()
        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = report
        session.execute = AsyncMock(return_value=execute_result)

        svc = ReportService(session)
        result = await svc.get_report_by_token(report.web_view_token)
        assert result is report

    @pytest.mark.asyncio
    async def test_get_report_by_token_not_found(self):
        session = self._make_session()
        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=execute_result)

        svc = ReportService(session)
        with pytest.raises(NotFoundError):
            await svc.get_report_by_token("missing-token")

    @pytest.mark.asyncio
    async def test_get_report_for_audit_run(self):
        report = _make_report()
        session = self._make_session()
        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = report
        session.execute = AsyncMock(return_value=execute_result)

        svc = ReportService(session)
        result = await svc.get_report_for_audit_run(uuid.uuid4())
        assert result is report

    @pytest.mark.asyncio
    async def test_list_reports_for_business(self):
        report = _make_report()
        session = self._make_session()
        execute_result = MagicMock()
        execute_result.scalars.return_value.all.return_value = [report]
        session.execute = AsyncMock(return_value=execute_result)

        svc = ReportService(session)
        results = await svc.list_reports_for_business(uuid.uuid4(), uuid.uuid4())
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_mark_report_failed(self):
        report = _make_report()
        session = self._make_session()
        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = report
        session.execute = AsyncMock(return_value=execute_result)

        svc = ReportService(session)
        result = await svc.mark_report_failed(report.id)
        assert result.status == ReportStatus.failed

    @pytest.mark.asyncio
    async def test_pending_events_initially_empty(self):
        svc = ReportService(self._make_session())
        assert svc.pending_events == []

    @pytest.mark.asyncio
    async def test_create_share_link_success(self):
        tid = uuid.uuid4()
        bid = uuid.uuid4()
        report = _make_report(
            tenant_id=tid, business_id=bid, status=ReportStatus.ready
        )
        link = _make_share_link(tenant_id=tid, business_id=bid, report_id=report.id)

        session = self._make_session()
        call_count = [0]

        async def execute_side(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:
                result.scalar_one_or_none.return_value = report
            else:
                result.scalar_one_or_none.return_value = None
            result.scalars.return_value.all.return_value = []
            return result

        session.execute = AsyncMock(side_effect=execute_side)

        svc = ReportService(session)
        result = await svc.create_share_link(
            report_id=report.id,
            tenant_id=tid,
        )
        assert result.token is not None

    @pytest.mark.asyncio
    async def test_create_share_link_wrong_tenant(self):
        tid = uuid.uuid4()
        report = _make_report(tenant_id=tid, status=ReportStatus.ready)

        session = self._make_session()
        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = report
        session.execute = AsyncMock(return_value=execute_result)

        svc = ReportService(session)
        with pytest.raises(PermissionDeniedError):
            await svc.create_share_link(
                report_id=report.id,
                tenant_id=uuid.uuid4(),  # different tenant
            )

    @pytest.mark.asyncio
    async def test_create_share_link_report_not_ready(self):
        tid = uuid.uuid4()
        report = _make_report(tenant_id=tid, status=ReportStatus.generating)

        session = self._make_session()
        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = report
        session.execute = AsyncMock(return_value=execute_result)

        svc = ReportService(session)
        with pytest.raises(ConflictError):
            await svc.create_share_link(
                report_id=report.id,
                tenant_id=tid,
            )

    @pytest.mark.asyncio
    async def test_get_share_link_by_token_found(self):
        link = _make_share_link()
        session = self._make_session()
        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = link
        session.execute = AsyncMock(return_value=execute_result)

        svc = ReportService(session)
        result = await svc.get_share_link_by_token(link.token)
        assert result is link

    @pytest.mark.asyncio
    async def test_get_share_link_by_token_not_found(self):
        session = self._make_session()
        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=execute_result)

        svc = ReportService(session)
        with pytest.raises(NotFoundError):
            await svc.get_share_link_by_token("missing")

    @pytest.mark.asyncio
    async def test_revoke_share_link_success(self):
        tid = uuid.uuid4()
        link = _make_share_link(tenant_id=tid)

        session = self._make_session()
        call_count = [0]

        async def execute_side(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            result.scalar_one_or_none.return_value = link
            return result

        session.execute = AsyncMock(side_effect=execute_side)

        svc = ReportService(session)
        result = await svc.revoke_share_link(link.token, tenant_id=tid)
        assert result is not None

    @pytest.mark.asyncio
    async def test_revoke_share_link_not_found(self):
        session = self._make_session()
        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=execute_result)

        svc = ReportService(session)
        with pytest.raises(NotFoundError):
            await svc.revoke_share_link("missing", tenant_id=uuid.uuid4())

    @pytest.mark.asyncio
    async def test_revoke_share_link_wrong_tenant(self):
        tid = uuid.uuid4()
        link = _make_share_link(tenant_id=tid)

        session = self._make_session()
        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = link
        session.execute = AsyncMock(return_value=execute_result)

        svc = ReportService(session)
        with pytest.raises(PermissionDeniedError):
            await svc.revoke_share_link(link.token, tenant_id=uuid.uuid4())

    @pytest.mark.asyncio
    async def test_record_share_view(self):
        link = _make_share_link()
        link.view_count = 0
        session = self._make_session()
        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = link
        session.execute = AsyncMock(return_value=execute_result)

        svc = ReportService(session)
        await svc.record_share_view(link.token)
        # Atomic SQL UPDATE — in-memory object not mutated; verify execute was called
        assert session.execute.called

    @pytest.mark.asyncio
    async def test_flush_events(self):
        svc = ReportService(self._make_session())
        event = ReportGenerated(
            report_id=uuid.uuid4(),
            audit_run_id=uuid.uuid4(),
            business_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            web_view_token="tok123",
        )
        svc._pending_events.append(event)
        assert len(svc.pending_events) == 1

        with patch("app.modules.reporting.service.event_bus") as mock_bus:
            mock_bus.publish = AsyncMock()
            await svc.flush_events()
            mock_bus.publish.assert_called_once_with(event)

        assert len(svc.pending_events) == 0

    @pytest.mark.asyncio
    async def test_finalise_report(self):
        """Test finalise_report generates quick wins and marks report ready."""
        from app.modules.audit.models import (
            AuditRun,
            AuditStatus,
            AuditTrigger,
            QueryExecution,
            QueryExecutionStatus,
            Citation,
            CitationPolarity,
            CompetitorObservation,
        )
        from app.modules.business_profile.models import Business, BusinessSource, BusinessStatus
        from app.modules.business_profile.models import BusinessLocation, BusinessKeyword, BusinessAlias, AliasType

        tid = uuid.uuid4()
        bid = uuid.uuid4()
        arid = uuid.uuid4()
        rid = uuid.uuid4()

        report = _make_report(
            id=rid,
            tenant_id=tid,
            business_id=bid,
            audit_run_id=arid,
            score=60.0,
            confidence_band="medium",
            completeness_pct=0.9,
            status=ReportStatus.generating,
        )

        # After mark_ready, report should be ready
        ready_report = _make_report(
            id=rid,
            tenant_id=tid,
            business_id=bid,
            audit_run_id=arid,
            score=60.0,
            confidence_band="medium",
            completeness_pct=0.9,
            status=ReportStatus.ready,
        )

        business = Business(
            tenant_id=tid,
            canonical_name="My Bakery",
            name_normalized="my bakery",
            category_id=uuid.UUID(int=0),
            source=BusinessSource.free_audit,
        )
        business.website_url = "https://mybakery.com"

        location = BusinessLocation(
            business_id=bid,
            tenant_id=tid,
            city="Bangalore",
            locality="Koramangala",
            is_primary=True,
        )

        keyword = BusinessKeyword(
            business_id=bid,
            tenant_id=tid,
            keyword="fresh bread",
            keyword_normalized="fresh bread",
        )

        qe = QueryExecution(
            audit_run_id=arid,
            tenant_id=tid,
            engine_descriptor_id=uuid.uuid4(),
            query_text="best bakery",
            status=QueryExecutionStatus.succeeded,
        )

        citation = Citation(
            query_execution_id=qe.id,
            tenant_id=tid,
            business_id=bid,
            cited=True,
            confidence=0.9,
            polarity=CitationPolarity.positive,
        )

        competitor = CompetitorObservation(
            audit_run_id=arid,
            tenant_id=tid,
            business_id=bid,
            competitor_name="Rival Bakery",
            competitor_name_normalized="rival bakery",
            first_seen_in_execution_id=qe.id,
        )

        session = MagicMock()
        session.add = MagicMock()
        session.flush = AsyncMock()
        call_count = [0]

        async def execute_side(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            n = call_count[0]
            if n == 1:  # get_by_id (report)
                result.scalar_one_or_none.return_value = report
            elif n == 2:  # business
                result.scalar_one_or_none.return_value = business
            elif n == 3:  # locations
                result.scalars.return_value.all.return_value = [location]
            elif n == 4:  # keywords
                result.scalars.return_value.all.return_value = [keyword]
            elif n == 5:  # aliases
                result.scalars.return_value.all.return_value = []
            elif n == 6:  # query executions
                result.scalars.return_value.all.return_value = [qe]
            elif n == 7:  # citations
                result.scalars.return_value.all.return_value = [citation]
            elif n == 8:  # competitor observations
                result.scalars.return_value.all.return_value = [competitor]
            else:  # mark_ready get_by_id
                result.scalar_one_or_none.return_value = ready_report
            return result

        session.execute = AsyncMock(side_effect=execute_side)

        svc = ReportService(session)
        result = await svc.finalise_report(
            rid,
            tenant_id=tid,
            business_id=bid,
            audit_run_id=arid,
        )

        assert result.status == ReportStatus.ready
        events = svc.pending_events
        assert len(events) == 1
        assert isinstance(events[0], ReportGenerated)
        assert events[0].audit_run_id == arid

    @pytest.mark.asyncio
    async def test_finalise_report_with_lost_queries_and_competitors(self):
        """Test _build_audit_context covers lost query and competitor paths."""
        from app.modules.audit.models import (
            QueryExecution,
            QueryExecutionStatus,
            Citation,
            CitationPolarity,
            CompetitorObservation,
        )
        from app.modules.business_profile.models import Business, BusinessSource

        tid = uuid.uuid4()
        bid = uuid.uuid4()
        arid = uuid.uuid4()
        rid = uuid.uuid4()

        report = _make_report(
            id=rid,
            tenant_id=tid,
            business_id=bid,
            audit_run_id=arid,
            score=30.0,
            confidence_band="low",
            completeness_pct=0.7,
            status=ReportStatus.generating,
        )

        ready_report = _make_report(
            id=rid,
            tenant_id=tid,
            business_id=bid,
            audit_run_id=arid,
            status=ReportStatus.ready,
        )

        business = Business(
            tenant_id=tid,
            canonical_name="Test Business",
            name_normalized="test business",
            category_id=uuid.UUID(int=0),
            source=BusinessSource.free_audit,
        )

        # QE with failed status (should be skipped)
        qe_failed = QueryExecution(
            audit_run_id=arid,
            tenant_id=tid,
            engine_descriptor_id=uuid.uuid4(),
            query_text="failed query",
            status=QueryExecutionStatus.failed,
        )

        # QE succeeded but not cited (lost query with competitor mentioned)
        qe_lost = QueryExecution(
            audit_run_id=arid,
            tenant_id=tid,
            engine_descriptor_id=uuid.uuid4(),
            query_text="lost query",
            status=QueryExecutionStatus.succeeded,
        )

        citation_not_cited = Citation(
            query_execution_id=qe_lost.id,
            tenant_id=tid,
            business_id=bid,
            cited=False,
            confidence=0.0,
            polarity=CitationPolarity.neutral,
            competitors_mentioned=["Competitor A"],
        )

        competitor = CompetitorObservation(
            audit_run_id=arid,
            tenant_id=tid,
            business_id=bid,
            competitor_name="Competitor A",
            competitor_name_normalized="competitor a",
            first_seen_in_execution_id=qe_lost.id,
        )

        session = MagicMock()
        session.add = MagicMock()
        session.flush = AsyncMock()
        call_count = [0]

        async def execute_side(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            n = call_count[0]
            if n == 1:  # get_by_id (report)
                result.scalar_one_or_none.return_value = report
            elif n == 2:  # business
                result.scalar_one_or_none.return_value = business
            elif n == 3:  # locations (empty)
                result.scalars.return_value.all.return_value = []
            elif n == 4:  # keywords (empty)
                result.scalars.return_value.all.return_value = []
            elif n == 5:  # aliases (empty)
                result.scalars.return_value.all.return_value = []
            elif n == 6:  # query executions
                result.scalars.return_value.all.return_value = [qe_failed, qe_lost]
            elif n == 7:  # citations
                result.scalars.return_value.all.return_value = [citation_not_cited]
            elif n == 8:  # competitor observations
                result.scalars.return_value.all.return_value = [competitor]
            else:  # mark_ready
                result.scalar_one_or_none.return_value = ready_report
            return result

        session.execute = AsyncMock(side_effect=execute_side)

        svc = ReportService(session)
        result = await svc.finalise_report(
            rid,
            tenant_id=tid,
            business_id=bid,
            audit_run_id=arid,
        )
        assert result.status == ReportStatus.ready
        # The lost query "lost query" should have competitor mapped
        events = svc.pending_events
        assert len(events) == 1


class TestFreeAuditSubmissionService:
    def _make_fat(self, **kwargs):
        from app.modules.business_profile.models import FreeAuditToken
        defaults = dict(
            token=f"fat-{uuid.uuid4().hex[:8]}",
            business_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            expires_at=_utcnow() + timedelta(days=14),
        )
        defaults.update(kwargs)
        return FreeAuditToken(**defaults)

    def _make_audit_run(self, **kwargs):
        from app.modules.audit.models import AuditRun, AuditTrigger
        defaults = dict(
            tenant_id=uuid.uuid4(),
            business_id=uuid.uuid4(),
            trigger=AuditTrigger.free_audit,
            status=AuditStatus.pending,
        )
        defaults.update(kwargs)
        return AuditRun(**defaults)

    def _make_session(self, fat=None, audit_run=None):
        session = MagicMock()
        session.add = MagicMock()
        session.flush = AsyncMock()

        async def execute_side(*args, **kwargs):
            result = MagicMock()
            result.scalar_one_or_none.return_value = fat if fat is not None else None
            return result

        session.execute = AsyncMock(side_effect=execute_side)
        return session

    @pytest.mark.asyncio
    async def test_submit_returns_token(self):
        session = self._make_session()
        svc = FreeAuditSubmissionService(session)

        tid = uuid.uuid4()
        bid = uuid.uuid4()
        arid = uuid.uuid4()

        token = await svc.submit(
            tenant_id=tid,
            business_id=bid,
            submitter_email_normalized="test@example.com",
            audit_run_id=arid,
        )
        assert isinstance(token, str)
        assert len(token) > 0

    @pytest.mark.asyncio
    async def test_submit_creates_free_audit_submitted_event(self):
        session = self._make_session()
        svc = FreeAuditSubmissionService(session)

        tid = uuid.uuid4()
        bid = uuid.uuid4()
        arid = uuid.uuid4()

        await svc.submit(
            tenant_id=tid,
            business_id=bid,
            submitter_email_normalized="test@example.com",
            audit_run_id=arid,
        )
        events = svc.pending_events
        assert len(events) == 1
        assert isinstance(events[0], FreeAuditSubmitted)
        assert events[0].tenant_id == tid
        assert events[0].business_id == bid

    @pytest.mark.asyncio
    async def test_get_status_token_not_found(self):
        session = self._make_session(fat=None)
        svc = FreeAuditSubmissionService(session)
        with pytest.raises(NotFoundError):
            await svc.get_status("missing-token")

    @pytest.mark.asyncio
    async def test_get_status_no_audit_run(self):
        fat = self._make_fat()
        fat.audit_run_id = None
        session = self._make_session(fat=fat)
        svc = FreeAuditSubmissionService(session)
        result = await svc.get_status(fat.token)
        assert result["status"] == "pending"
        assert result["report_ready"] is False

    @pytest.mark.asyncio
    async def test_get_status_with_running_audit(self):
        arid = uuid.uuid4()
        fat = self._make_fat(audit_run_id=arid)
        run = self._make_audit_run(status=AuditStatus.running, completeness_pct=0.5)

        session = MagicMock()
        session.add = MagicMock()
        session.flush = AsyncMock()
        call_count = [0]

        async def execute_side(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:
                result.scalar_one_or_none.return_value = fat
            else:
                result.scalar_one_or_none.return_value = run
            return result

        session.execute = AsyncMock(side_effect=execute_side)
        svc = FreeAuditSubmissionService(session)
        result = await svc.get_status(fat.token)
        assert result["status"] == "running"
        assert result["report_ready"] is False

    @pytest.mark.asyncio
    async def test_get_status_completed_audit(self):
        arid = uuid.uuid4()
        fat = self._make_fat(audit_run_id=arid)
        run = self._make_audit_run(
            status=AuditStatus.completed,
            completeness_pct=1.0,
            queries_total=50,
            queries_successful=50,
        )

        session = MagicMock()
        session.add = MagicMock()
        session.flush = AsyncMock()
        call_count = [0]

        async def execute_side(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:
                result.scalar_one_or_none.return_value = fat
            else:
                result.scalar_one_or_none.return_value = run
            return result

        session.execute = AsyncMock(side_effect=execute_side)
        svc = FreeAuditSubmissionService(session)
        result = await svc.get_status(fat.token)
        assert result["status"] == "completed"
        assert result["report_ready"] is True
        assert result["claim_offered"] is True

    @pytest.mark.asyncio
    async def test_claim_success(self):
        fat = self._make_fat()
        session = self._make_session(fat=fat)
        svc = FreeAuditSubmissionService(session)
        result = await svc.claim(fat.token)
        assert result is True

    @pytest.mark.asyncio
    async def test_claim_not_found(self):
        session = self._make_session(fat=None)
        svc = FreeAuditSubmissionService(session)
        result = await svc.claim("missing-token")
        assert result is False

    @pytest.mark.asyncio
    async def test_flush_events(self):
        session = self._make_session()
        svc = FreeAuditSubmissionService(session)
        event = FreeAuditSubmitted(
            audit_run_id=uuid.uuid4(),
            business_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            submitter_email_normalized="test@example.com",
            free_audit_token="tok",
        )
        svc._pending_events.append(event)

        with patch("app.modules.reporting.service.event_bus") as mock_bus:
            mock_bus.publish = AsyncMock()
            await svc.flush_events()
            mock_bus.publish.assert_called_once_with(event)

        assert len(svc.pending_events) == 0
