"""AuditService — orchestrates audit creation, execution, and completion.

Domain events:
- AuditRunStarted: emitted when an audit run begins
- AuditRunCompleted: emitted when audit run reaches completed/partial/failed status
- CompetitorsObserved: emitted when competitor observations are made
"""

from __future__ import annotations

import logging
import re
import unicodedata
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import DomainEvent, event_bus
from app.core.exceptions import (
    BusinessNotFoundError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
)
from app.modules.audit.citation_detector import CitationDetector, Polarity
from app.modules.audit.identity import BusinessIdentity, NormalisedAlias
from app.modules.audit.models import (
    AuditStatus,
    AuditTrigger,
    CitationMatchType,
    CitationPolarity,
    QueryExecutionStatus,
)
from app.modules.audit.query_generator import QueryGenerator
from app.modules.audit.repository import (
    AuditRunRepository,
    CitationRepository,
    CompetitorObservationRepository,
    QueryExecutionRepository,
    QueryTemplateRepository,
)
from app.modules.audit.score_calculator import (
    AIVisibilityScoreCalculator,
    EngineQueryStats,
)
from app.modules.business_profile.repository import (
    BusinessAliasRepository,
    BusinessKeywordRepository,
    BusinessLocationRepository,
    BusinessRepository,
)
from app.modules.engines.protocol import EngineResponse, ProbeBudget, QueryIntent
from app.modules.engines.registry import engine_registry

_log = logging.getLogger(__name__)


# ── Domain events ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AuditRunStarted(DomainEvent):
    audit_run_id: uuid.UUID = uuid.UUID(int=0)
    business_id: uuid.UUID = uuid.UUID(int=0)
    tenant_id: uuid.UUID = uuid.UUID(int=0)


@dataclass(frozen=True)
class AuditRunCompleted(DomainEvent):
    audit_run_id: uuid.UUID = uuid.UUID(int=0)
    business_id: uuid.UUID = uuid.UUID(int=0)
    tenant_id: uuid.UUID = uuid.UUID(int=0)
    ai_visibility_score: float = 0.0
    completeness_pct: float = 0.0
    status: str = "completed"


@dataclass(frozen=True)
class CompetitorsObserved(DomainEvent):
    audit_run_id: uuid.UUID = uuid.UUID(int=0)
    business_id: uuid.UUID = uuid.UUID(int=0)
    tenant_id: uuid.UUID = uuid.UUID(int=0)
    competitor_names: tuple[str, ...] = ()


# ── AuditService ──────────────────────────────────────────────────────────────


