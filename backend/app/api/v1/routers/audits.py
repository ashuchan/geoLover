"""Audit run API endpoints.

All endpoints require authentication and appropriate tenant context.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.api.dependencies.auth import TenantContext, get_session_factory, get_tenant_context
from app.core.database import get_db_session
from app.core.events import event_bus
from app.core.exceptions import BusinessNotFoundError, CitedByError, NotFoundError
from app.modules.audit.models import AuditTrigger
from app.modules.audit.service import AuditService
from app.modules.identity.models import UserRole

router = APIRouter(prefix="/audits", tags=["audits"])
_log = logging.getLogger(__name__)


# ── Request / Response schemas ─────────────────────────────────────────────────


class AuditRunCreateRequest(BaseModel):
    business_id: uuid.UUID
    trigger: str = "manual"


class AuditRunResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    business_id: uuid.UUID
    trigger: str
    status: str
    ai_visibility_score: Optional[float] = None
    completeness_pct: Optional[float] = None
    queries_total: int = 0
    queries_successful: int = 0
    queries_cited: int = 0
    queries_negative: int = 0
    algorithm_version: str
    workflow_run_id: Optional[str] = None
    created_at: str

    @classmethod
    def from_model(cls, run) -> "AuditRunResponse":
        return cls(
            id=run.id,
            tenant_id=run.tenant_id,
            business_id=run.business_id,
            trigger=run.trigger.value if hasattr(run.trigger, "value") else str(run.trigger),
            status=run.status.value if hasattr(run.status, "value") else str(run.status),
            ai_visibility_score=run.ai_visibility_score,
            completeness_pct=run.completeness_pct,
            queries_total=run.queries_total,
            queries_successful=run.queries_successful,
            queries_cited=getattr(run, "queries_cited", 0),
            queries_negative=getattr(run, "queries_negative", 0),
            algorithm_version=run.algorithm_version,
            workflow_run_id=run.workflow_run_id,
            created_at=run.created_at.isoformat(),
        )


class AuditRunListResponse(BaseModel):
    items: list[AuditRunResponse]
    total: int


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("", response_model=AuditRunResponse, status_code=status.HTTP_201_CREATED)
async def create_audit_run(
    body: AuditRunCreateRequest,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Trigger a new audit run for a business."""
    ctx.assert_role(UserRole.agency_admin, UserRole.business_owner)
    tenant_id = ctx.assert_tenant()

    # Validate trigger
    try:
        trigger = AuditTrigger(body.trigger)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid trigger: {body.trigger}. Valid values: {[t.value for t in AuditTrigger]}",
        )

    factory = get_session_factory()
    pending: list = []

    async with get_db_session(factory, ctx.to_request_context()) as session:
        svc = AuditService(session)
        try:
            run = await svc.create_audit_run(
                business_id=body.business_id,
                tenant_id=tenant_id,
                trigger=trigger,
            )
            pending = svc.pending_events
        except BusinessNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.to_dict())
        except CitedByError as exc:
            raise HTTPException(status_code=exc.http_status, detail=exc.to_dict())

    for evt in pending:
        try:
            await event_bus.publish(evt)
        except Exception:
            _log.exception("Error flushing audit events")

    return AuditRunResponse.from_model(run)


@router.get("", response_model=AuditRunListResponse)
async def list_audit_runs(
    business_id: Optional[uuid.UUID] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    ctx: TenantContext = Depends(get_tenant_context),
):
    """List audit runs for the current tenant."""
    ctx.assert_role(UserRole.agency_admin, UserRole.business_owner)
    tenant_id = ctx.assert_tenant()

    factory = get_session_factory()

    async with get_db_session(factory, ctx.to_request_context()) as session:
        svc = AuditService(session)
        runs = await svc.list_audit_runs(
            tenant_id,
            business_id=business_id,
            limit=limit,
            offset=offset,
        )

    return AuditRunListResponse(
        items=[AuditRunResponse.from_model(r) for r in runs],
        total=len(runs),
    )


@router.get("/{audit_run_id}", response_model=AuditRunResponse)
async def get_audit_run(
    audit_run_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Get a specific audit run by ID."""
    ctx.assert_role(UserRole.agency_admin, UserRole.business_owner)
    tenant_id = ctx.assert_tenant()

    factory = get_session_factory()

    async with get_db_session(factory, ctx.to_request_context()) as session:
        svc = AuditService(session)
        try:
            run = await svc.get_audit_run(audit_run_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.to_dict())

    # Verify tenant ownership
    if run.tenant_id != tenant_id and not ctx.is_platform_admin:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit run not found")

    return AuditRunResponse.from_model(run)
