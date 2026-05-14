"""Publishing & Entity Seeding endpoints."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.dependencies.auth import TenantContext, get_session_factory, get_tenant_context
from app.core.database import get_db_session
from app.modules.identity.models import UserRole

router = APIRouter(prefix="/publishing", tags=["publishing"])
_log = logging.getLogger(__name__)


# ── Schemas ────────────────────────────────────────────────────────────────────


class PublishTargetResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    business_id: uuid.UUID
    channel: str
    status: str
    connected_account_label: Optional[str] = None
    external_identifier: Optional[str] = None
    publish_authorized_at: Optional[Any] = None
    revoked_at: Optional[Any] = None
    last_publish_at: Optional[Any] = None
    meta: dict = {}
    created_at: Any
    updated_at: Any

    @classmethod
    def from_model(cls, t) -> "PublishTargetResponse":
        return cls(
            id=t.id,
            tenant_id=t.tenant_id,
            business_id=t.business_id,
            channel=t.channel.value if hasattr(t.channel, "value") else t.channel,
            status=t.status.value if hasattr(t.status, "value") else t.status,
            connected_account_label=t.connected_account_label,
            external_identifier=t.external_identifier,
            publish_authorized_at=t.publish_authorized_at,
            revoked_at=t.revoked_at,
            last_publish_at=t.last_publish_at,
            meta=t.meta or {},
            created_at=t.created_at,
            updated_at=t.updated_at,
        )

    model_config = {"from_attributes": True}


class CreatePublishTargetRequest(BaseModel):
    business_id: uuid.UUID
    channel: str
    redirect_uri: str = ""
    connected_account_label: Optional[str] = None
    external_identifier: Optional[str] = None
    meta: Optional[dict] = None


class EntitySeedResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    business_id: uuid.UUID
    directory_id: uuid.UUID
    status: str
    external_listing_id: Optional[str] = None
    external_listing_url: Optional[str] = None
    submitted_at: Optional[Any] = None
    first_verified_at: Optional[Any] = None
    last_verified_at: Optional[Any] = None
    created_at: Any
    updated_at: Any

    @classmethod
    def from_model(cls, s) -> "EntitySeedResponse":
        return cls(
            id=s.id,
            tenant_id=s.tenant_id,
            business_id=s.business_id,
            directory_id=s.directory_id,
            status=s.status.value if hasattr(s.status, "value") else s.status,
            external_listing_id=s.external_listing_id,
            external_listing_url=s.external_listing_url,
            submitted_at=s.submitted_at,
            first_verified_at=s.first_verified_at,
            last_verified_at=s.last_verified_at,
            created_at=s.created_at,
            updated_at=s.updated_at,
        )

    model_config = {"from_attributes": True}


# ── Endpoints ──────────────────────────────────────────────────────────────────


@router.get("/targets", response_model=list[PublishTargetResponse])
async def list_targets(
    business_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """List publish targets for a business."""
    ctx.assert_role(UserRole.agency_admin, UserRole.business_owner)
    tenant_id = ctx.assert_tenant()

    from app.modules.publishing.repository import PublishTargetRepository

    factory = get_session_factory()
    async with get_db_session(factory, ctx.to_request_context()) as session:
        repo = PublishTargetRepository(session)
        targets = await repo.list_for_business(tenant_id, business_id)
    return [PublishTargetResponse.from_model(t) for t in targets]


@router.get("/targets/{target_id}", response_model=PublishTargetResponse)
async def get_target(
    target_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Get a specific publish target."""
    ctx.assert_role(UserRole.agency_admin, UserRole.business_owner)
    tenant_id = ctx.assert_tenant()

    from app.modules.publishing.repository import PublishTargetRepository

    factory = get_session_factory()
    async with get_db_session(factory, ctx.to_request_context()) as session:
        repo = PublishTargetRepository(session)
        target = await repo.get(target_id, tenant_id)

    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": "Publish target not found"},
        )
    return PublishTargetResponse.from_model(target)


@router.post("/targets", response_model=PublishTargetResponse, status_code=201)
async def create_target(
    body: CreatePublishTargetRequest,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Create a new publish target."""
    ctx.assert_role(UserRole.agency_admin, UserRole.business_owner)
    tenant_id = ctx.assert_tenant()

    from app.modules.publishing.service import PublishService

    factory = get_session_factory()
    async with get_db_session(factory, ctx.to_request_context()) as session:
        svc = PublishService(session)
        target = await svc.connect_target(
            tenant_id=tenant_id,
            business_id=body.business_id,
            channel=body.channel,
            redirect_uri=body.redirect_uri,
            connected_account_label=body.connected_account_label or "",
            external_identifier=body.external_identifier or "",
            meta=body.meta,
        )
    return PublishTargetResponse.from_model(target)


@router.post("/targets/{target_id}/authorize", response_model=PublishTargetResponse)
async def authorize_target(
    target_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Authorize publishing for a target."""
    ctx.assert_role(UserRole.agency_admin, UserRole.business_owner)
    tenant_id = ctx.assert_tenant()

    from app.modules.publishing.service import PublishService

    factory = get_session_factory()
    async with get_db_session(factory, ctx.to_request_context()) as session:
        svc = PublishService(session)
        target = await svc.authorize_publish(
            target_id=target_id,
            tenant_id=tenant_id,
        )

    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": "Publish target not found"},
        )
    return PublishTargetResponse.from_model(target)


@router.post("/targets/{target_id}/revoke", status_code=204)
async def revoke_target(
    target_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Revoke a publish target."""
    ctx.assert_role(UserRole.agency_admin, UserRole.business_owner)
    tenant_id = ctx.assert_tenant()

    from app.modules.publishing.service import PublishService

    factory = get_session_factory()
    async with get_db_session(factory, ctx.to_request_context()) as session:
        svc = PublishService(session)
        await svc.revoke_target(
            target_id=target_id,
            tenant_id=tenant_id,
        )


@router.get("/seeds", response_model=list[EntitySeedResponse])
async def list_seeds(
    business_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """List entity seeds for a business."""
    ctx.assert_role(UserRole.agency_admin, UserRole.business_owner)
    tenant_id = ctx.assert_tenant()

    from app.modules.publishing.repository import EntitySeedRepository

    factory = get_session_factory()
    async with get_db_session(factory, ctx.to_request_context()) as session:
        repo = EntitySeedRepository(session)
        seeds = await repo.list_for_business(tenant_id, business_id)
    return [EntitySeedResponse.from_model(s) for s in seeds]
