"""Agency & Whitelabel Portal endpoints."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.dependencies.auth import TenantContext, get_session_factory, get_tenant_context
from app.core.database import get_db_session
from app.modules.identity.models import UserRole

router = APIRouter(prefix="/agency", tags=["agency"])
_log = logging.getLogger(__name__)


# ── Pydantic Schemas ───────────────────────────────────────────────────────────


class WhitelabelConfigResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    product_display_name: Optional[str] = None
    primary_color_hex: str
    secondary_color_hex: str
    font_family: str
    content_approval_flow: str

    model_config = {"from_attributes": True}


class UpdateConfigRequest(BaseModel):
    product_display_name: Optional[str] = None
    tagline: Optional[str] = None
    primary_color_hex: Optional[str] = None
    secondary_color_hex: Optional[str] = None
    font_family: Optional[str] = None
    support_email: Optional[str] = None
    pdf_footer_text: Optional[str] = None
    content_approval_flow: Optional[str] = None


class DomainMappingResponse(BaseModel):
    id: uuid.UUID
    domain: str
    domain_type: str
    verification_status: str
    ssl_cert_status: str

    model_config = {"from_attributes": True}


class AddDomainRequest(BaseModel):
    domain: str
    domain_type: str = "custom"
    verification_method: str = "dns_txt"


class ThemeAssetResponse(BaseModel):
    id: uuid.UUID
    asset_kind: str
    content_type: str
    gcs_object_path: str

    model_config = {"from_attributes": True}


class RegisterAssetRequest(BaseModel):
    asset_kind: str
    content_type: str
    gcs_object_path: str
    width_px: Optional[int] = None
    height_px: Optional[int] = None
    safe_for_email: bool = False


class BulkImportRequest(BaseModel):
    source_object_path: str
    rows: list[dict] = []


class BulkImportResponse(BaseModel):
    id: uuid.UUID
    status: str
    total_rows: Optional[int] = None
    succeeded_rows: Optional[int] = None
    failed_rows: Optional[int] = None

    model_config = {"from_attributes": True}


class BrandingScanRequest(BaseModel):
    scan_run_id: str
    scan_target: str
    content: str


class BrandingScanResponse(BaseModel):
    verdict: str
    findings: list[dict]


# ── Helpers ────────────────────────────────────────────────────────────────────


def _config_response(cfg) -> WhitelabelConfigResponse:
    return WhitelabelConfigResponse(
        id=cfg.id,
        tenant_id=cfg.tenant_id,
        product_display_name=cfg.product_display_name,
        primary_color_hex=cfg.primary_color_hex,
        secondary_color_hex=cfg.secondary_color_hex,
        font_family=cfg.font_family,
        content_approval_flow=cfg.content_approval_flow,
    )


def _domain_response(dm) -> DomainMappingResponse:
    return DomainMappingResponse(
        id=dm.id,
        domain=dm.domain,
        domain_type=dm.domain_type.value if hasattr(dm.domain_type, "value") else dm.domain_type,
        verification_status=(
            dm.verification_status.value
            if hasattr(dm.verification_status, "value")
            else dm.verification_status
        ),
        ssl_cert_status=(
            dm.ssl_cert_status.value
            if hasattr(dm.ssl_cert_status, "value")
            else dm.ssl_cert_status
        ),
    )


def _asset_response(a) -> ThemeAssetResponse:
    return ThemeAssetResponse(
        id=a.id,
        asset_kind=a.asset_kind,
        content_type=a.content_type,
        gcs_object_path=a.gcs_object_path,
    )


def _job_response(j) -> BulkImportResponse:
    return BulkImportResponse(
        id=j.id,
        status=j.status.value if hasattr(j.status, "value") else j.status,
        total_rows=j.total_rows,
        succeeded_rows=j.succeeded_rows,
        failed_rows=j.failed_rows,
    )


# ── Endpoints ──────────────────────────────────────────────────────────────────


@router.get("/config", response_model=WhitelabelConfigResponse)
async def get_config(
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Get whitelabel config for the current tenant."""
    ctx.assert_role(UserRole.agency_admin)
    tenant_id = ctx.assert_tenant()

    from app.modules.whitelabel.service import WhitelabelService

    factory = get_session_factory()
    async with get_db_session(factory, ctx.to_request_context()) as session:
        svc = WhitelabelService(session)
        cfg = await svc.get_or_create_config(tenant_id)
    return _config_response(cfg)


