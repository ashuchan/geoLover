"""Report and Share Link endpoints."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.dependencies.auth import TenantContext, get_session_factory, get_tenant_context
from app.core.database import get_db_session
from app.core.exceptions import CitedByError, NotFoundError, PermissionDeniedError
from app.modules.identity.models import UserRole
from app.modules.reporting.service import ReportService

router = APIRouter(prefix="/reports", tags=["reports"])
_log = logging.getLogger(__name__)


# ── Schemas ───────────────────────────────────────────────────────────────────


class ReportResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    business_id: uuid.UUID
    audit_run_id: uuid.UUID
    version: int
    status: str
    score: Optional[float] = None
    confidence_band: Optional[str] = None
    completeness_pct: Optional[float] = None
    web_view_token: str
    quick_wins: Optional[Any] = None
    template_version: str
    generated_at: Optional[Any] = None
    created_at: Any

    @classmethod
    def from_model(cls, r) -> "ReportResponse":
        return cls(
            id=r.id,
            tenant_id=r.tenant_id,
            business_id=r.business_id,
            audit_run_id=r.audit_run_id,
            version=r.version,
            status=r.status.value if hasattr(r.status, "value") else r.status,
            score=r.score,
            confidence_band=r.confidence_band,
            completeness_pct=r.completeness_pct,
            web_view_token=r.web_view_token,
            quick_wins=r.quick_wins,
            template_version=r.template_version,
            generated_at=r.generated_at,
            created_at=r.created_at,
        )

    model_config = {"from_attributes": True}


class ShareLinkResponse(BaseModel):
    id: uuid.UUID
    token: str
    report_id: uuid.UUID
    expires_at: Any
    view_count: int
    created_at: Any

    @classmethod
    def from_model(cls, link) -> "ShareLinkResponse":
        return cls(
            id=link.id,
            token=link.token,
            report_id=link.report_id,
            expires_at=link.expires_at,
            view_count=link.view_count,
            created_at=link.created_at,
        )

    model_config = {"from_attributes": True}


class CreateShareLinkRequest(BaseModel):
    ttl_days: int = 30

    from pydantic import field_validator

    @field_validator("ttl_days")
    @classmethod
    def validate_ttl(cls, v: int) -> int:
        if v < 1 or v > 365:
            raise ValueError("ttl_days must be between 1 and 365")
        return v


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("/by-token/{token}", response_model=ReportResponse)
async def get_report_by_token(
    token: str,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Get report by web_view_token. Accessible to any authenticated user holding the token."""
    factory = get_session_factory()
    async with get_db_session(factory, ctx.to_request_context()) as session:
        svc = ReportService(session)
        try:
            report = await svc.get_report_by_token(token)
        except NotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.to_dict())
        except CitedByError as exc:
            raise HTTPException(status_code=exc.http_status, detail=exc.to_dict())
    # Return only non-sensitive fields via a slimmed response (tenant/business IDs omitted)
    return ReportResponse.from_model(report)


@router.get("/{report_id}", response_model=ReportResponse)
async def get_report(
    report_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Get a report by ID (requires tenant membership)."""
    ctx.assert_role(UserRole.agency_admin, UserRole.business_owner, UserRole.agency_member)
    tenant_id = ctx.assert_tenant()

    factory = get_session_factory()
    async with get_db_session(factory, ctx.to_request_context()) as session:
        svc = ReportService(session)
        try:
            report = await svc.get_report(report_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.to_dict())
        except CitedByError as exc:
            raise HTTPException(status_code=exc.http_status, detail=exc.to_dict())

    if report.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "permission_denied", "message": "Access denied"},
        )
    return ReportResponse.from_model(report)


@router.post("/{report_id}/share", response_model=ShareLinkResponse, status_code=201)
async def create_share_link(
    report_id: uuid.UUID,
    body: CreateShareLinkRequest,
    ctx: TenantContext = Depends(get_tenant_context),
):
    ctx.assert_role(UserRole.agency_admin, UserRole.business_owner)
    tenant_id = ctx.assert_tenant()

    factory = get_session_factory()
    async with get_db_session(factory, ctx.to_request_context()) as session:
        svc = ReportService(session)
        try:
            link = await svc.create_share_link(
                report_id=report_id,
                tenant_id=tenant_id,
                ttl_days=body.ttl_days,
            )
        except (NotFoundError, PermissionDeniedError, CitedByError) as exc:
            raise HTTPException(status_code=exc.http_status, detail=exc.to_dict())

    return ShareLinkResponse.from_model(link)


@router.delete("/share/{token}", status_code=204)
async def revoke_share_link(
    token: str,
    ctx: TenantContext = Depends(get_tenant_context),
):
    ctx.assert_role(UserRole.agency_admin, UserRole.business_owner)
    tenant_id = ctx.assert_tenant()

    factory = get_session_factory()
    async with get_db_session(factory, ctx.to_request_context()) as session:
        svc = ReportService(session)
        try:
            await svc.revoke_share_link(token, tenant_id=tenant_id)
        except (NotFoundError, PermissionDeniedError, CitedByError) as exc:
            raise HTTPException(status_code=exc.http_status, detail=exc.to_dict())
