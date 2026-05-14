"""Business profile CRUD endpoints."""

from __future__ import annotations

import uuid

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies.auth import TenantContext, get_master_key, get_session_factory, get_tenant_context
from app.api.v1.schemas import (
    AliasCreate,
    AliasResponse,
    BusinessCreate,
    BusinessResponse,
    BusinessUpdate,
    KeywordResponse,
    KeywordsAdd,
    LocationCreate,
    LocationResponse,
)
from app.core.database import get_db_session
from app.core.events import event_bus
from app.core.exceptions import CitedByError
from app.modules.business_profile.models import BusinessSource
from app.modules.business_profile.service import BusinessProfileService
from app.modules.identity.models import UserRole

router = APIRouter(prefix="/businesses", tags=["businesses"])
_log = logging.getLogger(__name__)


def _get_service(session, master_key: str) -> BusinessProfileService:
    return BusinessProfileService(session, master_key)


@router.post("", response_model=BusinessResponse, status_code=status.HTTP_201_CREATED)
async def create_business(
    body: BusinessCreate,
    ctx: TenantContext = Depends(get_tenant_context),
):
    tenant_id = ctx.assert_tenant()
    ctx.assert_role(UserRole.agency_admin, UserRole.business_owner)

    factory = get_session_factory()
    master_key = get_master_key()

    pending: list = []
    async with get_db_session(factory, ctx.to_request_context()) as session:
        svc = _get_service(session, master_key)
        try:
            business = await svc.create_business(
                actor_user_id=ctx.user_id,
                tenant_id=tenant_id,
                canonical_name=body.canonical_name,
                category_id=body.category_id,
                source=body.source,
                description=body.description,
                website_url=body.website_url,
                primary_email=body.primary_email,
                primary_phone=body.primary_phone,
                locale=body.locale,
                subcategory_ids=body.subcategory_ids,
            )
            pending = svc.pending_events
        except CitedByError as exc:
            raise HTTPException(status_code=exc.http_status, detail=exc.to_dict())

    try:
        for evt in pending:
            await event_bus.publish(evt)
    except Exception:
        _log.exception("Failed to publish events after create_business commit")
    return BusinessResponse.model_validate(business)


@router.get("", response_model=list[BusinessResponse])
async def list_businesses(
    ctx: TenantContext = Depends(get_tenant_context),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    tenant_id = ctx.assert_tenant()
    ctx.assert_role(UserRole.agency_admin, UserRole.business_owner)
    factory = get_session_factory()
    master_key = get_master_key()

    async with get_db_session(factory, ctx.to_request_context()) as session:
        svc = _get_service(session, master_key)
        businesses = await svc.list_businesses(tenant_id, limit=limit, offset=offset)
        return [BusinessResponse.model_validate(b) for b in businesses]


@router.get("/{business_id}", response_model=BusinessResponse)
async def get_business(
    business_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),
):
    tenant_id = ctx.assert_tenant()
    ctx.assert_role(UserRole.agency_admin, UserRole.business_owner, UserRole.business_member)
    factory = get_session_factory()
    master_key = get_master_key()

    async with get_db_session(factory, ctx.to_request_context()) as session:
        svc = _get_service(session, master_key)
        try:
            business = await svc.get_business(
                business_id, tenant_id=tenant_id, actor_user_id=ctx.user_id
            )
            return BusinessResponse.model_validate(business)
        except CitedByError as exc:
            raise HTTPException(status_code=exc.http_status, detail=exc.to_dict())


@router.patch("/{business_id}", response_model=BusinessResponse)
async def update_business(
    business_id: uuid.UUID,
    body: BusinessUpdate,
    ctx: TenantContext = Depends(get_tenant_context),
):
    tenant_id = ctx.assert_tenant()
    ctx.assert_role(UserRole.agency_admin, UserRole.business_owner)
    factory = get_session_factory()
    master_key = get_master_key()

    pending: list = []
    async with get_db_session(factory, ctx.to_request_context()) as session:
        svc = _get_service(session, master_key)
        try:
            business = await svc.update_business(
                actor_user_id=ctx.user_id,
                business_id=business_id,
                tenant_id=tenant_id,
                canonical_name=body.canonical_name,
                description=body.description,
                website_url=body.website_url,
                primary_email=body.primary_email,
                primary_phone=body.primary_phone,
                status=body.status,
            )
            pending = svc.pending_events
        except CitedByError as exc:
            raise HTTPException(status_code=exc.http_status, detail=exc.to_dict())

    try:
        for evt in pending:
            await event_bus.publish(evt)
    except Exception:
        _log.exception("Failed to publish events after update_business commit")
    return BusinessResponse.model_validate(business)