@router.put("/config", response_model=WhitelabelConfigResponse)
async def update_config(
    body: UpdateConfigRequest,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Update whitelabel config for the current tenant."""
    ctx.assert_role(UserRole.agency_admin)
    tenant_id = ctx.assert_tenant()

    from app.modules.whitelabel.service import WhitelabelService

    factory = get_session_factory()
    async with get_db_session(factory, ctx.to_request_context()) as session:
        svc = WhitelabelService(session)
        # Ensure config exists first
        await svc.get_or_create_config(tenant_id)
        try:
            cfg = await svc.update_config(tenant_id=tenant_id, **body.model_dump(exclude_none=True))
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "validation_error", "message": str(exc)},
            ) from exc
    return _config_response(cfg)


@router.get("/domains", response_model=list[DomainMappingResponse])
async def list_domains(
    ctx: TenantContext = Depends(get_tenant_context),
):
    """List non-revoked domain mappings for the current tenant."""
    ctx.assert_role(UserRole.agency_admin)
    tenant_id = ctx.assert_tenant()

    from app.modules.whitelabel.repository import DomainMappingRepository

    factory = get_session_factory()
    async with get_db_session(factory, ctx.to_request_context()) as session:
        repo = DomainMappingRepository(session)
        domains = await repo.list_for_tenant(tenant_id)
    return [_domain_response(d) for d in domains]


@router.post("/domains", response_model=DomainMappingResponse, status_code=201)
async def add_domain(
    body: AddDomainRequest,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Add a new domain mapping."""
    ctx.assert_role(UserRole.agency_admin)
    tenant_id = ctx.assert_tenant()

    from app.modules.whitelabel.service import DomainService

    factory = get_session_factory()
    async with get_db_session(factory, ctx.to_request_context()) as session:
        svc = DomainService(session)
        mapping = await svc.add_domain(
            tenant_id=tenant_id,
            domain=body.domain,
            domain_type=body.domain_type,
            verification_method=body.verification_method,
        )
    return _domain_response(mapping)


@router.post("/domains/{mapping_id}/verify", response_model=DomainMappingResponse)
async def verify_domain(
    mapping_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Trigger domain verification."""
    ctx.assert_role(UserRole.agency_admin)
    tenant_id = ctx.assert_tenant()

    from app.modules.whitelabel.repository import DomainMappingRepository
    from app.modules.whitelabel.service import DomainService

    factory = get_session_factory()
    async with get_db_session(factory, ctx.to_request_context()) as session:
        svc = DomainService(session)
        ok, message = await svc.verify_domain(mapping_id=mapping_id, tenant_id=tenant_id)
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "not_found", "message": message},
            )
        repo = DomainMappingRepository(session)
        mapping = await repo.get(mapping_id, tenant_id)
    if mapping is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": "Domain mapping not found"},
        )
    return _domain_response(mapping)


@router.delete("/domains/{mapping_id}", status_code=204)
async def revoke_domain(
    mapping_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Revoke a domain mapping."""
    ctx.assert_role(UserRole.agency_admin)
    tenant_id = ctx.assert_tenant()

    from app.modules.whitelabel.service import DomainService

    factory = get_session_factory()
    async with get_db_session(factory, ctx.to_request_context()) as session:
        svc = DomainService(session)
        await svc.revoke_domain(mapping_id=mapping_id, tenant_id=tenant_id)


@router.get("/assets", response_model=list[ThemeAssetResponse])
async def list_assets(
    ctx: TenantContext = Depends(get_tenant_context),
):
    """List theme assets for the current tenant."""
    ctx.assert_role(UserRole.agency_admin)
    tenant_id = ctx.assert_tenant()

    from app.modules.whitelabel.repository import ThemeAssetRepository

    factory = get_session_factory()
    async with get_db_session(factory, ctx.to_request_context()) as session:
        repo = ThemeAssetRepository(session)
        assets = await repo.list_for_tenant(tenant_id)
    return [_asset_response(a) for a in assets]


@router.post("/assets", response_model=ThemeAssetResponse, status_code=201)
async def register_asset(
    body: RegisterAssetRequest,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Register a new theme asset."""
    ctx.assert_role(UserRole.agency_admin)
    tenant_id = ctx.assert_tenant()

    from app.modules.whitelabel.service import WhitelabelService

    factory = get_session_factory()
    async with get_db_session(factory, ctx.to_request_context()) as session:
        svc = WhitelabelService(session)
        try:
            asset = await svc.register_theme_asset(
                tenant_id=tenant_id,
                asset_kind=body.asset_kind,
                content_type=body.content_type,
                gcs_object_path=body.gcs_object_path,
                width_px=body.width_px,
                height_px=body.height_px,
                safe_for_email=body.safe_for_email,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "validation_error", "message": str(exc)},
            ) from exc
    return _asset_response(asset)


@router.get("/bulk-imports", response_model=list[BulkImportResponse])
async def list_bulk_imports(
    ctx: TenantContext = Depends(get_tenant_context),
):
    """List bulk import jobs for the current tenant."""
    ctx.assert_role(UserRole.agency_admin)
    tenant_id = ctx.assert_tenant()

    from app.modules.whitelabel.repository import BulkImportJobRepository

    factory = get_session_factory()
    async with get_db_session(factory, ctx.to_request_context()) as session:
        repo = BulkImportJobRepository(session)
        jobs = await repo.list_for_tenant(tenant_id)
    return [_job_response(j) for j in jobs]


@router.post("/bulk-import", response_model=BulkImportResponse, status_code=201)
async def create_bulk_import(
    body: BulkImportRequest,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Create and immediately process a bulk import job."""
    ctx.assert_role(UserRole.agency_admin)
    tenant_id = ctx.assert_tenant()
    user_id = ctx.user_id

    from app.modules.whitelabel.service import BulkImportService

    factory = get_session_factory()
    async with get_db_session(factory, ctx.to_request_context()) as session:
        svc = BulkImportService(session)
        job = await svc.create_job(
            tenant_id=tenant_id,
            initiated_by_user_id=user_id,
            source_object_path=body.source_object_path,
        )
        if body.rows:
            await svc.process_csv_rows(
                job_id=job.id,
                tenant_id=tenant_id,
                rows=body.rows,
            )
            # Refresh job state
            job = await svc.get_job(job_id=job.id, tenant_id=tenant_id) or job
    return _job_response(job)


@router.get("/bulk-imports/{job_id}", response_model=BulkImportResponse)
async def get_bulk_import(
    job_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Get status of a bulk import job."""
    ctx.assert_role(UserRole.agency_admin)
    tenant_id = ctx.assert_tenant()

    from app.modules.whitelabel.service import BulkImportService

    factory = get_session_factory()
    async with get_db_session(factory, ctx.to_request_context()) as session:
        svc = BulkImportService(session)
        job = await svc.get_job(job_id=job_id, tenant_id=tenant_id)

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": "Bulk import job not found"},
        )
    return _job_response(job)


@router.get("/clients")
async def list_clients(
    limit: int = 50,
    cursor: Optional[str] = None,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """List businesses (dummy paginated list)."""
    ctx.assert_role(UserRole.agency_admin)
    # Dummy implementation — returns empty paginated response
    return {
        "items": [],
        "limit": limit,
        "cursor": cursor,
        "next_cursor": None,
    }


@router.post("/scan-branding", response_model=BrandingScanResponse)
async def scan_branding(
    body: BrandingScanRequest,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Scan content for CitedBy branding leaks."""
    ctx.assert_role(UserRole.agency_admin)
    ctx.assert_tenant()

    from app.modules.whitelabel.service import WhitelabelService

    factory = get_session_factory()
    async with get_db_session(factory, ctx.to_request_context()) as session:
        svc = WhitelabelService(session)
        report = await svc.scan_for_branding_leaks(
            scan_run_id=body.scan_run_id,
            scan_target=body.scan_target,
            content=body.content,
        )
    return BrandingScanResponse(verdict=report.verdict, findings=report.findings)
