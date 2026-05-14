"""Unit tests for Reporting repositories."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import NotFoundError
from app.modules.reporting.models import Report, ReportStatus, ShareLink
from app.modules.reporting.repository import ReportRepository, ShareLinkRepository


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


class TestReportRepository:
    def _make_session(self, scalar_result=None):
        session = MagicMock()
        session.add = MagicMock()
        session.flush = AsyncMock()
        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = scalar_result
        execute_result.scalars.return_value.all.return_value = [scalar_result] if scalar_result else []
        session.execute = AsyncMock(return_value=execute_result)
        return session

    @pytest.mark.asyncio
    async def test_create(self):
        session = self._make_session()
        repo = ReportRepository(session)
        r = await repo.create(
            tenant_id=uuid.uuid4(),
            business_id=uuid.uuid4(),
            audit_run_id=uuid.uuid4(),
            web_view_token="tok123",
            score=72.5,
            confidence_band="medium",
        )
        session.add.assert_called_once()
        session.flush.assert_called_once()
        assert r.status == ReportStatus.generating
        assert r.score == 72.5

    @pytest.mark.asyncio
    async def test_get_by_id_found(self):
        report = _make_report()
        session = self._make_session(scalar_result=report)
        repo = ReportRepository(session)
        result = await repo.get_by_id(report.id)
        assert result is report

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self):
        session = self._make_session(scalar_result=None)
        repo = ReportRepository(session)
        with pytest.raises(NotFoundError):
            await repo.get_by_id(uuid.uuid4())

    @pytest.mark.asyncio
    async def test_get_by_web_view_token_found(self):
        report = _make_report()
        session = self._make_session(scalar_result=report)
        repo = ReportRepository(session)
        result = await repo.get_by_web_view_token("tok123")
        assert result is report

    @pytest.mark.asyncio
    async def test_get_by_web_view_token_not_found(self):
        session = self._make_session(scalar_result=None)
        repo = ReportRepository(session)
        result = await repo.get_by_web_view_token("missing")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_audit_run(self):
        report = _make_report()
        session = self._make_session(scalar_result=report)
        repo = ReportRepository(session)
        result = await repo.get_by_audit_run(uuid.uuid4())
        assert result is report

    @pytest.mark.asyncio
    async def test_list_for_business(self):
        report = _make_report()
        session = self._make_session(scalar_result=report)
        repo = ReportRepository(session)
        results = await repo.list_for_business(uuid.uuid4(), uuid.uuid4())
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_mark_ready(self):
        report = _make_report()
        session = self._make_session(scalar_result=report)
        repo = ReportRepository(session)
        result = await repo.mark_ready(
            report.id,
            quick_wins={"wins": []},
            score=80.0,
            confidence_band="high",
            completeness_pct=0.98,
            pdf_gcs_uri="gs://bucket/report.pdf",
            pdf_byte_size=12345,
            pdf_checksum="abc123",
        )
        assert result.status == ReportStatus.ready
        assert result.quick_wins == {"wins": []}
        assert result.score == 80.0
        assert result.pdf_gcs_uri == "gs://bucket/report.pdf"
        assert result.generated_at is not None

    @pytest.mark.asyncio
    async def test_mark_ready_minimal(self):
        report = _make_report()
        session = self._make_session(scalar_result=report)
        repo = ReportRepository(session)
        result = await repo.mark_ready(report.id)
        assert result.status == ReportStatus.ready

    @pytest.mark.asyncio
    async def test_mark_failed(self):
        report = _make_report()
        session = self._make_session(scalar_result=report)
        repo = ReportRepository(session)
        result = await repo.mark_failed(report.id)
        assert result.status == ReportStatus.failed


class TestShareLinkRepository:
    def _make_session(self, scalar_result=None):
        session = MagicMock()
        session.add = MagicMock()
        session.flush = AsyncMock()
        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = scalar_result
        execute_result.scalars.return_value.all.return_value = [scalar_result] if scalar_result else []
        session.execute = AsyncMock(return_value=execute_result)
        return session

    @pytest.mark.asyncio
    async def test_create(self):
        session = self._make_session()
        repo = ShareLinkRepository(session)
        link = await repo.create(
            tenant_id=uuid.uuid4(),
            business_id=uuid.uuid4(),
            report_id=uuid.uuid4(),
            token="sharetoken",
            expires_at=_utcnow() + timedelta(days=30),
        )
        session.add.assert_called_once()
        session.flush.assert_called_once()
        assert link.token == "sharetoken"

    @pytest.mark.asyncio
    async def test_get_by_token_found(self):
        link = _make_share_link()
        session = self._make_session(scalar_result=link)
        repo = ShareLinkRepository(session)
        result = await repo.get_by_token(link.token)
        assert result is link

    @pytest.mark.asyncio
    async def test_get_by_token_not_found(self):
        session = self._make_session(scalar_result=None)
        repo = ShareLinkRepository(session)
        result = await repo.get_by_token("missing")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_id_found(self):
        link = _make_share_link()
        session = self._make_session(scalar_result=link)
        repo = ShareLinkRepository(session)
        result = await repo.get_by_id(link.id)
        assert result is link

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self):
        session = self._make_session(scalar_result=None)
        repo = ShareLinkRepository(session)
        with pytest.raises(NotFoundError):
            await repo.get_by_id(uuid.uuid4())

    @pytest.mark.asyncio
    async def test_list_for_report(self):
        link = _make_share_link()
        session = self._make_session(scalar_result=link)
        repo = ShareLinkRepository(session)
        results = await repo.list_for_report(uuid.uuid4())
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_revoke_found(self):
        link = _make_share_link()
        session = self._make_session(scalar_result=link)
        repo = ShareLinkRepository(session)
        result = await repo.revoke(link.token)
        assert result is link
        assert link.revoked_at is not None

    @pytest.mark.asyncio
    async def test_revoke_not_found(self):
        session = self._make_session(scalar_result=None)
        repo = ShareLinkRepository(session)
        result = await repo.revoke("missing")
        assert result is None

    @pytest.mark.asyncio
    async def test_increment_view(self):
        link = _make_share_link()
        link.view_count = 3
        session = self._make_session(scalar_result=link)
        repo = ShareLinkRepository(session)
        await repo.increment_view(link.token)
        # Atomic SQL UPDATE — in-memory object unchanged; verify execute was called
        assert session.execute.called
        assert session.flush.called

    @pytest.mark.asyncio
    async def test_increment_view_not_found(self):
        session = self._make_session(scalar_result=None)
        repo = ShareLinkRepository(session)
        # Should not raise
        await repo.increment_view("missing")
