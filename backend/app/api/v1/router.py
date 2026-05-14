"""Mount all v1 routers."""

from fastapi import APIRouter

from app.api.v1.routers.audits import router as audits_router
from app.api.v1.routers.businesses import router as businesses_router
from app.api.v1.routers.tenants import router as tenants_router

v1_router = APIRouter(prefix="/api/v1")
v1_router.include_router(tenants_router)
v1_router.include_router(businesses_router)
v1_router.include_router(audits_router)
