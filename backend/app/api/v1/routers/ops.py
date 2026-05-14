"""Ops/Admin endpoints for Phase 8 (Hardening, Security Review, Launch)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.dependencies.auth import TenantContext, get_session_factory, get_tenant_context
from app.core.database import get_db_session

router = APIRouter(prefix="/ops", tags=["ops"])
_log = logging.getLogger(__name__)


# ── Schemas ────────────────────────────────────────────────────────────────────


class QuotaLogEntry(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    quota_kind: str
    action: str
    triggered_at: datetime

    model_config = {"from_attributes": True}


class ExtendGraceRequest(BaseModel):
    tenant_id: uuid.UUID
    quota_kind: str
    days: int
    reason: Optional[str] = None


class GraceExtensionResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    quota_kind: str
    extended_until: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class StartImpersonationRequest(BaseModel):
    impersonated_tenant_id: uuid.UUID
    reason: str


class ImpersonationLogResponse(BaseModel):
    id: uuid.UUID
    admin_user_id: uuid.UUID
    impersonated_tenant_id: uuid.UUID
    reason: str
    started_at: datetime
    ended_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class StatusComponentResponse(BaseModel):
    name: str
    description: Optional[str] = None
    last_known_state: str
    last_evaluated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class UpdateStateRequest(BaseModel):
    state: str


class PlanLimitsResponse(BaseModel):
    plan: str
    businesses: int
    audits_per_month: int
    content_briefs_per_month: int
    llm_spend_inr_per_month: int


# ── Quota endpoints ────────────────────────────────────────────────────────────


@router.get("/quota/log", response_model=list[QuotaLogEntry])
async def list_quota_log(
    tenant_id: Optional[uuid.UUID] = None,
    limit: int = 50,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """List recent quota enforcement log entries. Admin only."""
    if not ctx.is_platform_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "permission_denied", "message": "Admin access required"},
        )

    from app.modules.ops.repository import QuotaEnforcementLogRepository

    factory = get_session_factory()
    async with factory() as session:
        repo = QuotaEnforcementLogRepository(session)
        if tenant_id is not None:
            entries = await repo.list_for_tenant(tenant_id, limit=limit)
        else:
            entries = await repo.list_recent(limit=limit)
    return [QuotaLogEntry.model_validate(e) for e in entries]


@router.post("/quota/grace", response_model=GraceExtensionResponse, status_code=201)
async def extend_grace(
    body: ExtendGraceRequest,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Extend grace period for a tenant quota. Admin only."""
    if not ctx.is_platform_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "permission_denied", "message": "Admin access required"},
        )

    from app.modules.ops.service import QuotaService

    factory = get_session_factory()
    async with factory() as session:
        svc = QuotaService(session)
        grace = await svc.extend_grace(
            tenant_id=body.tenant_id,
            quota_kind=body.quota_kind,
            days=body.days,
            extended_by_user_id=ctx.user_id,
            reason=body.reason,
        )
        await session.commit()
    return GraceExtensionResponse.model_validate(grace)


@router.get("/quota/grace", response_model=list[GraceExtensionResponse])
async def list_grace_extensions(
    tenant_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """List grace extensions for a tenant. Admin only."""
    if not ctx.is_platform_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "permission_denied", "message": "Admin access required"},
        )

    from app.modules.ops.repository import TenantGraceExtensionRepository

    factory = get_session_factory()
    async with factory() as session:
        repo = TenantGraceExtensionRepository(session)
        extensions = await repo.list_for_tenant(tenant_id)
    return [GraceExtensionResponse.model_validate(e) for e in extensions]


# ── Impersonation endpoints ────────────────────────────────────────────────────


@router.post("/impersonation/start", response_model=ImpersonationLogResponse, status_code=201)
async def start_impersonation(
    body: StartImpersonationRequest,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Start an admin impersonation session. Platform admin only."""
    if not ctx.is_platform_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "permission_denied", "message": "Admin access required"},
        )

    from app.modules.ops.service import AdminOpsService

    factory = get_session_factory()
    async with factory() as session:
        svc = AdminOpsService(session)
        log = await svc.start_impersonation(
            admin_user_id=ctx.user_id,
            impersonated_tenant_id=body.impersonated_tenant_id,
            reason=body.reason,
        )
        await session.commit()
    return ImpersonationLogResponse.model_validate(log)


@router.post("/impersonation/{log_id}/end", status_code=204)
async def end_impersonation(
    log_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """End an admin impersonation session. Platform admin only."""
    if not ctx.is_platform_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "permission_denied", "message": "Admin access required"},
        )

    from app.modules.ops.service import AdminOpsService
    from app.core.exceptions import NotFoundError, PermissionDeniedError

    factory = get_session_factory()
    try:
        async with factory() as session:
            svc = AdminOpsService(session)
            await svc.end_impersonation(log_id=log_id, admin_user_id=ctx.user_id)
            await session.commit()
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": str(exc)},
        )
    except PermissionDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "permission_denied", "message": str(exc)},
        )


# ── Status page endpoints ──────────────────────────────────────────────────────


@router.get("/status", response_model=list[StatusComponentResponse])
async def get_all_component_states():
    """Get all component states. Public, no auth required."""
    from app.modules.ops.service import AdminOpsService
    from app.core.database import db_manager

    if db_manager._main_factory is None:
        raise HTTPException(status_code=503, detail="Database not initialised")

    factory = db_manager._main_factory
    async with factory() as session:
        svc = AdminOpsService(session)
        components = await svc.get_all_component_states()
    return [StatusComponentResponse.model_validate(c) for c in components]


@router.put("/status/{component_name}", response_model=StatusComponentResponse)
async def update_component_state(
    component_name: str,
    body: UpdateStateRequest,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Update the state of a status component. Admin only."""
    if not ctx.is_platform_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "permission_denied", "message": "Admin access required"},
        )

    from app.modules.ops.service import AdminOpsService

    factory = get_session_factory()
    async with factory() as session:
        svc = AdminOpsService(session)
        component = await svc.update_component_state(name=component_name, state=body.state)
        await session.commit()

    if component is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": f"Component '{component_name}' not found"},
        )
    return StatusComponentResponse.model_validate(component)


@router.post("/status/seed", response_model=list[StatusComponentResponse], status_code=201)
async def seed_default_components(
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Seed default status components. Admin only."""
    if not ctx.is_platform_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "permission_denied", "message": "Admin access required"},
        )

    from app.modules.ops.service import AdminOpsService

    factory = get_session_factory()
    async with factory() as session:
        svc = AdminOpsService(session)
        components = await svc.seed_default_components()
        await session.commit()
    return [StatusComponentResponse.model_validate(c) for c in components]


# ── Plans endpoint ─────────────────────────────────────────────────────────────


@router.get("/plans", response_model=list[PlanLimitsResponse])
async def list_plans():
    """List plan limits. Public, no auth required."""
    from app.modules.ops.enforcement import get_all_plans, get_limits

    plans = get_all_plans()
    result = []
    for plan in plans:
        limits = get_limits(plan)
        result.append(
            PlanLimitsResponse(
                plan=plan,
                businesses=limits.businesses,
                audits_per_month=limits.audits_per_month,
                content_briefs_per_month=limits.content_briefs_per_month,
                llm_spend_inr_per_month=limits.llm_spend_inr_per_month,
            )
        )
    return result
