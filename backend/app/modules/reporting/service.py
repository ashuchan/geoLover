"""ReportService and FreeAuditSubmissionService.

Domain events:
- ReportGenerated: emitted when a report reaches 'ready' status
- FreeAuditSubmitted: emitted when a free-audit form submission is accepted
"""

from __future__ import annotations

import logging
import re
import secrets
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import DomainEvent, event_bus
from app.core.exceptions import ConflictError, NotFoundError, PermissionDeniedError
from app.modules.audit.models import AuditStatus, AuditTrigger, QueryExecutionStatus
from app.modules.audit.repository import (
    AuditRunRepository,
    CitationRepository,
    CompetitorObservationRepository,
    QueryExecutionRepository,
)
from app.modules.business_profile.repository import (
    BusinessAliasRepository,
    BusinessKeywordRepository,
    BusinessLocationRepository,
    BusinessRepository,
    FreeAuditTokenRepository,
)
from app.modules.reporting.models import ReportStatus
from app.modules.reporting.quick_wins import AuditContext, QuickWinsGenerator
from app.modules.reporting.repository import ReportRepository, ShareLinkRepository

_log = logging.getLogger(__name__)

_FREE_AUDIT_TOKEN_TTL_DAYS = 14
_SHARE_LINK_TTL_DAYS = 30
_SHARE_TOKEN_LENGTH = 48
_WEB_VIEW_TOKEN_LENGTH = 32

