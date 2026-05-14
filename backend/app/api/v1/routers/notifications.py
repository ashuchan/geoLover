"""Notifications & Recrawl Schedule endpoints."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import TenantContext, get_session_factory, get_tenant_context
from app.core.database import get_db_session
from app.modules.identity.models import UserRole

router = APIRouter(tags=["notifications"])
_log = logging.getLogger(__name__)


# ── Schemas ────────────────────────────────────────────────────────────────────


class NotificationResponse(BaseModel):
    id: uuid.UUID
    notification_type: str
    priority: str
    channel: str
    status: str
    idempotency_key: str
    created_at: datetime

    model_config = {"from_attributes": True}


class PreferenceResponse(BaseModel):
    notification_type: str
    channels_enabled: list[str]
    cadence: str

    model_config = {"from_attributes": True}


class UpdatePreferenceRequest(BaseModel):
    channels_enabled: list[str]
    cadence: str


class ResendWebhookPayload(BaseModel):
    type: str
    data: dict


class RecrawlScheduleResponse(BaseModel):
    id: uuid.UUID
    business_id: uuid.UUID
    day_of_week: int
    hour_local: int
    enabled: bool
    next_run_at: Optional[datetime] = None
    last_run_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class CreateRecrawlScheduleRequest(BaseModel):
    business_id: uuid.UUID
    day_of_week: int = 0
    hour_local: int = 6


class UpdateRecrawlScheduleRequest(BaseModel):
    day_of_week: int
    hour_local: int
    enabled: bool


# ── Endpoints ──────────────────────────────────────────────────────────────────


@router.get("/notifications", response_model=list[NotificationResponse])
async def list_notifications(
    business_id: Optional[uuid.UUID] = None,
    limit: int = 50,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """List notifications for the current user."""
    ctx.assert_role(UserRole.agency_admin, UserRole.business_owner)
    tenant_id = ctx.assert_tenant()
    user_id = ctx.user_id

    from app.modules.notifications.repository import NotificationRepository

    factory = get_session_factory()
    async with get_db_session(factory, ctx.to_request_context()) as session:
        repo = NotificationRepository(session)
        notifications = await repo.list_for_user(tenant_id, user_id, limit=limit)
    return [
        NotificationResponse(
            id=n.id,
            notification_type=n.notification_type,
            priority=n.priority.value if hasattr(n.priority, "value") else n.priority,
            channel=n.channel,
            status=n.status.value if hasattr(n.status, "value") else n.status,
            idempotency_key=n.idempotency_key,
            created_at=n.created_at,
        )
        for n in notifications
    ]


@router.get("/notifications/preferences", response_model=list[PreferenceResponse])
async def list_preferences(
    ctx: TenantContext = Depends(get_tenant_context),
):
    """List notification preferences for the current user."""
    ctx.assert_role(UserRole.agency_admin, UserRole.business_owner)
    tenant_id = ctx.assert_tenant()
    user_id = ctx.user_id

    from app.modules.notifications.repository import NotificationPreferenceRepository

    factory = get_session_factory()
    async with get_db_session(factory, ctx.to_request_context()) as session:
        repo = NotificationPreferenceRepository(session)
        prefs = await repo.list_for_user(user_id, tenant_id)
    return [
        PreferenceResponse(
            notification_type=p.notification_type,
            channels_enabled=list(p.channels_enabled or []),
            cadence=p.cadence.value if hasattr(p.cadence, "value") else p.cadence,
        )
        for p in prefs
    ]


@router.put("/notifications/preferences/{notification_type}", response_model=PreferenceResponse)
async def update_preference(
    notification_type: str,
    body: UpdatePreferenceRequest,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Update notification preference for the current user."""
    ctx.assert_role(UserRole.agency_admin, UserRole.business_owner)
    tenant_id = ctx.assert_tenant()
    user_id = ctx.user_id

    from app.modules.notifications.service import NotificationService

    factory = get_session_factory()
    async with get_db_session(factory, ctx.to_request_context()) as session:
        svc = NotificationService(session)
        pref = await svc.update_preference(
            user_id=user_id,
            tenant_id=tenant_id,
            notification_type=notification_type,
            channels_enabled=body.channels_enabled,
            cadence=body.cadence,
        )
    return PreferenceResponse(
        notification_type=pref.notification_type,
        channels_enabled=list(pref.channels_enabled or []),
        cadence=pref.cadence.value if hasattr(pref.cadence, "value") else pref.cadence,
    )


