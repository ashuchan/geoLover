"""Tenant management endpoints."""

from __future__ import annotations

import uuid

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies.auth import TenantContext, get_master_key, get_session_factory, get_tenant_context
from app.api.v1.schemas import (
    MemberInvite,
    MemberRevokeResponse,
    MembershipResponse,
    TenantCreate,
    TenantResponse,
    TenantUpdate,
)
from app.core.database import RequestContext, get_db_session
from app.core.exceptions import CitedByError, ConflictError
from app.modules.identity.models import UserRole
from app.modules.identity.service import MembershipService, TenantService

router = APIRouter(prefix="/tenants", tags=["tenants"])
_log = logging.getLogger(__name__)


@router.post("", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    body: TenantCreate,
    ctx: TenantContext = Depends(get_tenant_context),
):
    factory = get_session_factory()
    master_key = get_master_key()

    # Tenant creation has no prior tenant_id for RLS; a plain session is intentional here.
    # Events are flushed after commit to ensure consumers see committed data.
    async with factory() as session:
        svc = TenantService(session, master_key)
        try:
            tenant = await svc.create_tenant(
                actor_user_id=ctx.user_id,
                tenant_type=body.type,
                display_name=body.display_name,
                slug=body.slug,
                primary_country=body.primary_country,
            )
            await session.commit()
        except ConflictError as exc:
            # Rollback the failed transaction before querying for alternatives
            await session.rollback()
            alternatives = await svc.suggest_slug_alternatives(body.slug)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": exc.error_code,
                    "message": exc.message,
                    "slug_alternatives": alternatives,
                },
            )
        except CitedByError as exc:
            raise HTTPException(status_code=exc.http_status, detail=exc.to_dict())

    try:
        await svc.flush_pending_events()
    except Exception:
        _log.exception("Failed to publish events after create_tenant commit")
    return TenantResponse.model_validate(tenant)


@router.get("/current", response_model=TenantResponse)
async def get_current_tenant(
    ctx: TenantContext = Depends(get_tenant_context),
):
    tenant_id = ctx.assert_tenant()
    ctx.assert_role(
        UserRole.agency_admin,
        UserRole.agency_member,
        UserRole.business_owner,
        UserRole.business_member,
    )
    factory = get_session_factory()
    master_key = get_master_key()

    async with factory() as session:
        svc = TenantService(session, master_key)
        try:
            tenant = await svc.get_tenant(tenant_id)
            return TenantResponse.model_validate(tenant)
        except CitedByError as exc:
            raise HTTPException(status_code=exc.http_status, detail=exc.to_dict())


@router.patch("/current", response_model=TenantResponse)
async def update_current_tenant(
    body: TenantUpdate,
    ctx: TenantContext = Depends(get_tenant_context),
):
    tenant_id = ctx.assert_tenant()
    ctx.assert_role(UserRole.agency_admin, UserRole.business_owner)

    factory = get_session_factory()
    master_key = get_master_key()

    async with factory() as session:
        svc = TenantService(session, master_key)
        try:
            tenant = await svc.update_tenant(
                actor_user_id=ctx.user_id,
                tenant_id=tenant_id,
                display_name=body.display_name,
                primary_country=body.primary_country,
            )
            await session.commit()
            return TenantResponse.model_validate(tenant)
        except CitedByError as exc:
            raise HTTPException(status_code=exc.http_status, detail=exc.to_dict())


@router.get("/current/members", response_model=list[MembershipResponse])
async def list_members(
    ctx: TenantContext = Depends(get_tenant_context),
):
    tenant_id = ctx.assert_tenant()
    ctx.assert_role(UserRole.agency_admin, UserRole.business_owner)

    factory = get_session_factory()
    async with factory() as session:
        svc = MembershipService(session)
        members = await svc.list_tenant_members(tenant_id)
        return [MembershipResponse.model_validate(m) for m in members]


@router.delete(
    "/current/members/{membership_id}",
    response_model=MemberRevokeResponse,
)
async def revoke_member(
    membership_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),
):
    tenant_id = ctx.assert_tenant()
    ctx.assert_role(UserRole.agency_admin)

    factory = get_session_factory()
    async with factory() as session:
        svc = MembershipService(session)
        try:
            membership = await svc.revoke(
                actor_user_id=ctx.user_id,
                membership_id=membership_id,
                tenant_id=tenant_id,
            )
            await session.commit()
            return MemberRevokeResponse(membership_id=membership.id)
        except CitedByError as exc:
            raise HTTPException(status_code=exc.http_status, detail=exc.to_dict())
