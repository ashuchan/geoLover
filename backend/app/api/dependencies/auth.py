"""FastAPI dependencies for authentication and tenant resolution.

The flow (per Phase 1 §4.2):
1. Extract JWT from Authorization header
2. Validate signature
3. Resolve tenant from Host header (subdomain → slug → tenant)
4. Load user's active memberships and assert access
5. Inject RequestContext into database session
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import Depends, Header, HTTPException, Request, status
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.database import RequestContext, get_db_session
from app.core.exceptions import AuthenticationError, PermissionDeniedError, TenantNotFoundError
from app.modules.identity.models import Membership, UserRole
from app.modules.identity.repository import MembershipRepository, TenantRepository, UserRepository


# ── Token schemas ─────────────────────────────────────────────────────────────


class TokenPayload(BaseModel):
    sub: str  # Auth0 subject = auth_provider_id
    tenant_id: Optional[str] = None  # custom claim injected by Auth0 rule
    is_platform_admin: bool = False


class AuthenticatedUser(BaseModel):
    user_id: uuid.UUID
    auth_provider_id: str
    tenant_id: Optional[uuid.UUID] = None
    is_platform_admin: bool = False
    active_memberships: list[Membership] = []

    class Config:
        arbitrary_types_allowed = True


# ── JWT validation ────────────────────────────────────────────────────────────


def _decode_jwt(token: str, secret: str, algorithm: str) -> TokenPayload:
    try:
        payload = jwt.decode(token, secret, algorithms=[algorithm])
        return TokenPayload(**payload)
    except JWTError as exc:
        raise AuthenticationError(f"Invalid token: {exc}") from exc


async def _resolve_tenant_from_host(
    host: str,
    tenant_repo: TenantRepository,
) -> Optional[uuid.UUID]:
    """Extract tenant_id from subdomain, e.g. 'agencyA.citedby.app' → tenant."""
    parts = host.split(".")
    # e.g. agencyA.citedby.app → subdomain='agencyA'
    if len(parts) >= 3 and parts[-2] == "citedby" and parts[-1] in ("app", "dev"):
        slug = parts[0].lower()
        if slug not in ("app", "www", "api"):
            try:
                tenant = await tenant_repo.get_by_slug(slug)
                return tenant.id
            except TenantNotFoundError:
                pass
    return None


# ── Dependency factories (these depend on app startup wiring) ─────────────────


def get_jwt_settings() -> tuple[str, str]:
    """Return (secret_key, algorithm) from app settings."""
    from app.core.config import get_settings
    s = get_settings()
    return s.secret_key.get_secret_value(), s.jwt_algorithm


def get_master_key() -> str:
    from app.core.config import get_settings
    return get_settings().encryption_master_key.get_secret_value()


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    from app.core.database import db_manager
    return db_manager._main_factory  # type: ignore[return-value]


# ── Reusable FastAPI dependency ───────────────────────────────────────────────


class TenantContext:
    """Resolved once per request; passed to handlers via Depends."""

    def __init__(
        self,
        user_id: uuid.UUID,
        auth_provider_id: str,
        tenant_id: Optional[uuid.UUID],
        is_platform_admin: bool,
        memberships: list[Membership],
    ) -> None:
        self.user_id = user_id
        self.auth_provider_id = auth_provider_id
        self.tenant_id = tenant_id
        self.is_platform_admin = is_platform_admin
        self.memberships = memberships

    def assert_tenant(self) -> uuid.UUID:
        if self.tenant_id is None:
            raise PermissionDeniedError("No tenant context for this request")
        return self.tenant_id

    def has_role(self, *roles: UserRole) -> bool:
        if self.is_platform_admin:
            return True
        return any(
            m.role in roles and m.tenant_id == self.tenant_id
            for m in self.memberships
        )

    def assert_role(self, *roles: UserRole) -> None:
        if not self.has_role(*roles):
            raise PermissionDeniedError(
                f"Required role(s): {[r.value for r in roles]}"
            )

    def to_request_context(self) -> RequestContext:
        if self.tenant_id is None:
            raise PermissionDeniedError("No tenant context")

        # Build business_scope_ids from membership
        scope_ids: list[uuid.UUID] = []
        for m in self.memberships:
            if m.tenant_id == self.tenant_id and m.business_scope_ids:
                scope_ids.extend(m.business_scope_ids)

        return RequestContext(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            is_platform_admin=self.is_platform_admin,
            business_scope_ids=list(set(scope_ids)),
        )


async def get_tenant_context(request: Request) -> TenantContext:
    """FastAPI dependency: validate JWT, resolve tenant, load memberships."""
    from app.core.database import db_manager

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header",
        )

    token = auth_header[len("Bearer "):]
    secret, algorithm = get_jwt_settings()

    try:
        payload = _decode_jwt(token, secret, algorithm)
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        )

    # Non-RLS session for identity lookups (memberships table is not under RLS)
    factory = get_session_factory()
    if factory is None:
        raise HTTPException(status_code=503, detail="Database not initialised")

    async with factory() as session:
        user_repo = UserRepository(session)
        user = await user_repo.get_by_auth_provider_id(payload.sub)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
            )

        membership_repo = MembershipRepository(session)
        memberships = list(await membership_repo.get_active_for_user(user.id))

        # Verify platform_admin claim against DB
        is_platform_admin = payload.is_platform_admin and await membership_repo.is_platform_admin(
            user.id
        )

        # Resolve tenant from Host header
        host = request.headers.get("host", "")
        tenant_repo = TenantRepository(session)
        tenant_id = await _resolve_tenant_from_host(host, tenant_repo)

        return TenantContext(
            user_id=user.id,
            auth_provider_id=payload.sub,
            tenant_id=tenant_id,
            is_platform_admin=is_platform_admin,
            memberships=memberships,
        )
