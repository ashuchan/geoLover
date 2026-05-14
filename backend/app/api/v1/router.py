"""Mount all v1 routers."""

from fastapi import APIRouter

from app.api.v1.routers.audits import router as audits_router
from app.api.v1.routers.businesses import router as businesses_router
from app.api.v1.routers.content import router as content_router
from app.api.v1.routers.free_audit import router as free_audit_router
from app.api.v1.routers.notifications import router as notifications_router
from app.api.v1.routers.publishing import router as publishing_router
from app.api.v1.routers.reports import router as reports_router
from app.api.v1.routers.tenants import router as tenants_router
from app.api.v1.routers.agency import router as agency_router
from app.api.v1.routers.ops import router as ops_router

v1_router = APIRouter(prefix="/api/v1")
v1_router.include_router(tenants_router)
v1_router.include_router(businesses_router)
v1_router.include_router(audits_router)
v1_router.include_router(reports_router)
v1_router.include_router(free_audit_router)
v1_router.include_router(content_router)
v1_router.include_router(publishing_router)
v1_router.include_router(notifications_router)
v1_router.include_router(agency_router)
v1_router.include_router(ops_router)