class AuditService:
    """Service for audit operations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._audit_repo = AuditRunRepository(session)
        self._qe_repo = QueryExecutionRepository(session)
        self._citation_repo = CitationRepository(session)
        self._competitor_repo = CompetitorObservationRepository(session)
        self._template_repo = QueryTemplateRepository(session)
        self._business_repo = BusinessRepository(session)
        self._alias_repo = BusinessAliasRepository(session)
        self._location_repo = BusinessLocationRepository(session)
        self._keyword_repo = BusinessKeywordRepository(session)
        self._pending_events: list[DomainEvent] = []

    @property
    def pending_events(self) -> list[DomainEvent]:
        return list(self._pending_events)

    async def flush_pending_events(self) -> None:
        """Alias for flush_events for API consistency."""
        await self.flush_events()

    async def create_audit_run(
        self,
        *,
        business_id: uuid.UUID,
        tenant_id: uuid.UUID,
        trigger: AuditTrigger,
        algorithm_version: str = "v1",
        workflow_run_id: Optional[str] = None,
    ):
        """Create a new pending audit run."""
        # Verify business exists
        business = await self._business_repo.get_by_id(business_id)
        if business.tenant_id != tenant_id:
            raise BusinessNotFoundError(f"Business {business_id} not found in tenant {tenant_id}")

        run = await self._audit_repo.create(
            tenant_id=tenant_id,
            business_id=business_id,
            trigger=trigger,
            status=AuditStatus.pending,
            algorithm_version=algorithm_version,
            workflow_run_id=workflow_run_id,
        )
        self._pending_events.append(
            AuditRunStarted(
                audit_run_id=run.id,
                business_id=business_id,
                tenant_id=tenant_id,
            )
        )
        return run

    async def get_audit_run(self, audit_run_id: uuid.UUID):
        return await self._audit_repo.get_by_id(audit_run_id)

    async def list_audit_runs(
        self,
        tenant_id: uuid.UUID,
        *,
        business_id: Optional[uuid.UUID] = None,
        limit: int = 20,
        offset: int = 0,
    ):
        return await self._audit_repo.list_for_tenant(
            tenant_id,
            business_id=business_id,
            limit=limit,
            offset=offset,
        )

    async def build_business_identity(self, business_id: uuid.UUID) -> BusinessIdentity:
        """Build a BusinessIdentity from stored business profile data."""
        business = await self._business_repo.get_by_id(business_id)
        aliases = await self._alias_repo.list_for_business(business_id)
        locations = await self._location_repo.list_for_business(business_id)
        keywords = await self._keyword_repo.list_for_business(business_id)

        primary_location = next((l for l in locations if l.is_primary), None) or (locations[0] if locations else None)

        normalised_aliases = [
            NormalisedAlias(
                text=a.alias_text,
                text_normalized=a.alias_text_normalized,
                alias_type=a.alias_type.value,
            )
            for a in aliases
        ]

        return BusinessIdentity.build(
            business_id=business.id,
            canonical_name=business.canonical_name,
            aliases=normalised_aliases,
            website_url=business.website_url,
            primary_locality=primary_location.locality if primary_location else None,
            primary_city=primary_location.city if primary_location else None,
            name_uniqueness_score=business.identity_uniqueness_score or 0.5,
            keywords=[k.keyword for k in keywords[:10]],
        )

    async def run_single_query(
        self,
        *,
        audit_run_id: uuid.UUID,
        tenant_id: uuid.UUID,
        business_id: uuid.UUID,
        engine_descriptor_id: uuid.UUID,
        engine_slug: str,
        query_text: str,
        query_template_id: Optional[uuid.UUID] = None,
        identity: BusinessIdentity,
        engine_response: Optional[EngineResponse] = None,
    ):
        """Process a single query execution: persist result + run citation detection."""

        if engine_response is None:
            qe = await self._qe_repo.create(
                audit_run_id=audit_run_id,
                tenant_id=tenant_id,
                engine_descriptor_id=engine_descriptor_id,
                query_text=query_text,
                query_template_id=query_template_id,
                status=QueryExecutionStatus.failed,
            )
            return qe, None

        status = QueryExecutionStatus.succeeded if engine_response.success else QueryExecutionStatus.failed
        qe = await self._qe_repo.create(
            audit_run_id=audit_run_id,
            tenant_id=tenant_id,
            engine_descriptor_id=engine_descriptor_id,
            query_text=query_text,
            query_template_id=query_template_id,
            status=status,
        )

        citation_result = None
        if engine_response.success and engine_response.response_text:
            await self._qe_repo.update(
                qe.id,
                response_text=engine_response.response_text[:4096],
                latency_ms=engine_response.latency_ms,
                cost_usd=engine_response.cost_usd,
                executed_at=datetime.now(timezone.utc),
            )

            detector = CitationDetector()
            result = detector.detect(engine_response.response_text, identity)

            match_type_map = {
                "exact_name": CitationMatchType.exact_name,
                "alias": CitationMatchType.alias,
                "phone": CitationMatchType.phone,
                "website": CitationMatchType.website,
                "address": CitationMatchType.address,
                "fuzzy_name": CitationMatchType.fuzzy_name,
                "composite": CitationMatchType.composite,
            }
            polarity_map = {
                Polarity.positive: CitationPolarity.positive,
                Polarity.neutral: CitationPolarity.neutral,
                Polarity.negative: CitationPolarity.negative,
            }

            citation_result = await self._citation_repo.create(
                query_execution_id=qe.id,
                tenant_id=tenant_id,
                business_id=business_id,
                cited=result.cited,
                confidence=result.confidence,
                match_type=match_type_map.get(result.match_type.value) if result.match_type else None,
                polarity=polarity_map.get(result.polarity, CitationPolarity.neutral),
                snippet=result.snippet[:280] if result.snippet else "",
                snippet_start_pos=result.snippet_start_pos,
                corroborating_signals=list(result.corroborating_signals),
                competitors_mentioned=list(result.competitors_mentioned),
                algorithm_version=result.algorithm_version,
            )

            # Record competitor observations
            for comp_name in result.competitors_mentioned:
                nfkd = unicodedata.normalize("NFKD", comp_name)
                norm = "".join(c for c in nfkd if not unicodedata.combining(c)).lower()
                norm = re.sub(r"\s+", " ", norm).strip()
                await self._competitor_repo.create(
                    audit_run_id=audit_run_id,
                    tenant_id=tenant_id,
                    business_id=business_id,
                    competitor_name=comp_name,
                    competitor_name_normalized=norm,
                    first_seen_in_execution_id=qe.id,
                )

        return qe, citation_result

    async def finalise_audit_run(
        self,
        audit_run_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        business_id: uuid.UUID,
    ):
        """Compute final score and update AuditRun status."""
        # Get all query executions
        executions = await self._qe_repo.list_for_run(audit_run_id)
        citations = await self._citation_repo.list_for_run(audit_run_id)

        total = len(executions)
        successful = sum(1 for qe in executions if qe.status == QueryExecutionStatus.succeeded)
        completeness_pct = successful / total if total > 0 else 0.0

        # Group stats by engine
        engine_stats_map: dict[str, dict] = defaultdict(lambda: {
            "total": 0, "successful": 0, "cited": 0, "negative": 0
        })

        citation_by_qe = {c.query_execution_id: c for c in citations}

        for qe in executions:
            slug = str(qe.engine_descriptor_id)  # use descriptor ID as key for now
            engine_stats_map[slug]["total"] += 1
            if qe.status == QueryExecutionStatus.succeeded:
                engine_stats_map[slug]["successful"] += 1
                c = citation_by_qe.get(qe.id)
                if c and c.cited:
                    engine_stats_map[slug]["cited"] += 1
                    if c.polarity == CitationPolarity.negative:
                        engine_stats_map[slug]["negative"] += 1

        stats = [
            EngineQueryStats(
                engine_id=slug,
                queries_total=v["total"],
                queries_successful=v["successful"],
                queries_cited=v["cited"],
                queries_negative=v["negative"],
            )
            for slug, v in engine_stats_map.items()
        ]

        calc = AIVisibilityScoreCalculator()
        score_result = calc.calculate(stats)

        if completeness_pct >= 0.95:
            final_status = AuditStatus.completed
        elif completeness_pct >= 0.60:
            final_status = AuditStatus.partial
        else:
            final_status = AuditStatus.failed

        run = await self._audit_repo.update_status(
            audit_run_id,
            status=final_status,
            completed_at=datetime.now(timezone.utc),
            ai_visibility_score=score_result.audit_score,
            completeness_pct=completeness_pct,
            queries_total=total,
            queries_successful=successful,
        )

        # Emit events
        self._pending_events.append(
            AuditRunCompleted(
                audit_run_id=audit_run_id,
                business_id=business_id,
                tenant_id=tenant_id,
                ai_visibility_score=score_result.audit_score,
                completeness_pct=completeness_pct,
                status=final_status.value,
            )
        )

        # Emit competitor observations event
        observations = await self._competitor_repo.list_for_run(audit_run_id)
        if observations:
            names = tuple(o.competitor_name for o in observations)
            self._pending_events.append(
                CompetitorsObserved(
                    audit_run_id=audit_run_id,
                    business_id=business_id,
                    tenant_id=tenant_id,
                    competitor_names=names,
                )
            )

        return run

    async def flush_events(self) -> None:
        for event in self._pending_events:
            await event_bus.publish(event)
        self._pending_events.clear()
