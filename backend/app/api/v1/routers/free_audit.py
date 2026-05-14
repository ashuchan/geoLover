"""Public free-audit endpoints.

These endpoints do not require authentication. They use the free-audit token
to identify the submitter and their trial tenant.
"""

from __future__ import annotations

import logging
import re
import unicodedata
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import get_session_factory
from app.core.database import RequestContext, get_db_session
from app.core.exceptions import CitedByError, ConflictError, NotFoundError
from app.modules.reporting.service import normalise_business_name

router = APIRouter(prefix="/free-audit", tags=["free-audit"])
_log = logging.getLogger(__name__)


# ── Schemas ───────────────────────────────────────────────────────────────────


class FreeAuditStartRequest(BaseModel):
    business_name: str
    city: str
    locality: str
    category: str
    email: str
    keywords: list[str] = []
    phone: Optional[str] = None
    website: Optional[str] = None

    from pydantic import field_validator

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, v: str) -> str:
        pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
        if not re.match(pattern, v.strip()):
            raise ValueError("Invalid email format")
        return v.strip()


class FreeAuditStartResponse(BaseModel):
    token: str
    status_url: str
    message: str


class FreeAuditStatusResponse(BaseModel):
    status: str
    progress: dict
    report_ready: bool
    claim_offered: bool


class FreeAuditClaimResponse(BaseModel):
    success: bool
    message: str


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/start", response_model=FreeAuditStartResponse, status_code=201)
async def start_free_audit(
    body: FreeAuditStartRequest,
):
    """Submit a free audit request.

    Creates a trial tenant + business, starts an AuditWorkflow,
    and returns a token for status polling.
    """
    from app.modules.audit.models import AuditTrigger
    from app.modules.audit.service import AuditService
    from app.modules.business_profile.models import BusinessSource, BusinessStatus
    from app.modules.business_profile.repository import (
        BusinessKeywordRepository,
        BusinessLocationRepository,
        BusinessRepository,
    )
    from app.modules.identity.models import TenantType
    from app.modules.identity.repository import TenantRepository
    from app.modules.reporting.service import FreeAuditSubmissionService

    slug = f"trial-{uuid.uuid4().hex[:8]}"
    factory = get_session_factory()
    # Public endpoint — use an anonymous request context with no tenant set
    ctx = RequestContext(tenant_id=None, user_id=None)

    audit_svc = None
    submission_svc = None

    try:
        async with get_db_session(factory, ctx) as session:
            tenant_repo = TenantRepository(session)
            trial_tenant = await tenant_repo.create(
                type=TenantType.trial,
                display_name=body.business_name,
                slug=slug,
            )

            # Use canonical normalisation (strips suffixes for dedup)
            name_norm = normalise_business_name(body.business_name)

            biz_repo = BusinessRepository(session)
            business = await biz_repo.create(
                tenant_id=trial_tenant.id,
                canonical_name=body.business_name,
                name_normalized=name_norm,
                category_id=uuid.UUID(int=0),
                source=BusinessSource.free_audit,
                website_url=body.website,
            )

            loc_repo = BusinessLocationRepository(session)
            await loc_repo.create(
                business_id=business.id,
                tenant_id=trial_tenant.id,
                city=body.city,
                locality=body.locality,
                is_primary=True,
            )

            if body.keywords:
                kw_repo = BusinessKeywordRepository(session)
                kw_pairs = [(kw, kw.lower().strip()) for kw in body.keywords[:10]]
                await kw_repo.create_batch(
                    business_id=business.id,
                    tenant_id=trial_tenant.id,
                    keywords=kw_pairs,
                )

            audit_svc = AuditService(session)
            run = await audit_svc.create_audit_run(
                business_id=business.id,
                tenant_id=trial_tenant.id,
                trigger=AuditTrigger.free_audit,
            )

            email_normalized = body.email.lower().strip()
            submission_svc = FreeAuditSubmissionService(session)
            token = await submission_svc.submit(
                tenant_id=trial_tenant.id,
                business_id=business.id,
                submitter_email_normalized=email_normalized,
                audit_run_id=run.id,
            )

    except CitedByError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.to_dict())

    # Flush events after DB commit, outside error-mapping block
    try:
        if audit_svc:
            await audit_svc.flush_events()
        if submission_svc:
            await submission_svc.flush_events()
    except Exception:
        _log.exception("Error flushing free audit events")

    return FreeAuditStartResponse(
        token=token,
        status_url=f"/api/v1/free-audit/{token}/status",
        message="Your audit has been submitted. Check back in a few minutes.",
    )


@router.get("/{token}/status", response_model=FreeAuditStatusResponse)
async def get_free_audit_status(token: str):
    """Poll the status of a free audit."""
    from app.modules.reporting.service import FreeAuditSubmissionService

    factory = get_session_factory()
    ctx = RequestContext(tenant_id=None, user_id=None)

    try:
        async with get_db_session(factory, ctx) as session:
            svc = FreeAuditSubmissionService(session)
            result = await svc.get_status(token)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.to_dict())
    except CitedByError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.to_dict())

    return result


@router.post("/{token}/claim", response_model=FreeAuditClaimResponse)
async def claim_free_audit(token: str):
    """Initiate the claim flow for a free audit token."""
    from app.modules.reporting.service import FreeAuditSubmissionService

    factory = get_session_factory()
    ctx = RequestContext(tenant_id=None, user_id=None)

    async with get_db_session(factory, ctx) as session:
        svc = FreeAuditSubmissionService(session)
        claimed = await svc.claim(token)

    if claimed:
        return FreeAuditClaimResponse(
            success=True,
            message="Claim initiated. Check your email for the magic link.",
        )
    return FreeAuditClaimResponse(
        success=False,
        message="Token not found, already claimed, or expired.",
    )
