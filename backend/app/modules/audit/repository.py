"""Repository layer for Audit module.

All RLS-protected queries run under the tenant context set by the calling session.
Global reference data (query_template_sets, query_templates, engine_descriptors)
has no RLS and can be queried without tenant context.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.modules.audit.models import (
    AuditRun,
    AuditStatus,
    AuditTrigger,
    Citation,
    CitationMatchType,
    CitationPolarity,
    CompetitorObservation,
    EngineDescriptor,
    QueryExecution,
    QueryExecutionStatus,
    QueryTemplate,
    QueryTemplateSet,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AuditRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, audit_run_id: uuid.UUID) -> AuditRun:
        result = await self._session.execute(
            select(AuditRun).where(AuditRun.id == audit_run_id)
        )
        run = result.scalar_one_or_none()
        if run is None:
            raise NotFoundError(f"AuditRun {audit_run_id} not found")
        return run

    async def list_for_tenant(
        self,
        tenant_id: uuid.UUID,
        *,
        business_id: Optional[uuid.UUID] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[AuditRun]:
        stmt = select(AuditRun).where(AuditRun.tenant_id == tenant_id)
        if business_id is not None:
            stmt = stmt.where(AuditRun.business_id == business_id)
        stmt = stmt.order_by(AuditRun.created_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        business_id: uuid.UUID,
        trigger: AuditTrigger,
        status: AuditStatus = AuditStatus.pending,
        algorithm_version: str = "v1",
        workflow_run_id: Optional[str] = None,
    ) -> AuditRun:
        run = AuditRun(
            tenant_id=tenant_id,
            business_id=business_id,
            trigger=trigger,
            status=status,
            algorithm_version=algorithm_version,
            workflow_run_id=workflow_run_id,
        )
        self._session.add(run)
        await self._session.flush()
        return run

    async def update_status(
        self,
        audit_run_id: uuid.UUID,
        *,
        status: AuditStatus,
        started_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
        ai_visibility_score: Optional[float] = None,
        completeness_pct: Optional[float] = None,
        queries_total: Optional[int] = None,
        queries_successful: Optional[int] = None,
        queries_cited: Optional[int] = None,
        queries_negative: Optional[int] = None,
    ) -> AuditRun:
        run = await self.get_by_id(audit_run_id)
        run.status = status
        if started_at is not None:
            run.started_at = started_at
        if completed_at is not None:
            run.completed_at = completed_at
        if ai_visibility_score is not None:
            run.ai_visibility_score = ai_visibility_score
        if completeness_pct is not None:
            run.completeness_pct = completeness_pct
        if queries_total is not None:
            run.queries_total = queries_total
        if queries_successful is not None:
            run.queries_successful = queries_successful
        if queries_cited is not None:
            run.queries_cited = queries_cited
        if queries_negative is not None:
            run.queries_negative = queries_negative
        await self._session.flush()
        return run


class QueryExecutionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        audit_run_id: uuid.UUID,
        tenant_id: uuid.UUID,
        engine_descriptor_id: uuid.UUID,
        query_text: str,
        query_template_id: Optional[uuid.UUID] = None,
        status: QueryExecutionStatus = QueryExecutionStatus.pending,
    ) -> QueryExecution:
        qe = QueryExecution(
            audit_run_id=audit_run_id,
            tenant_id=tenant_id,
            engine_descriptor_id=engine_descriptor_id,
            query_text=query_text,
            query_template_id=query_template_id,
            status=status,
        )
        self._session.add(qe)
        await self._session.flush()
        return qe

    async def get_by_id(self, execution_id: uuid.UUID) -> QueryExecution:
        result = await self._session.execute(
            select(QueryExecution).where(QueryExecution.id == execution_id)
        )
        qe = result.scalar_one_or_none()
        if qe is None:
            raise NotFoundError(f"QueryExecution {execution_id} not found")
        return qe

    async def list_for_run(self, audit_run_id: uuid.UUID) -> Sequence[QueryExecution]:
        result = await self._session.execute(
            select(QueryExecution).where(QueryExecution.audit_run_id == audit_run_id)
        )
        return result.scalars().all()

    async def update(
        self,
        execution_id: uuid.UUID,
        *,
        status: Optional[QueryExecutionStatus] = None,
        response_text: Optional[str] = None,
        error_message: Optional[str] = None,
        latency_ms: Optional[int] = None,
        cost_usd: Optional[float] = None,
        executed_at: Optional[datetime] = None,
    ) -> QueryExecution:
        qe = await self.get_by_id(execution_id)
        if status is not None:
            qe.status = status
        if response_text is not None:
            qe.response_text = response_text
        if error_message is not None:
            qe.error_message = error_message
        if latency_ms is not None:
            qe.latency_ms = latency_ms
        if cost_usd is not None:
            qe.cost_usd = cost_usd
        if executed_at is not None:
            qe.executed_at = executed_at
        await self._session.flush()
        return qe


class CitationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        query_execution_id: uuid.UUID,
        tenant_id: uuid.UUID,
        business_id: uuid.UUID,
        cited: bool,
        confidence: float,
        match_type: Optional[CitationMatchType] = None,
        polarity: CitationPolarity = CitationPolarity.neutral,
        snippet: str = "",
        snippet_start_pos: int = 0,
        corroborating_signals: list[str] | None = None,
        competitors_mentioned: list[str] | None = None,
        algorithm_version: str = "v1",
    ) -> Citation:
        citation = Citation(
            query_execution_id=query_execution_id,
            tenant_id=tenant_id,
            business_id=business_id,
            cited=cited,
            confidence=confidence,
            match_type=match_type,
            polarity=polarity,
            snippet=snippet,
            snippet_start_pos=snippet_start_pos,
            corroborating_signals=corroborating_signals or [],
            competitors_mentioned=competitors_mentioned or [],
            algorithm_version=algorithm_version,
        )
        self._session.add(citation)
        await self._session.flush()
        return citation

    async def list_for_run(self, audit_run_id: uuid.UUID) -> Sequence[Citation]:
        """Get citations by joining through query_executions."""
        stmt = (
            select(Citation)
            .join(QueryExecution, Citation.query_execution_id == QueryExecution.id)
            .where(QueryExecution.audit_run_id == audit_run_id)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()


class CompetitorObservationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        audit_run_id: uuid.UUID,
        tenant_id: uuid.UUID,
        business_id: uuid.UUID,
        competitor_name: str,
        competitor_name_normalized: str,
        mention_count: int = 1,
        first_seen_in_execution_id: Optional[uuid.UUID] = None,
    ) -> CompetitorObservation:
        obs = CompetitorObservation(
            audit_run_id=audit_run_id,
            tenant_id=tenant_id,
            business_id=business_id,
            competitor_name=competitor_name,
            competitor_name_normalized=competitor_name_normalized,
            mention_count=mention_count,
            first_seen_in_execution_id=first_seen_in_execution_id,
        )
        self._session.add(obs)
        await self._session.flush()
        return obs

    async def list_for_run(self, audit_run_id: uuid.UUID) -> Sequence[CompetitorObservation]:
        result = await self._session.execute(
            select(CompetitorObservation).where(
                CompetitorObservation.audit_run_id == audit_run_id
            )
        )
        return result.scalars().all()


class EngineDescriptorRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, engine_id: uuid.UUID) -> EngineDescriptor:
        result = await self._session.execute(
            select(EngineDescriptor).where(EngineDescriptor.id == engine_id)
        )
        ed = result.scalar_one_or_none()
        if ed is None:
            raise NotFoundError(f"EngineDescriptor {engine_id} not found")
        return ed

    async def get_by_slug(self, slug: str) -> EngineDescriptor:
        result = await self._session.execute(
            select(EngineDescriptor).where(EngineDescriptor.slug == slug)
        )
        ed = result.scalar_one_or_none()
        if ed is None:
            raise NotFoundError(f"EngineDescriptor slug={slug} not found")
        return ed

    async def list_active(self) -> Sequence[EngineDescriptor]:
        from app.modules.audit.models import EngineHealth
        result = await self._session.execute(
            select(EngineDescriptor).where(
                EngineDescriptor.health.in_([EngineHealth.healthy, EngineHealth.degraded])
            )
        )
        return result.scalars().all()


class QueryTemplateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_set(self, template_set_id: uuid.UUID) -> Sequence[QueryTemplate]:
        result = await self._session.execute(
            select(QueryTemplate)
            .where(QueryTemplate.template_set_id == template_set_id)
            .order_by(QueryTemplate.priority)
        )
        return result.scalars().all()

    async def get_default_set(self) -> Optional[QueryTemplateSet]:
        result = await self._session.execute(
            select(QueryTemplateSet).where(QueryTemplateSet.is_default.is_(True))
        )
        return result.scalar_one_or_none()
