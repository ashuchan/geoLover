"""Service layer for Ops/Admin module (Phase 8)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ops.models import ImpersonationLog, QuotaEnforcementLog, StatusComponent, TenantGraceExtension
from app.modules.ops.repository import (
    ImpersonationLogRepository,
    QuotaEnforcementLogRepository,
    StatusComponentRepository,
    TenantGraceExtensionRepository,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Domain Events ──────────────────────────────────────────────────────────────


@dataclass
class QuotaBlocked:
    name: str = "QuotaBlocked"
    tenant_id: uuid.UUID = None  # type: ignore[assignment]
    quota_kind: str = ""
    action: str = ""

    def __init__(self, tenant_id: uuid.UUID, quota_kind: str, action: str) -> None:
        self.name = "QuotaBlocked"
        self.tenant_id = tenant_id
        self.quota_kind = quota_kind
        self.action = action


@dataclass
class ImpersonationStarted:
    name: str = "ImpersonationStarted"
    log_id: uuid.UUID = None  # type: ignore[assignment]
    admin_user_id: uuid.UUID = None  # type: ignore[assignment]
    impersonated_tenant_id: uuid.UUID = None  # type: ignore[assignment]

    def __init__(
        self,
        log_id: uuid.UUID,
        admin_user_id: uuid.UUID,
        impersonated_tenant_id: uuid.UUID,
    ) -> None:
        self.name = "ImpersonationStarted"
        self.log_id = log_id
        self.admin_user_id = admin_user_id
        self.impersonated_tenant_id = impersonated_tenant_id


@dataclass
class ImpersonationEnded:
    name: str = "ImpersonationEnded"
    log_id: uuid.UUID = None  # type: ignore[assignment]

    def __init__(self, log_id: uuid.UUID) -> None:
        self.name = "ImpersonationEnded"
        self.log_id = log_id


# ── Default status components ──────────────────────────────────────────────────

_DEFAULT_COMPONENTS = [
    {"name": "api", "description": "Core API", "health_signal_query": "error_rate_5m < 0.01"},
    {
        "name": "audit_engine",
        "description": "Audit Engine",
        "health_signal_query": "audit_completion_rate > 0.95",
    },
    {
        "name": "content_generation",
        "description": "Content Generation (LLM)",
        "health_signal_query": "llm_error_rate_5m < 0.05",
    },
    {
        "name": "publishing",
        "description": "Publishing Pipeline",
        "health_signal_query": "publish_success_rate > 0.98",
    },
    {
        "name": "notifications",
        "description": "Notification Delivery",
        "health_signal_query": "email_delivery_rate > 0.97",
    },
]


# ── QuotaService ───────────────────────────────────────────────────────────────


class QuotaService:
    """Manages quota checking, enforcement logging, and grace extensions."""

    _QUOTA_KINDS = frozenset(
        [
            "audits",
            "content_briefs",
            "llm_spend",
            "businesses",
            "publish_channels",
            "bulk_import_rows",
            "api_requests",
        ]
    )

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._pending_events: list = []
        self._log_repo = QuotaEnforcementLogRepository(session)
        self._grace_repo = TenantGraceExtensionRepository(session)

    @property
    def pending_events(self) -> list:
        return list(self._pending_events)

    async def check_quota(
        self,
        *,
        tenant_id: uuid.UUID,
        business_id: Optional[uuid.UUID] = None,
        quota_kind: str,
        current_value: float,
        limit: float,
        grace_days: int = 7,
    ) -> tuple[str, bool]:
        """
        Returns (action, is_blocked).
        action is 'ok', 'soft_warn', or 'hard_block'.
        """
        if quota_kind not in self._QUOTA_KINDS:
            return ("ok", False)

        pct = current_value / limit if limit > 0 else 0

        if pct < 0.8:
            return ("ok", False)

        if pct < 1.0:
            # Soft warn zone: 80-99%
            await self.log_action(
                tenant_id=tenant_id,
                business_id=business_id,
                quota_kind=quota_kind,
                action="soft_warn",
                threshold_pct=pct,
            )
            return ("soft_warn", False)

        # pct >= 1.0: check for active grace
        now = _utcnow()
        grace = await self._grace_repo.get_active(tenant_id, quota_kind, now)
        if grace is not None:
            return ("soft_warn", False)

        # Hard block
        await self.log_action(
            tenant_id=tenant_id,
            business_id=business_id,
            quota_kind=quota_kind,
            action="hard_block",
            threshold_pct=pct,
        )
        self._pending_events.append(
            QuotaBlocked(
                tenant_id=tenant_id,
                quota_kind=quota_kind,
                action="hard_block",
            )
        )
        return ("hard_block", True)

    async def log_action(
        self,
        *,
        tenant_id: uuid.UUID,
        business_id: Optional[uuid.UUID] = None,
        quota_kind: str,
        action: str,
        threshold_pct: Optional[float] = None,
        detail: Optional[dict] = None,
    ) -> QuotaEnforcementLog:
        """Create a quota enforcement log entry."""
        return await self._log_repo.create(
            tenant_id=tenant_id,
            business_id=business_id,
            quota_kind=quota_kind,
            action=action,
            threshold_pct=threshold_pct,
            triggered_at=_utcnow(),
            detail=detail,
        )

    async def extend_grace(
        self,
        *,
        tenant_id: uuid.UUID,
        quota_kind: str,
        days: int,
        extended_by_user_id: uuid.UUID,
        reason: Optional[str] = None,
    ) -> TenantGraceExtension:
        """Create a grace period extension."""
        extended_until = _utcnow() + timedelta(days=days)
        return await self._grace_repo.create(
            tenant_id=tenant_id,
            quota_kind=quota_kind,
            extended_until=extended_until,
            extended_by_user_id=extended_by_user_id,
            reason=reason,
        )

    async def is_in_grace(self, *, tenant_id: uuid.UUID, quota_kind: str) -> bool:
        """Check if tenant has an active grace extension for the given quota kind."""
        now = _utcnow()
        grace = await self._grace_repo.get_active(tenant_id, quota_kind, now)
        return grace is not None


# ── AdminOpsService ────────────────────────────────────────────────────────────


class AdminOpsService:
    """Manages admin impersonation and status page components."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._pending_events: list = []
        self._impersonation_repo = ImpersonationLogRepository(session)
        self._status_repo = StatusComponentRepository(session)

    @property
    def pending_events(self) -> list:
        return list(self._pending_events)

    async def start_impersonation(
        self,
        *,
        admin_user_id: uuid.UUID,
        impersonated_tenant_id: uuid.UUID,
        reason: str,
        impersonated_user_id: Optional[uuid.UUID] = None,
    ) -> ImpersonationLog:
        """Create an ImpersonationLog and emit ImpersonationStarted event."""
        log = await self._impersonation_repo.create(
            admin_user_id=admin_user_id,
            impersonated_tenant_id=impersonated_tenant_id,
            impersonated_user_id=impersonated_user_id,
            reason=reason,
        )
        self._pending_events.append(
            ImpersonationStarted(
                log_id=log.id,
                admin_user_id=admin_user_id,
                impersonated_tenant_id=impersonated_tenant_id,
            )
        )
        return log

    async def end_impersonation(
        self,
        *,
        log_id: uuid.UUID,
        admin_user_id: uuid.UUID,
    ) -> None:
        """End impersonation session, verifying admin_user_id matches."""
        log = await self._impersonation_repo.get(log_id)
        if log is None:
            from app.core.exceptions import NotFoundError
            raise NotFoundError(f"Impersonation log {log_id} not found")
        if log.admin_user_id != admin_user_id:
            from app.core.exceptions import PermissionDeniedError
            raise PermissionDeniedError("Cannot end impersonation session owned by another admin")
        await self._impersonation_repo.end_session(log_id)
        self._pending_events.append(ImpersonationEnded(log_id=log_id))

    async def upsert_status_component(
        self,
        *,
        name: str,
        description: Optional[str] = None,
        health_signal_query: str,
        state: str = "operational",
    ) -> StatusComponent:
        """Get or create a status component, updating its state."""
        component = await self._status_repo.get_by_name(name)
        if component is None:
            component = await self._status_repo.create(
                name=name,
                description=description,
                health_signal_query=health_signal_query,
                last_known_state=state,
                last_evaluated_at=_utcnow(),
            )
        else:
            await self._status_repo.update_state(component.id, state, _utcnow())
            component.last_known_state = state
            component.last_evaluated_at = _utcnow()
        return component

    async def update_component_state(
        self, *, name: str, state: str
    ) -> Optional[StatusComponent]:
        """Get by name, update state with now() as evaluated_at. Returns None if not found."""
        component = await self._status_repo.get_by_name(name)
        if component is None:
            return None
        now = _utcnow()
        await self._status_repo.update_state(component.id, state, now)
        component.last_known_state = state
        component.last_evaluated_at = now
        return component

    async def get_all_component_states(self) -> list[StatusComponent]:
        """List all status components."""
        return await self._status_repo.list_all()

    async def seed_default_components(self) -> list[StatusComponent]:
        """Create default status components if they don't exist."""
        results = []
        for spec in _DEFAULT_COMPONENTS:
            component = await self._status_repo.get_by_name(spec["name"])
            if component is None:
                component = await self._status_repo.create(
                    name=spec["name"],
                    description=spec["description"],
                    health_signal_query=spec["health_signal_query"],
                    last_known_state="operational",
                )
            results.append(component)
        return results