@router.delete("/{business_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_business(
    business_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),
):
    tenant_id = ctx.assert_tenant()
    ctx.assert_role(UserRole.agency_admin, UserRole.business_owner)
    factory = get_session_factory()
    master_key = get_master_key()

    pending: list = []
    async with get_db_session(factory, ctx.to_request_context()) as session:
        svc = _get_service(session, master_key)
        try:
            await svc.delete_business(
                actor_user_id=ctx.user_id,
                business_id=business_id,
                tenant_id=tenant_id,
            )
            pending = svc.pending_events
        except CitedByError as exc:
            raise HTTPException(status_code=exc.http_status, detail=exc.to_dict())

    try:
        for evt in pending:
            await event_bus.publish(evt)
    except Exception:
        _log.exception("Failed to publish events after delete_business commit")


@router.post("/{business_id}/aliases", response_model=AliasResponse, status_code=status.HTTP_201_CREATED)
async def add_alias(
    business_id: uuid.UUID,
    body: AliasCreate,
    ctx: TenantContext = Depends(get_tenant_context),
):
    tenant_id = ctx.assert_tenant()
    ctx.assert_role(UserRole.agency_admin, UserRole.business_owner, UserRole.business_member)
    factory = get_session_factory()
    master_key = get_master_key()

    pending: list = []
    async with get_db_session(factory, ctx.to_request_context()) as session:
        svc = _get_service(session, master_key)
        try:
            alias = await svc.add_alias(
                actor_user_id=ctx.user_id,
                business_id=business_id,
                tenant_id=tenant_id,
                alias_text=body.alias_text,
                alias_type=body.alias_type,
                confidence=body.confidence,
            )
            pending = svc.pending_events
        except CitedByError as exc:
            raise HTTPException(status_code=exc.http_status, detail=exc.to_dict())

    try:
        for evt in pending:
            await event_bus.publish(evt)
    except Exception:
        _log.exception("Failed to publish events after add_alias commit")
    return AliasResponse.model_validate(alias)


@router.post("/{business_id}/locations", response_model=LocationResponse, status_code=status.HTTP_201_CREATED)
async def add_location(
    business_id: uuid.UUID,
    body: LocationCreate,
    ctx: TenantContext = Depends(get_tenant_context),
):
    tenant_id = ctx.assert_tenant()
    ctx.assert_role(UserRole.agency_admin, UserRole.business_owner, UserRole.business_member)
    factory = get_session_factory()
    master_key = get_master_key()

    pending: list = []
    async with get_db_session(factory, ctx.to_request_context()) as session:
        svc = _get_service(session, master_key)
        try:
            location = await svc.add_location(
                actor_user_id=ctx.user_id,
                business_id=business_id,
                tenant_id=tenant_id,
                city=body.city,
                is_primary=body.is_primary,
                label=body.label,
                locality=body.locality,
                address_line_1=body.address_line_1,
                address_line_2=body.address_line_2,
                postal_code=body.postal_code,
                state=body.state,
                country=body.country,
            )
            pending = svc.pending_events
        except CitedByError as exc:
            raise HTTPException(status_code=exc.http_status, detail=exc.to_dict())

    try:
        for evt in pending:
            await event_bus.publish(evt)
    except Exception:
        _log.exception("Failed to publish events after add_location commit")
    return LocationResponse.model_validate(location)


@router.post("/{business_id}/keywords", response_model=list[KeywordResponse], status_code=status.HTTP_201_CREATED)
async def add_keywords(
    business_id: uuid.UUID,
    body: KeywordsAdd,
    ctx: TenantContext = Depends(get_tenant_context),
):
    tenant_id = ctx.assert_tenant()
    ctx.assert_role(UserRole.agency_admin, UserRole.business_owner, UserRole.business_member)
    factory = get_session_factory()
    master_key = get_master_key()

    pending: list = []
    async with get_db_session(factory, ctx.to_request_context()) as session:
        svc = _get_service(session, master_key)
        try:
            keywords = await svc.add_keywords(
                actor_user_id=ctx.user_id,
                business_id=business_id,
                tenant_id=tenant_id,
                keywords=body.keywords,
            )
            pending = svc.pending_events
        except CitedByError as exc:
            raise HTTPException(status_code=exc.http_status, detail=exc.to_dict())

    try:
        for evt in pending:
            await event_bus.publish(evt)
    except Exception:
        _log.exception("Failed to publish events after add_keywords commit")
    return [KeywordResponse.model_validate(k) for k in keywords]
