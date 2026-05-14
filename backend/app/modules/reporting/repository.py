"""Repository layer for the Reporting module."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.modules.reporting.models import Report, ReportStatus, ShareLink


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ReportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        business_id: uuid.UUID,
        audit_run_id: uuid.UUID,
        web_view_token: str,
        version: int = 1,
        score: Optional[float] = None,
        confidence_band: Optional[str] = None,
        completeness_pct: Optional[float] = None,
        template_version: str = "v1",
    ) -> Report:
        report = Report(
            tenant_id=tenant_id,
            business_id=business_id,
            audit_run_id=audit_run_id,
            web_view_token=web_view_token,
            version=version,
            score=score,
            confidence_band=confidence_band,
            completeness_pct=completeness_pct,
            template_version=template_version,
            status=ReportStatus.generating,
        )
        self._session.add(report)
        await self._session.flush()
        return report

    async def get_by_id(self, report_id: uuid.UUID) -> Report:
        result = await self._session.execute(
            select(Report).where(Report.id == report_id)
        )
        report = result.scalar_one_or_none()
        if report is None:
            raise NotFoundError(f"Report {report_id} not found")
        return report

    async def get_by_web_view_token(self, token: str) -> Optional[Report]:
        result = await self._session.execute(
            select(Report).where(Report.web_view_token == token)
        )
        return result.scalar_one_or_none()

    async def get_by_audit_run(self, audit_run_id: uuid.UUID) -> Optional[Report]:
        result = await self._session.execute(
            select(Report)
            .where(Report.audit_run_id == audit_run_id)
            .order_by(Report.version.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_for_business(
        self,
        business_id: uuid.UUID,
        tenant_id: uuid.UUID,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> Sequence[Report]:
        result = await self._session.execute(
            select(Report)
            .where(Report.business_id == business_id, Report.tenant_id == tenant_id)
            .order_by(Report.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()

    async def mark_ready(
        self,
        report_id: uuid.UUID,
        *,
        quick_wins: Optional[dict] = None,
        pdf_gcs_uri: Optional[str] = None,
        pdf_byte_size: Optional[int] = None,
        pdf_checksum: Optional[str] = None,
        score: Optional[float] = None,
        confidence_band: Optional[str] = None,
        completeness_pct: Optional[float] = None,
    ) -> Report:
        report = await self.get_by_id(report_id)
        report.status = ReportStatus.ready
        report.generated_at = _utcnow()
        if quick_wins is not None:
            report.quick_wins = quick_wins
        if pdf_gcs_uri is not None:
            report.pdf_gcs_uri = pdf_gcs_uri
        if pdf_byte_size is not None:
            report.pdf_byte_size = pdf_byte_size
        if pdf_checksum is not None:
            report.pdf_checksum = pdf_checksum
        if score is not None:
            report.score = score
        if confidence_band is not None:
            report.confidence_band = confidence_band
        if completeness_pct is not None:
            report.completeness_pct = completeness_pct
        await self._session.flush()
        return report

    async def mark_failed(self, report_id: uuid.UUID) -> Report:
        report = await self.get_by_id(report_id)
        report.status = ReportStatus.failed
        await self._session.flush()
        return report


class ShareLinkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        business_id: uuid.UUID,
        report_id: uuid.UUID,
        token: str,
        expires_at: datetime,
        created_by_user_id: Optional[uuid.UUID] = None,
    ) -> ShareLink:
        link = ShareLink(
            tenant_id=tenant_id,
            business_id=business_id,
            report_id=report_id,
            token=token,
            expires_at=expires_at,
            created_by_user_id=created_by_user_id,
        )
        self._session.add(link)
        await self._session.flush()
        return link

    async def get_by_token(self, token: str) -> Optional[ShareLink]:
        result = await self._session.execute(
            select(ShareLink).where(
                ShareLink.token == token,
                ShareLink.revoked_at.is_(None),
                ShareLink.expires_at > _utcnow(),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, link_id: uuid.UUID) -> ShareLink:
        result = await self._session.execute(
            select(ShareLink).where(ShareLink.id == link_id)
        )
        link = result.scalar_one_or_none()
        if link is None:
            raise NotFoundError(f"ShareLink {link_id} not found")
        return link

    async def list_for_report(self, report_id: uuid.UUID) -> Sequence[ShareLink]:
        result = await self._session.execute(
            select(ShareLink)
            .where(ShareLink.report_id == report_id)
            .order_by(ShareLink.created_at.desc())
        )
        return result.scalars().all()

    async def get_by_token_unrestricted(self, token: str) -> Optional[ShareLink]:
        """Fetch share link by token without filtering by expiry or revocation status."""
        result = await self._session.execute(
            select(ShareLink).where(ShareLink.token == token)
        )
        return result.scalar_one_or_none()

    async def revoke(self, token: str) -> Optional[ShareLink]:
        link = await self.get_by_token_unrestricted(token)
        if link is None:
            return None
        link.revoked_at = _utcnow()
        await self._session.flush()
        return link

    async def increment_view(self, token: str) -> None:
        from sqlalchemy import update
        await self._session.execute(
            update(ShareLink)
            .where(ShareLink.token == token)
            .values(view_count=ShareLink.view_count + 1, last_viewed_at=_utcnow())
        )
        await self._session.flush()
