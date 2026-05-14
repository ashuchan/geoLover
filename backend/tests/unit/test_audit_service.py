"""Unit tests for AuditService."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import BusinessNotFoundError
from app.modules.audit.models import (
    AuditRun,
    AuditStatus,
    AuditTrigger,
    Citation,
    CitationPolarity,
    CompetitorObservation,
    QueryExecution,
    QueryExecutionStatus,
)
from app.modules.audit.service import (
    AuditRunCompleted,
    AuditRunStarted,
    AuditService,
    CompetitorsObserved,
)
from app.modules.audit.identity import BusinessIdentity
from app.modules.engines.protocol import EngineResponse


def _make_session():
    session = MagicMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()
    return session


def _make_business(tenant_id: uuid.UUID):
    biz = MagicMock()
    biz.id = uuid.uuid4()
    biz.tenant_id = tenant_id
    biz.canonical_name = "Sharma Dental"
    biz.website_url = None
    biz.identity_uniqueness_score = 0.8
    return biz


def _make_run(tid: uuid.UUID, bid: uuid.UUID) -> AuditRun:
    return AuditRun(tenant_id=tid, business_id=bid, trigger=AuditTrigger.manual)


class TestAuditServiceCreateRun:
    def _make_svc(self, business):
        session = _make_session()
        svc = AuditService(session)
        svc._business_repo.get_by_id = AsyncMock(return_value=business)
        svc._audit_repo.create = AsyncMock(
            return_value=AuditRun(
                tenant_id=business.tenant_id,
                business_id=business.id,
                trigger=AuditTrigger.manual,
            )
        )
        return svc, session

    @pytest.mark.asyncio
    async def test_create_run_success(self):
        tid = uuid.uuid4()
        biz = _make_business(tid)
        svc, _ = self._make_svc(biz)

        run = await svc.create_audit_run(
            business_id=biz.id,
            tenant_id=tid,
            trigger=AuditTrigger.manual,
        )
        assert run.status == AuditStatus.pending
        assert len(svc._pending_events) == 1
        assert isinstance(svc._pending_events[0], AuditRunStarted)

    @pytest.mark.asyncio
    async def test_create_run_wrong_tenant_raises(self):
        tid = uuid.uuid4()
        biz = _make_business(uuid.uuid4())  # different tenant
        svc, _ = self._make_svc(biz)

        with pytest.raises(BusinessNotFoundError):
            await svc.create_audit_run(
                business_id=biz.id,
                tenant_id=tid,
                trigger=AuditTrigger.manual,
            )

    @pytest.mark.asyncio
    async def test_flush_events_calls_event_bus(self):
        tid = uuid.uuid4()
        biz = _make_business(tid)
        svc, _ = self._make_svc(biz)

        await svc.create_audit_run(
            business_id=biz.id,
            tenant_id=tid,
            trigger=AuditTrigger.manual,
        )

        with patch("app.modules.audit.service.event_bus") as mock_bus:
            mock_bus.publish = AsyncMock()
            await svc.flush_events()
            mock_bus.publish.assert_called_once()
        assert len(svc._pending_events) == 0


class TestAuditServiceGetAndList:
    @pytest.mark.asyncio
    async def test_get_audit_run(self):
        session = _make_session()
        svc = AuditService(session)
        run = AuditRun(
            tenant_id=uuid.uuid4(), business_id=uuid.uuid4(), trigger=AuditTrigger.manual
        )
        svc._audit_repo.get_by_id = AsyncMock(return_value=run)

        result = await svc.get_audit_run(run.id)
        assert result is run

    @pytest.mark.asyncio
    async def test_list_audit_runs(self):
        session = _make_session()
        svc = AuditService(session)
        tid = uuid.uuid4()
        runs = [
            AuditRun(tenant_id=tid, business_id=uuid.uuid4(), trigger=AuditTrigger.weekly)
        ]
        svc._audit_repo.list_for_tenant = AsyncMock(return_value=runs)

        result = await svc.list_audit_runs(tid)
        assert result == runs


class TestAuditServiceBuildIdentity:
    @pytest.mark.asyncio
    async def test_build_identity_basic(self):
        session = _make_session()
        svc = AuditService(session)
        tid = uuid.uuid4()
        biz = _make_business(tid)
        biz.primary_location_id = None

        svc._business_repo.get_by_id = AsyncMock(return_value=biz)
        svc._alias_repo.list_for_business = AsyncMock(return_value=[])
        svc._location_repo.list_for_business = AsyncMock(return_value=[])
        svc._keyword_repo.list_for_business = AsyncMock(return_value=[])

        identity = await svc.build_business_identity(biz.id)
        assert identity.canonical_name == biz.canonical_name
        assert identity.business_id == biz.id

    @pytest.mark.asyncio
    async def test_build_identity_with_location(self):
        session = _make_session()
        svc = AuditService(session)
        tid = uuid.uuid4()
        biz = _make_business(tid)

        location = MagicMock()
        location.is_primary = True
        location.locality = "Koramangala"
        location.city = "Bengaluru"

        svc._business_repo.get_by_id = AsyncMock(return_value=biz)
        svc._alias_repo.list_for_business = AsyncMock(return_value=[])
        svc._location_repo.list_for_business = AsyncMock(return_value=[location])
        svc._keyword_repo.list_for_business = AsyncMock(return_value=[])

        identity = await svc.build_business_identity(biz.id)
        assert identity.primary_locality == "Koramangala"
        assert identity.primary_city == "Bengaluru"


class TestAuditServiceFinalise:
    def _setup_svc(self, executions, citations, observations):
        session = _make_session()
        svc = AuditService(session)
        svc._qe_repo.list_for_run = AsyncMock(return_value=executions)
        svc._citation_repo.list_for_run = AsyncMock(return_value=citations)
        svc._competitor_repo.list_for_run = AsyncMock(return_value=observations)
        svc._audit_repo.update_status = AsyncMock(
            side_effect=lambda run_id, **kw: _make_run_with_status(
                kw.get("status", AuditStatus.pending)
            )
        )
        return svc

    @pytest.mark.asyncio
    async def test_finalise_completed_when_all_successful(self):
        executions = [
            _make_qe(QueryExecutionStatus.succeeded) for _ in range(10)
        ]
        citations = []
        svc = self._setup_svc(executions, citations, [])

        with patch("app.modules.audit.service.event_bus"):
            run = await svc.finalise_audit_run(
                uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                business_id=uuid.uuid4(),
            )
        assert run.status == AuditStatus.completed

    @pytest.mark.asyncio
    async def test_finalise_partial_when_60_percent_successful(self):
        executions = [
            _make_qe(QueryExecutionStatus.succeeded) if i < 7 else _make_qe(QueryExecutionStatus.failed)
            for i in range(10)
        ]
        svc = self._setup_svc(executions, [], [])

        with patch("app.modules.audit.service.event_bus"):
            run = await svc.finalise_audit_run(
                uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                business_id=uuid.uuid4(),
            )
        assert run.status == AuditStatus.partial

    @pytest.mark.asyncio
    async def test_finalise_failed_when_below_60_percent(self):
        executions = [
            _make_qe(QueryExecutionStatus.succeeded) if i < 5 else _make_qe(QueryExecutionStatus.failed)
            for i in range(10)
        ]
        svc = self._setup_svc(executions, [], [])

        with patch("app.modules.audit.service.event_bus"):
            run = await svc.finalise_audit_run(
                uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                business_id=uuid.uuid4(),
            )
        assert run.status == AuditStatus.failed

    @pytest.mark.asyncio
    async def test_finalise_emits_run_completed_event(self):
        executions = [_make_qe(QueryExecutionStatus.succeeded) for _ in range(5)]
        svc = self._setup_svc(executions, [], [])

        await svc.finalise_audit_run(
            uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            business_id=uuid.uuid4(),
        )
        events = [e for e in svc._pending_events if isinstance(e, AuditRunCompleted)]
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_finalise_emits_competitors_observed_when_present(self):
        executions = [_make_qe(QueryExecutionStatus.succeeded) for _ in range(5)]
        observations = [
            MagicMock(competitor_name="Singh Dental"),
            MagicMock(competitor_name="City Dental"),
        ]
        svc = self._setup_svc(executions, [], observations)

        await svc.finalise_audit_run(
            uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            business_id=uuid.uuid4(),
        )
        events = [e for e in svc._pending_events if isinstance(e, CompetitorsObserved)]
        assert len(events) == 1
        assert "Singh Dental" in events[0].competitor_names


def _make_qe(status: QueryExecutionStatus) -> QueryExecution:
    qe = QueryExecution(
        audit_run_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        engine_descriptor_id=uuid.uuid4(),
        query_text="test",
        status=status,
    )
    return qe


def _make_run_with_status(status: AuditStatus) -> AuditRun:
    run = AuditRun(
        tenant_id=uuid.uuid4(), business_id=uuid.uuid4(), trigger=AuditTrigger.manual
    )
    run.status = status
    return run


class TestAuditServiceRunSingleQuery:
    def _make_svc(self):
        session = _make_session()
        svc = AuditService(session)
        tid = uuid.uuid4()
        bid = uuid.uuid4()
        eid = uuid.uuid4()
        rid = uuid.uuid4()

        qe = QueryExecution(
            audit_run_id=rid, tenant_id=tid, engine_descriptor_id=eid, query_text="test"
        )
        svc._qe_repo.create = AsyncMock(return_value=qe)
        svc._qe_repo.update = AsyncMock(return_value=qe)
        svc._citation_repo.create = AsyncMock(
            return_value=Citation(
                query_execution_id=qe.id,
                tenant_id=tid,
                business_id=bid,
                cited=True,
                confidence=0.99,
            )
        )
        svc._competitor_repo.create = AsyncMock(return_value=MagicMock())
        return svc, tid, bid, eid, rid

    def _make_identity(self):
        import uuid
        return BusinessIdentity.build(
            business_id=uuid.uuid4(),
            canonical_name="Sharma Dental",
            primary_city="Bengaluru",
            primary_locality="Koramangala",
            name_uniqueness_score=0.9,
        )

    @pytest.mark.asyncio
    async def test_run_single_query_none_response(self):
        svc, tid, bid, eid, rid = self._make_svc()
        identity = self._make_identity()

        qe, citation = await svc.run_single_query(
            audit_run_id=rid,
            tenant_id=tid,
            business_id=bid,
            engine_descriptor_id=eid,
            engine_slug="openai-v1",
            query_text="test",
            identity=identity,
            engine_response=None,
        )
        assert qe is not None
        assert citation is None

    @pytest.mark.asyncio
    async def test_run_single_query_with_successful_response(self):
        svc, tid, bid, eid, rid = self._make_svc()
        identity = self._make_identity()

        response = EngineResponse(
            engine_slug="openai-v1",
            query_text="test",
            response_text="Sharma Dental in Koramangala is excellent.",
            latency_ms=200,
            cost_usd=0.001,
            success=True,
        )

        qe, citation = await svc.run_single_query(
            audit_run_id=rid,
            tenant_id=tid,
            business_id=bid,
            engine_descriptor_id=eid,
            engine_slug="openai-v1",
            query_text="Best dental clinic",
            identity=identity,
            engine_response=response,
        )
        assert qe is not None
        assert citation is not None

    @pytest.mark.asyncio
    async def test_run_single_query_failed_response_no_citation(self):
        svc, tid, bid, eid, rid = self._make_svc()
        identity = self._make_identity()

        response = EngineResponse(
            engine_slug="openai-v1",
            query_text="test",
            response_text="",
            latency_ms=0,
            cost_usd=0.0,
            success=False,
        )

        qe, citation = await svc.run_single_query(
            audit_run_id=rid,
            tenant_id=tid,
            business_id=bid,
            engine_descriptor_id=eid,
            engine_slug="openai-v1",
            query_text="test",
            identity=identity,
            engine_response=response,
        )
        assert qe is not None
        assert citation is None

    @pytest.mark.asyncio
    async def test_pending_events_property(self):
        session = _make_session()
        svc = AuditService(session)
        tid = uuid.uuid4()
        biz = _make_business(tid)
        svc._business_repo.get_by_id = AsyncMock(return_value=biz)
        svc._audit_repo.create = AsyncMock(
            return_value=AuditRun(tenant_id=tid, business_id=biz.id, trigger=AuditTrigger.manual)
        )

        await svc.create_audit_run(
            business_id=biz.id, tenant_id=tid, trigger=AuditTrigger.manual
        )
        events = svc.pending_events
        assert len(events) == 1