@router.post("/notifications/webhooks/resend", status_code=200)
async def resend_webhook(
    payload: ResendWebhookPayload,
):
    """Webhook endpoint for Resend delivery events. No auth required."""
    _log.info("Resend webhook received: type=%s", payload.type)
    # Process webhook event (delivery confirmation, bounce, complaint, etc.)
    # In production this would update notification status via NotificationService
    return {"received": True, "type": payload.type}


@router.get("/recrawl/schedules", response_model=list[RecrawlScheduleResponse])
async def list_recrawl_schedules(
    business_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """List recrawl schedules for a business."""
    ctx.assert_role(UserRole.agency_admin, UserRole.business_owner)

    from app.modules.notifications.repository import RecrawlScheduleRepository

    factory = get_session_factory()
    async with get_db_session(factory, ctx.to_request_context()) as session:
        repo = RecrawlScheduleRepository(session)
        schedule = await repo.get_by_business(business_id)
    if schedule is None:
        return []
    return [
        RecrawlScheduleResponse(
            id=schedule.id,
            business_id=schedule.business_id,
            day_of_week=schedule.day_of_week,
            hour_local=schedule.hour_local,
            enabled=schedule.enabled,
            next_run_at=schedule.next_run_at,
            last_run_at=schedule.last_run_at,
        )
    ]


@router.post("/recrawl/schedules", response_model=RecrawlScheduleResponse, status_code=201)
async def create_recrawl_schedule(
    body: CreateRecrawlScheduleRequest,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Create a recrawl schedule for a business."""
    ctx.assert_role(UserRole.agency_admin, UserRole.business_owner)
    tenant_id = ctx.assert_tenant()

    from app.modules.notifications.service import RecrawlService

    factory = get_session_factory()
    async with get_db_session(factory, ctx.to_request_context()) as session:
        svc = RecrawlService(session)
        schedule = await svc.create_schedule(
            tenant_id=tenant_id,
            business_id=body.business_id,
            day_of_week=body.day_of_week,
            hour_local=body.hour_local,
        )
    return RecrawlScheduleResponse(
        id=schedule.id,
        business_id=schedule.business_id,
        day_of_week=schedule.day_of_week,
        hour_local=schedule.hour_local,
        enabled=schedule.enabled,
        next_run_at=schedule.next_run_at,
        last_run_at=schedule.last_run_at,
    )


@router.put("/recrawl/schedules/{schedule_id}", response_model=RecrawlScheduleResponse)
async def update_recrawl_schedule(
    schedule_id: uuid.UUID,
    body: UpdateRecrawlScheduleRequest,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Update a recrawl schedule."""
    ctx.assert_role(UserRole.agency_admin, UserRole.business_owner)
    tenant_id = ctx.assert_tenant()

    from app.modules.notifications.service import RecrawlService
    from app.modules.notifications.repository import RecrawlScheduleRepository

    factory = get_session_factory()
    async with get_db_session(factory, ctx.to_request_context()) as session:
        svc = RecrawlService(session)
        await svc.update_schedule(
            schedule_id=schedule_id,
            tenant_id=tenant_id,
            day_of_week=body.day_of_week,
            hour_local=body.hour_local,
            enabled=body.enabled,
        )
        repo = RecrawlScheduleRepository(session)
        schedule = await repo.get(schedule_id, tenant_id)

    if schedule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": "Recrawl schedule not found"},
        )
    return RecrawlScheduleResponse(
        id=schedule.id,
        business_id=schedule.business_id,
        day_of_week=schedule.day_of_week,
        hour_local=schedule.hour_local,
        enabled=schedule.enabled,
        next_run_at=schedule.next_run_at,
        last_run_at=schedule.last_run_at,
    )
