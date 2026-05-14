"""FastAPI application factory with lifespan management."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import v1_router
from app.core.database import db_manager
from app.core.exceptions import CitedByError


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialise and teardown application resources."""
    from app.core.config import get_settings

    settings = get_settings()
    db_manager.init(
        str(settings.database_url),
        public_audit_dsn=str(settings.public_audit_database_url)
        if settings.public_audit_database_url
        else None,
        echo=settings.debug,
        main_pool_min=settings.db_pool_min_size,
        main_pool_max=settings.db_pool_max_size,
        audit_pool_min=settings.public_audit_pool_min_size,
        audit_pool_max=settings.public_audit_pool_max_size,
    )
    yield
    await db_manager.close()


def create_app() -> FastAPI:
    import os

    # Read lightweight env vars directly to avoid requiring full Settings validation
    # during app import in tests. Full Settings is only loaded inside lifespan.
    _env = os.getenv("ENVIRONMENT", "development").lower()
    _allowed = [h.strip() for h in os.getenv("ALLOWED_HOSTS", "").split(",") if h.strip()]

    is_production = _env == "production"
    app = FastAPI(
        title="CitedBy API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None if is_production else "/docs",
        redoc_url=None if is_production else "/redoc",
        openapi_url=None if is_production else "/openapi.json",
    )

    if _allowed:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=_allowed)

    app.include_router(v1_router)

    @app.exception_handler(CitedByError)
    async def citedby_error_handler(request: Request, exc: CitedByError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content=exc.to_dict(),
        )

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