# Common business-name suffixes to strip for dedup normalization
_BUSINESS_SUFFIXES = re.compile(
    r"\b(pvt\.?\s*ltd\.?|private\s+limited|limited|llp|inc\.?|co\.?|corp\.?|&)\b",
    re.IGNORECASE,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalise_business_name(name: str) -> str:
    """Normalise business name for deduplication: strip suffixes, diacritics, lowercase."""
    nfkd = unicodedata.normalize("NFKD", name)
    stripped = "".join(c for c in nfkd if not unicodedata.combining(c))
    lower = stripped.lower()
    no_suffix = _BUSINESS_SUFFIXES.sub("", lower)
    collapsed = re.sub(r"\s+", " ", no_suffix).strip()
    return collapsed


def _generate_token(length: int = 32) -> str:
    return secrets.token_urlsafe(length)[:length]


# ── Domain events ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ReportGenerated(DomainEvent):
    report_id: uuid.UUID = uuid.UUID(int=0)
    audit_run_id: uuid.UUID = uuid.UUID(int=0)
    business_id: uuid.UUID = uuid.UUID(int=0)
    tenant_id: uuid.UUID = uuid.UUID(int=0)
    web_view_token: str = ""


@dataclass(frozen=True)
class FreeAuditSubmitted(DomainEvent):
    audit_run_id: uuid.UUID = uuid.UUID(int=0)
    business_id: uuid.UUID = uuid.UUID(int=0)
    tenant_id: uuid.UUID = uuid.UUID(int=0)
    submitter_email_normalized: str = ""
    free_audit_token: str = ""


# ── ReportService ─────────────────────────────────────────────────────────────


class ReportService:
    """Service for report lifecycle: create, finalise, share."""

    def __init__(self, session: AsyncSession, *, gateway=None) -> None:
        self._session = session
        self._report_repo = ReportRepository(session)
        self._share_repo = ShareLinkRepository(session)
        self._audit_repo = AuditRunRepository(session)
        self._alias_repo = BusinessAliasRepository(session)
        self._keyword_repo = BusinessKeywordRepository(session)
        self._location_repo = BusinessLocationRepository(session)
        self._business_repo = BusinessRepository(session)
        self._gateway = gateway
        self._pending_events: list[DomainEvent] = []

    @property
    def pending_events(self) -> list[DomainEvent]:
        return list(self._pending_events)

    async def flush_events(self) -> None:
        for event in self._pending_events:
            await event_bus.publish(event)
        self._pending_events.clear()

    async def create_report(
        self,
        *,
        tenant_id: uuid.UUID,
        business_id: uuid.UUID,
        audit_run_id: uuid.UUID,
        score: Optional[float] = None,
        confidence_band: Optional[str] = None,
        completeness_pct: Optional[float] = None,
        template_version: str = "v1",
    ):
        """Create a new Report in 'generating' status."""
        web_view_token = _generate_token(_WEB_VIEW_TOKEN_LENGTH)
        return await self._report_repo.create(
            tenant_id=tenant_id,
            business_id=business_id,
            audit_run_id=audit_run_id,
            web_view_token=web_view_token,
            score=score,
            confidence_band=confidence_band,
            completeness_pct=completeness_pct,
            template_version=template_version,
        )

    async def get_report(self, report_id: uuid.UUID):
        return await self._report_repo.get_by_id(report_id)

    async def get_report_by_token(self, token: str):
        report = await self._report_repo.get_by_web_view_token(token)
        if report is None:
            raise NotFoundError(f"Report with token '{token}' not found")
        return report

    async def get_report_for_audit_run(self, audit_run_id: uuid.UUID):
        return await self._report_repo.get_by_audit_run(audit_run_id)

    async def list_reports_for_business(
        self,
        business_id: uuid.UUID,
        tenant_id: uuid.UUID,
        *,
        limit: int = 20,
        offset: int = 0,
    ):
        return await self._report_repo.list_for_business(
            business_id, tenant_id, limit=limit, offset=offset
        )

    async def finalise_report(
        self,
        report_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        business_id: uuid.UUID,
        audit_run_id: uuid.UUID,
    ):
        """Generate Quick Wins and mark report ready."""
        report = await self._report_repo.get_by_id(report_id)

        ctx = await self._build_audit_context(
            audit_run_id=audit_run_id,
            business_id=business_id,
            score=report.score or 0.0,
            confidence_band=report.confidence_band or "low",
            completeness_pct=report.completeness_pct or 0.0,
        )

        generator = QuickWinsGenerator(gateway=self._gateway)
        wins_list = await generator.generate(ctx)
        quick_wins = {"wins": wins_list, "generated_by": "v1"}

        report = await self._report_repo.mark_ready(
            report_id,
            quick_wins=quick_wins,
            score=report.score,
            confidence_band=report.confidence_band,
            completeness_pct=report.completeness_pct,
        )

        self._pending_events.append(
            ReportGenerated(
                report_id=report.id,
                audit_run_id=audit_run_id,
                business_id=business_id,
                tenant_id=tenant_id,
                web_view_token=report.web_view_token,
            )
        )
        return report

    async def mark_report_failed(self, report_id: uuid.UUID):
        return await self._report_repo.mark_failed(report_id)

    async def _build_audit_context(
        self,
        *,
        audit_run_id: uuid.UUID,
        business_id: uuid.UUID,
        score: float,
        confidence_band: str,
        completeness_pct: float,
    ) -> AuditContext:
        """Build AuditContext for Quick Wins generation from stored data."""
        business = await self._business_repo.get_by_id(business_id)
        locations = await self._location_repo.list_for_business(business_id)
        keywords = await self._keyword_repo.list_for_business(business_id)
        aliases = await self._alias_repo.list_for_business(business_id)

        primary_loc = next((l for l in locations if l.is_primary), None) or (
            locations[0] if locations else None
        )

        qe_repo = QueryExecutionRepository(self._session)
        citation_repo = CitationRepository(self._session)
        competitor_repo = CompetitorObservationRepository(self._session)

        executions = await qe_repo.list_for_run(audit_run_id)
        citations = await citation_repo.list_for_run(audit_run_id)
        competitors = await competitor_repo.list_for_run(audit_run_id)

        citation_by_qe = {c.query_execution_id: c for c in citations}

        lost_queries: list[str] = []
        winning_queries: list[str] = []
        lost_query_competitors: dict[str, str] = {}

        for qe in executions:
            if qe.status != QueryExecutionStatus.succeeded:
                continue
            c = citation_by_qe.get(qe.id)
            if c and c.cited:
                winning_queries.append(qe.query_text)
            else:
                lost_queries.append(qe.query_text)

        # Map lost queries to the competitor mentioned in that execution
        for qe in executions:
            if qe.query_text in lost_queries:
                c = citation_by_qe.get(qe.id)
                if c and c.competitors_mentioned:
                    lost_query_competitors[qe.query_text] = c.competitors_mentioned[0]

        engine_slugs = list({str(qe.engine_descriptor_id) for qe in executions})
        comp_names = [o.competitor_name for o in competitors]

        return AuditContext(
            business_name=business.canonical_name,
            category=getattr(business, "category", "") or "",
            locality=primary_loc.locality if primary_loc else "",
            city=primary_loc.city if primary_loc else "",
            keywords=[k.keyword for k in keywords[:10]],
            score=score,
            confidence_band=confidence_band,
            completeness_pct=completeness_pct,
            engines_covered=engine_slugs,
            lost_queries=lost_queries[:10],
            winning_queries=winning_queries[:5],
            competitors=comp_names[:10],
            lost_query_competitors=lost_query_competitors,
            has_phone=bool(getattr(business, "primary_phone_encrypted", None)),
            has_website=bool(business.website_url),
            has_description=bool(getattr(business, "description", None)),
            aliases_count=len(aliases),
        )

    # ── Share links ────────────────────────────────────────────────────────────

    async def create_share_link(
        self,
        *,
        report_id: uuid.UUID,
        tenant_id: uuid.UUID,
        created_by_user_id: Optional[uuid.UUID] = None,
        ttl_days: int = _SHARE_LINK_TTL_DAYS,
    ):
        """Create a new share link for a report."""
        report = await self._report_repo.get_by_id(report_id)
        if report.tenant_id != tenant_id:
            raise PermissionDeniedError("Report does not belong to this tenant")
        if report.status != ReportStatus.ready:
            raise ConflictError("Cannot share a report that is not ready")

        token = _generate_token(_SHARE_TOKEN_LENGTH)
        expires_at = _utcnow() + timedelta(days=ttl_days)
        return await self._share_repo.create(
            tenant_id=tenant_id,
            business_id=report.business_id,  # read from report, not caller
            report_id=report_id,
            token=token,
            expires_at=expires_at,
            created_by_user_id=created_by_user_id,
        )

    async def get_share_link_by_token(self, token: str):
        link = await self._share_repo.get_by_token(token)
        if link is None:
            raise NotFoundError(f"Share link '{token}' not found or expired")
        return link

    async def revoke_share_link(self, token: str, *, tenant_id: uuid.UUID):
        """Revoke a share link. Validates tenant ownership; works on expired/revoked links."""
        result = await self._share_repo.get_by_token_unrestricted(token)
        if result is None:
            raise NotFoundError(f"Share link '{token}' not found")
        if result.tenant_id != tenant_id:
            raise PermissionDeniedError("Share link does not belong to this tenant")
        return await self._share_repo.revoke(token)

    async def record_share_view(self, token: str) -> None:
        await self._share_repo.increment_view(token)


# ── FreeAuditSubmissionService ────────────────────────────────────────────────


class FreeAuditSubmissionService:
    """Handles free-audit form submission, idempotency, and token lifecycle."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._business_repo = BusinessRepository(session)
        self._location_repo = BusinessLocationRepository(session)
        self._keyword_repo = BusinessKeywordRepository(session)
        self._fat_repo = FreeAuditTokenRepository(session)
        self._audit_repo = AuditRunRepository(session)
        self._pending_events: list[DomainEvent] = []

    @property
    def pending_events(self) -> list[DomainEvent]:
        return list(self._pending_events)

    async def flush_events(self) -> None:
        for event in self._pending_events:
            await event_bus.publish(event)
        self._pending_events.clear()

    async def get_status(self, token: str) -> dict:
        """Return audit progress for a free-audit token."""
        fat = await self._fat_repo.get_by_token(token)
        if fat is None:
            raise NotFoundError(f"Free audit token '{token}' not found or expired")

        if fat.audit_run_id is None:
            return {
                "status": "pending",
                "progress": {
                    "completeness_pct": 0.0,
                    "queries_done": 0,
                    "queries_total": 0,
                },
                "report_ready": False,
                "claim_offered": False,
            }

        run = await self._audit_repo.get_by_id(fat.audit_run_id)
        completeness = getattr(run, "completeness_pct", 0.0) or 0.0
        queries_total = getattr(run, "queries_total", 0) or 0
        queries_done = getattr(run, "queries_successful", 0) or 0

        report_ready = run.status in (AuditStatus.completed, AuditStatus.partial)
        claim_offered = report_ready and fat.claimed_at is None

        return {
            "status": run.status.value,
            "progress": {
                "completeness_pct": completeness,
                "queries_done": queries_done,
                "queries_total": queries_total,
            },
            "report_ready": report_ready,
            "claim_offered": claim_offered,
        }

    async def submit(
        self,
        *,
        tenant_id: uuid.UUID,
        business_id: uuid.UUID,
        submitter_email_normalized: str,
        audit_run_id: uuid.UUID,
        submitter_ip: Optional[str] = None,
        submitter_user_agent: Optional[str] = None,
    ) -> str:
        """Record a free-audit submission and return the token string."""
        token = _generate_token(48)
        expires_at = _utcnow() + timedelta(days=_FREE_AUDIT_TOKEN_TTL_DAYS)

        fat = await self._fat_repo.create(
            token=token,
            business_id=business_id,
            tenant_id=tenant_id,
            expires_at=expires_at,
            audit_run_id=audit_run_id,
        )

        self._pending_events.append(
            FreeAuditSubmitted(
                audit_run_id=audit_run_id,
                business_id=business_id,
                tenant_id=tenant_id,
                submitter_email_normalized=submitter_email_normalized,
                free_audit_token=token,
            )
        )
        return token

    async def claim(self, token: str) -> bool:
        """Mark a free-audit token as claimed. Returns True if claim succeeded."""
        result = await self._fat_repo.mark_claimed(token)
        return result is not None
