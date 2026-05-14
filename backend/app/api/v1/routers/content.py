"""Content brief endpoints."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.dependencies.auth import TenantContext, get_session_factory, get_tenant_context
from app.core.database import get_db_session
from app.core.exceptions import CitedByError, ConflictError, NotFoundError, PermissionDeniedError
from app.modules.identity.models import UserRole

router = APIRouter(prefix="/content", tags=["content"])
_log = logging.getLogger(__name__)


# ── Schemas ────────────────────────────────────────────────────────────────────


class ContentBriefResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    business_id: uuid.UUID
    source_audit_run_id: uuid.UUID
    brief_type: str
    target_query: str
    current_state: str
    current_asset_id: Optional[uuid.UUID] = None
    approval_flow: str
    created_at: Any
    updated_at: Any

    @classmethod
    def from_model(cls, b) -> "ContentBriefResponse":
        return cls(
            id=b.id,
            tenant_id=b.tenant_id,
            business_id=b.business_id,
            source_audit_run_id=b.source_audit_run_id,
            brief_type=b.brief_type.value if hasattr(b.brief_type, "value") else b.brief_type,
            target_query=b.target_query,
            current_state=b.current_state.value if hasattr(b.current_state, "value") else b.current_state,
            current_asset_id=b.current_asset_id,
            approval_flow=b.approval_flow.value if hasattr(b.approval_flow, "value") else b.approval_flow,
            created_at=b.created_at,
            updated_at=b.updated_at,
        )

    model_config = {"from_attributes": True}


class ApproveRejectRequest(BaseModel):
    reviewer_notes: Optional[str] = None


# ── Endpoints ──────────────────────────────────────────────────────────────────


@router.get("/briefs", response_model=list[ContentBriefResponse])
async def list_briefs(
    business_id: uuid.UUID,
    state: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """List content briefs for a business."""
    ctx.assert_role(UserRole.agency_admin, UserRole.business_owner, UserRole.agency_member)
    tenant_id = ctx.assert_tenant()

    from app.modules.content.models import BriefState
    from app.modules.content.service import ContentBriefService

    state_filter = None
    if state is not None:
        try:
            state_filter = BriefState(state)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error": "invalid_state", "message": f"Unknown brief state '{state}'"},
            )

    factory = get_session_factory()
    async with get_db_session(factory, ctx.to_request_context()) as session:
        svc = ContentBriefService(session)
        briefs = await svc.list_briefs(
            business_id, tenant_id, state=state_filter, limit=limit, offset=offset
        )
    return [ContentBriefResponse.from_model(b) for b in briefs]


@router.get("/briefs/{brief_id}", response_model=ContentBriefResponse)
async def get_brief(
    brief_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Get a content brief by ID."""
    ctx.assert_role(UserRole.agency_admin, UserRole.business_owner, UserRole.agency_member)
    tenant_id = ctx.assert_tenant()

    from app.modules.content.service import ContentBriefService

    factory = get_session_factory()
    async with get_db_session(factory, ctx.to_request_context()) as session:
        svc = ContentBriefService(session)
        try:
            brief = await svc.get_brief(brief_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.to_dict())

    if brief.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "permission_denied", "message": "Access denied"},
        )
    return ContentBriefResponse.from_model(brief)


@router.post("/briefs/{brief_id}/approve", response_model=ContentBriefResponse)
async def approve_brief(
    brief_id: uuid.UUID,
    body: ApproveRejectRequest,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Approve a content brief."""
    ctx.assert_role(UserRole.agency_admin, UserRole.business_owner)
    tenant_id = ctx.assert_tenant()
    user_id = ctx.user_id or uuid.UUID(int=0)

    from app.modules.content.service import ContentBriefService

    factory = get_session_factory()
    async with get_db_session(factory, ctx.to_request_context()) as session:
        svc = ContentBriefService(session)
        try:
            brief = await svc.approve_brief(
                brief_id, tenant_id=tenant_id, reviewer_user_id=user_id
            )
        except NotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.to_dict())
        except (ConflictError, PermissionDeniedError, CitedByError) as exc:
            raise HTTPException(status_code=exc.http_status, detail=exc.to_dict())

    try:
        await svc.flush_events()
    except Exception:
        _log.exception("Error flushing content brief events")

    return ContentBriefResponse.from_model(brief)


@router.post("/briefs/{brief_id}/reject", response_model=ContentBriefResponse)
async def reject_brief(
    brief_id: uuid.UUID,
    body: ApproveRejectRequest,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Reject a content brief with reviewer notes."""
    ctx.assert_role(UserRole.agency_admin, UserRole.business_owner)
    tenant_id = ctx.assert_tenant()
    user_id = ctx.user_id or uuid.UUID(int=0)

    from app.modules.content.service import ContentBriefService

    factory = get_session_factory()
    async with get_db_session(factory, ctx.to_request_context()) as session:
        svc = ContentBriefService(session)
        try:
            brief = await svc.reject_brief(
                brief_id,
                tenant_id=tenant_id,
                reviewer_user_id=user_id,
                reviewer_notes=body.reviewer_notes or "",
            )
        except NotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.to_dict())
        except (ConflictError, PermissionDeniedError, CitedByError) as exc:
            raise HTTPException(status_code=exc.http_status, detail=exc.to_dict())

    return ContentBriefResponse.from_model(brief)
