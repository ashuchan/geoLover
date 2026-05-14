"""Unit tests for Audit module repositories."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import NotFoundError
from app.modules.audit.models import (
    AuditRun,
    AuditStatus,
    AuditTrigger,
    Citation,
    CitationPolarity,
    CompetitorObservation,
    EngineDescriptor,
    EngineHealth,
    QueryExecution,
    QueryExecutionStatus,
    QueryTemplate,
    QueryTemplateSet,
)
from app.modules.audit.repository import (
    AuditRunRepository,
    CitationRepository,
    CompetitorObservationRepository,
    EngineDescriptorRepository,
    QueryExecutionRepository,
    QueryTemplateRepository,
)


def _make_session():
    session = MagicMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()
    return session


def _mock_scalar_one_or_none(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _mock_scalars_all(items):
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = items
    result.scalars.return_value = scalars
    return result


class TestAuditRunRepository:
    @pytest.mark.asyncio
    async def test_get_by_id_found(self):
        run = AuditRun(
            tenant_id=uuid.uuid4(), business_id=uuid.uuid4(), trigger=AuditTrigger.manual
        )
        session = _make_session()
        session.execute.return_value = _mock_scalar_one_or_none(run)

        repo = AuditRunRepository(session)
        result = await repo.get_by_id(run.id)
        assert result is run

    @pytest.mark.asyncio
    async def test_get_by_id_not_found_raises(self):
        session = _make_session()
        session.execute.return_value = _mock_scalar_one_or_none(None)

        repo = AuditRunRepository(session)
        with pytest.raises(NotFoundError):
            await repo.get_by_id(uuid.uuid4())

    @pytest.mark.asyncio
    async def test_create(self):
        session = _make_session()
        repo = AuditRunRepository(session)
        tid = uuid.uuid4()
        bid = uuid.uuid4()

        run = await repo.create(
            tenant_id=tid,
            business_id=bid,
            trigger=AuditTrigger.manual,
        )
        assert run.tenant_id == tid
        assert run.business_id == bid
        assert run.trigger == AuditTrigger.manual
        assert run.status == AuditStatus.pending
        session.add.assert_called_once()
        session.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_list_for_tenant(self):
        runs = [
            AuditRun(tenant_id=uuid.uuid4(), business_id=uuid.uuid4(), trigger=AuditTrigger.manual)
        ]
        session = _make_session()
        session.execute.return_value = _mock_scalars_all(runs)

        repo = AuditRunRepository(session)
        result = await repo.list_for_tenant(uuid.uuid4())
        assert result == runs

    @pytest.mark.asyncio
    async def test_update_status(self):
        run = AuditRun(
            tenant_id=uuid.uuid4(), business_id=uuid.uuid4(), trigger=AuditTrigger.manual
        )
        session = _make_session()
        session.execute.return_value = _mock_scalar_one_or_none(run)

        repo = AuditRunRepository(session)
        updated = await repo.update_status(
            run.id,
            status=AuditStatus.completed,
            ai_visibility_score=75.0,
            completeness_pct=1.0,
        )
        assert updated.status == AuditStatus.completed
        assert updated.ai_visibility_score == 75.0
        assert updated.completeness_pct == 1.0


class TestQueryExecutionRepository:
    @pytest.mark.asyncio
    async def test_create(self):
        session = _make_session()
        repo = QueryExecutionRepository(session)
        rid = uuid.uuid4()
        tid = uuid.uuid4()
        eid = uuid.uuid4()

        qe = await repo.create(
            audit_run_id=rid,
            tenant_id=tid,
            engine_descriptor_id=eid,
            query_text="test query",
        )
        assert qe.audit_run_id == rid
        assert qe.query_text == "test query"
        assert qe.status == QueryExecutionStatus.pending

    @pytest.mark.asyncio
    async def test_get_by_id_not_found_raises(self):
        session = _make_session()
        session.execute.return_value = _mock_scalar_one_or_none(None)

        repo = QueryExecutionRepository(session)
        with pytest.raises(NotFoundError):
            await repo.get_by_id(uuid.uuid4())

    @pytest.mark.asyncio
    async def test_list_for_run(self):
        qes = [
            QueryExecution(
                audit_run_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                engine_descriptor_id=uuid.uuid4(),
                query_text="q",
            )
        ]
        session = _make_session()
        session.execute.return_value = _mock_scalars_all(qes)

        repo = QueryExecutionRepository(session)
        result = await repo.list_for_run(uuid.uuid4())
        assert result == qes

    @pytest.mark.asyncio
    async def test_update(self):
        qe = QueryExecution(
            audit_run_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            engine_descriptor_id=uuid.uuid4(),
            query_text="query",
        )
        session = _make_session()
        session.execute.return_value = _mock_scalar_one_or_none(qe)

        repo = QueryExecutionRepository(session)
        updated = await repo.update(
            qe.id,
            status=QueryExecutionStatus.succeeded,
            response_text="response",
            latency_ms=500,
            cost_usd=0.001,
        )
        assert updated.status == QueryExecutionStatus.succeeded
        assert updated.response_text == "response"
        assert updated.latency_ms == 500


class TestCitationRepository:
    @pytest.mark.asyncio
    async def test_create(self):
        session = _make_session()
        repo = CitationRepository(session)

        cit = await repo.create(
            query_execution_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            business_id=uuid.uuid4(),
            cited=True,
            confidence=0.99,
        )
        assert cit.cited is True
        assert cit.confidence == 0.99
        assert cit.polarity == CitationPolarity.neutral

    @pytest.mark.asyncio
    async def test_list_for_run(self):
        citations = [
            Citation(
                query_execution_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                business_id=uuid.uuid4(),
                cited=True,
                confidence=0.9,
            )
        ]
        session = _make_session()
        session.execute.return_value = _mock_scalars_all(citations)

        repo = CitationRepository(session)
        result = await repo.list_for_run(uuid.uuid4())
        assert result == citations


class TestEngineDescriptorRepository:
    @pytest.mark.asyncio
    async def test_get_by_slug_found(self):
        ed = EngineDescriptor(
            slug="openai-v1",
            display_name="ChatGPT",
            provider="openai",
            adapter_class="...",
        )
        session = _make_session()
        session.execute.return_value = _mock_scalar_one_or_none(ed)

        repo = EngineDescriptorRepository(session)
        result = await repo.get_by_slug("openai-v1")
        assert result is ed

    @pytest.mark.asyncio
    async def test_get_by_slug_not_found_raises(self):
        session = _make_session()
        session.execute.return_value = _mock_scalar_one_or_none(None)

        repo = EngineDescriptorRepository(session)
        with pytest.raises(NotFoundError):
            await repo.get_by_slug("nonexistent")

    @pytest.mark.asyncio
    async def test_list_active(self):
        eds = [
            EngineDescriptor(
                slug="openai-v1", display_name="ChatGPT", provider="openai", adapter_class="..."
            )
        ]
        session = _make_session()
        session.execute.return_value = _mock_scalars_all(eds)

        repo = EngineDescriptorRepository(session)
        result = await repo.list_active()
        assert result == eds


class TestCompetitorObservationRepository:
    @pytest.mark.asyncio
    async def test_create(self):
        session = _make_session()
        repo = CompetitorObservationRepository(session)

        obs = await repo.create(
            audit_run_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            business_id=uuid.uuid4(),
            competitor_name="Singh Dental",
            competitor_name_normalized="singh dental",
        )
        assert obs.competitor_name == "Singh Dental"
        assert obs.mention_count == 1

    @pytest.mark.asyncio
    async def test_list_for_run(self):
        observations = [
            CompetitorObservation(
                audit_run_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                business_id=uuid.uuid4(),
                competitor_name="Singh Dental",
                competitor_name_normalized="singh dental",
            )
        ]
        session = _make_session()
        session.execute.return_value = _mock_scalars_all(observations)

        repo = CompetitorObservationRepository(session)
        result = await repo.list_for_run(uuid.uuid4())
        assert result == observations
