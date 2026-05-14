"""Business Profile service layer.

Enforces domain invariants: name normalization, direct_business singleton,
RLS-scoped operations, identity uniqueness scoring.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import DomainEvent, event_bus
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import (
    BusinessNotFoundError,
    BusinessSuspendedError,
    ConflictError,
    PermissionDeniedError,
    ValidationError,
)
from app.core.security import encrypt_pii, normalize_email, normalize_phone, normalize_text
from app.modules.business_profile.models import (
    AliasType,
    Business,
    BusinessAlias,
    BusinessKeyword,
    BusinessLocation,
    BusinessSource,
    BusinessStatus,
    FreeAuditToken,
    KeywordSource,
)
from app.modules.business_profile.repository import (
    BusinessAliasRepository,
    BusinessKeywordRepository,
    BusinessLocationRepository,
    BusinessRepository,
    CategoryRepository,
    FreeAuditTokenRepository,
)
from app.modules.identity.models import TenantType, UserRole
from app.modules.identity.repository import MembershipRepository, TenantRepository

_FREE_AUDIT_TOKEN_BYTES = 32
_FREE_AUDIT_EXPIRY_DAYS = 14


# ── Domain events ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BusinessCreated(DomainEvent):
    business_id: uuid.UUID = uuid.UUID(int=0)
    tenant_id: uuid.UUID = uuid.UUID(int=0)
    source: BusinessSource = BusinessSource.self_signup


@dataclass(frozen=True)
class BusinessProfileUpdated(DomainEvent):
    business_id: uuid.UUID = uuid.UUID(int=0)
    tenant_id: uuid.UUID = uuid.UUID(int=0)


@dataclass(frozen=True)
class BusinessDeleted(DomainEvent):
    business_id: uuid.UUID = uuid.UUID(int=0)
    tenant_id: uuid.UUID = uuid.UUID(int=0)


# ── helpers ───────────────────────────────────────────────────────────────────


def _compute_uniqueness_score(name_normalized: str, aliases: list[str]) -> float:
    """Heuristic: short or generic names score low (closer to 0).

    Simple proxy: ratio of unique chars to total chars; penalise very short names.
    Phase 2 will improve this with jaro-winkler against a corpus.
    """
    all_text = " ".join([name_normalized] + aliases)
    if not all_text.strip():
        return 0.0
    unique_chars = len(set(all_text.replace(" ", "")))
    total_chars = len(all_text.replace(" ", ""))
    ratio = unique_chars / total_chars if total_chars else 0.0
    length_penalty = min(1.0, len(name_normalized) / 10.0)
    return round(ratio * length_penalty, 4)


# ── BusinessProfileService ────────────────────────────────────────────────────


class BusinessProfileService:
    def __init__(self, session: AsyncSession, master_key_b64: str) -> None:
        self._session = session
        self._master_key = master_key_b64
        self._business_repo = BusinessRepository(session)
        self._alias_repo = BusinessAliasRepository(session)
        self._location_repo = BusinessLocationRepository(session)
        self._keyword_repo = BusinessKeywordRepository(session)
        self._category_repo = CategoryRepository(session)
        self._tenant_repo = TenantRepository(session)
        self._membership_repo = MembershipRepository(session)
        self._pending_events: list[DomainEvent] = []

    @property
    def pending_events(self) -> list[DomainEvent]:
        return list(self._pending_events)

    async def flush_pending_events(self) -> None:
        events, self._pending_events = self._pending_events, []
        for evt in events:
            await event_bus.publish(evt)

    async def _assert_write_access(
        self, actor_user_id: uuid.UUID, tenant_id: uuid.UUID, business_id: Optional[uuid.UUID] = None
    ) -> None:
        has_access = await self._membership_repo.has_role(
            actor_user_id,
            tenant_id,
            UserRole.agency_admin,
            UserRole.business_owner,
        ) or await self._membership_repo.is_platform_admin(actor_user_id)

        if not has_access and business_id is not None:
            has_access = await self._membership_repo.has_business_scope_access(
                actor_user_id, tenant_id, business_id
            )

        if not has_access:
            raise PermissionDeniedError("Insufficient permissions")

    async def create_business(
        self,
        *,
        actor_user_id: uuid.UUID,
        tenant_id: uuid.UUID,
        canonical_name: str,
        category_id: uuid.UUID,
        source: BusinessSource,
        description: Optional[str] = None,
        website_url: Optional[str] = None,
        primary_email: Optional[str] = None,
        primary_phone: Optional[str] = None,
        locale: str = "en-IN",
        subcategory_ids: Optional[list[uuid.UUID]] = None,
        status: BusinessStatus = BusinessStatus.trial,
    ) -> Business:
        if not canonical_name.strip():
            raise ValidationError("canonical_name cannot be empty")
        if len(canonical_name) < 2 or len(canonical_name) > 200:
            raise ValidationError("canonical_name must be 2–200 characters")

        await self._assert_write_access(actor_user_id, tenant_id)

        # Validate category exists
        await self._category_repo.get_by_id(category_id)

        name_normalized = normalize_text(canonical_name)

        primary_email_encrypted = (
            encrypt_pii(self._master_key, primary_email)
            if primary_email
            else None
        )
        primary_phone_encrypted = (
            encrypt_pii(self._master_key, primary_phone)
            if primary_phone
            else None
        )

        business = await self._business_repo.create(
            tenant_id=tenant_id,
            canonical_name=canonical_name,
            name_normalized=name_normalized,
            category_id=category_id,
            source=source,
            description=description,
            website_url=website_url,
            primary_email_encrypted=primary_email_encrypted,
            primary_phone_encrypted=primary_phone_encrypted,
            locale=locale,
            status=status,
            subcategory_ids=subcategory_ids,
        )

        score = _compute_uniqueness_score(name_normalized, [])
        await self._business_repo.update(business.id, identity_uniqueness_score=score)

        self._pending_events.append(
            BusinessCreated(
                business_id=business.id,
                tenant_id=tenant_id,
                source=source,
            )
        )
        return business

    async def get_business(
        self,
        business_id: uuid.UUID,
        *,
        tenant_id: Optional[uuid.UUID] = None,
        actor_user_id: Optional[uuid.UUID] = None,
    ) -> Business:
        business = await self._business_repo.get_by_id(business_id)
        if tenant_id is not None and business.tenant_id != tenant_id:
            raise BusinessNotFoundError(f"Business {business_id} not found")
        if actor_user_id is not None and tenant_id is not None:
            is_broad = await self._membership_repo.has_role(
                actor_user_id,
                tenant_id,
                UserRole.agency_admin,
                UserRole.business_owner,
            )
            is_admin = await self._membership_repo.is_platform_admin(actor_user_id)
            if not (is_broad or is_admin):
                scoped = await self._membership_repo.has_business_scope_access(
                    actor_user_id, tenant_id, business_id
                )
                if not scoped:
                    raise BusinessNotFoundError(f"Business {business_id} not found")
        return business

    async def list_businesses(
        self,
        tenant_id: uuid.UUID,
        *,
        status: Optional[BusinessStatus] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Business]:
        return await self._business_repo.list_for_tenant(
            tenant_id, status=status, limit=limit, offset=offset
        )

    async def update_business(
        self,
        *,
        actor_user_id: uuid.UUID,
        business_id: uuid.UUID,
        tenant_id: uuid.UUID,
        canonical_name: Optional[str] = None,
        description: Optional[str] = None,
        website_url: Optional[str] = None,
        primary_email: Optional[str] = None,
        primary_phone: Optional[str] = None,
        status: Optional[BusinessStatus] = None,
    ) -> Business:
        await self._assert_write_access(actor_user_id, tenant_id, business_id)
        await self.get_business(business_id, tenant_id=tenant_id)

        name_normalized = normalize_text(canonical_name) if canonical_name else None
        primary_email_encrypted = encrypt_pii(self._master_key, primary_email) if primary_email else None
        primary_phone_encrypted = encrypt_pii(self._master_key, primary_phone) if primary_phone else None

        business = await self._business_repo.update(
            business_id,
            canonical_name=canonical_name,
            name_normalized=name_normalized,
            description=description,
            website_url=website_url,
            primary_email_encrypted=primary_email_encrypted,
            primary_phone_encrypted=primary_phone_encrypted,
            status=status,
        )

        if canonical_name is not None:
            aliases = await self._alias_repo.list_for_business(business_id)
            alias_texts = [a.alias_text_normalized for a in aliases]
            score = _compute_uniqueness_score(business.name_normalized, alias_texts)
            await self._business_repo.update(business_id, identity_uniqueness_score=score)

        self._pending_events.append(
            BusinessProfileUpdated(business_id=business_id, tenant_id=tenant_id)
        )
        return business

    async def delete_business(
        self,
        *,
        actor_user_id: uuid.UUID,
        business_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> Business:
        await self._assert_write_access(actor_user_id, tenant_id, business_id)
        await self.get_business(business_id, tenant_id=tenant_id)
        business = await self._business_repo.soft_delete(business_id)
        self._pending_events.append(BusinessDeleted(business_id=business_id, tenant_id=tenant_id))
        return business

    async def add_alias(
        self,
        *,
        actor_user_id: uuid.UUID,
        business_id: uuid.UUID,
        tenant_id: uuid.UUID,
        alias_text: str,
        alias_type: AliasType,
        confidence: float = 1.0,
    ) -> BusinessAlias:
        await self._assert_write_access(actor_user_id, tenant_id, business_id)
        await self.get_business(business_id, tenant_id=tenant_id)
        alias = await self._alias_repo.create(
            business_id=business_id,
            tenant_id=tenant_id,
            alias_text=alias_text,
            alias_text_normalized=normalize_text(alias_text),
            alias_type=alias_type,
            confidence=confidence,
        )
        # Recompute uniqueness score
        business = await self._business_repo.get_by_id(business_id)
        aliases = await self._alias_repo.list_for_business(business_id)
        alias_texts = [a.alias_text_normalized for a in aliases]
        score = _compute_uniqueness_score(business.name_normalized, alias_texts)
        await self._business_repo.update(business_id, identity_uniqueness_score=score)
        self._pending_events.append(BusinessProfileUpdated(business_id=business_id, tenant_id=tenant_id))
        return alias

    async def add_location(
        self,
        *,
        actor_user_id: uuid.UUID,
        business_id: uuid.UUID,
        tenant_id: uuid.UUID,
        city: str,
        is_primary: bool = False,
        **kwargs,
    ) -> BusinessLocation:
        await self._assert_write_access(actor_user_id, tenant_id, business_id)
        await self.get_business(business_id, tenant_id=tenant_id)
        return await self._location_repo.create(
            business_id=business_id,
            tenant_id=tenant_id,
            city=city,
            is_primary=is_primary,
            **kwargs,
        )

    async def add_keywords(
        self,
        *,
        actor_user_id: uuid.UUID,
        business_id: uuid.UUID,
        tenant_id: uuid.UUID,
        keywords: list[str],
        source: KeywordSource = KeywordSource.user,
    ) -> list[BusinessKeyword]:
        await self._assert_write_access(actor_user_id, tenant_id, business_id)
        await self.get_business(business_id, tenant_id=tenant_id)
        keyword_pairs = [(kw, normalize_text(kw)) for kw in keywords if kw.strip()]
        return await self._keyword_repo.create_batch(
            business_id=business_id,
            tenant_id=tenant_id,
            keywords=keyword_pairs,
            source=source,
        )


# ── FreeAuditService ──────────────────────────────────────────────────────────


class FreeAuditService:
    def __init__(self, session: AsyncSession, master_key_b64: str) -> None:
        self._session = session
        self._master_key = master_key_b64
        self._token_repo = FreeAuditTokenRepository(session)
        self._business_repo = BusinessRepository(session)
        self._membership_repo = MembershipRepository(session)

    async def start_free_audit(
        self,
        *,
        actor_user_id: uuid.UUID,
        business_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> FreeAuditToken:
        """Return existing active token or create a new one.

        Handles concurrent creation via IntegrityError catch-and-retry to
        prevent duplicate active tokens from TOCTOU races.
        """
        business = await self._business_repo.get_by_id(business_id)
        if business.tenant_id != tenant_id:
            raise BusinessNotFoundError(f"Business {business_id} not found")

        has_access = await self._membership_repo.has_role(
            actor_user_id,
            tenant_id,
            UserRole.agency_admin,
            UserRole.business_owner,
            UserRole.business_member,
        ) or await self._membership_repo.is_platform_admin(actor_user_id)
        if not has_access:
            raise PermissionDeniedError("Insufficient permissions")

        existing = await self._token_repo.get_active_for_business(business_id)
        if existing:
            return existing

        token = secrets.token_urlsafe(_FREE_AUDIT_TOKEN_BYTES)
        expires_at = datetime.now(timezone.utc) + timedelta(days=_FREE_AUDIT_EXPIRY_DAYS)

        try:
            return await self._token_repo.create(
                token=token,
                business_id=business_id,
                tenant_id=tenant_id,
                expires_at=expires_at,
            )
        except IntegrityError:
            await self._session.rollback()
            existing = await self._token_repo.get_active_for_business(business_id)
            if existing:
                return existing
            raise

    async def get_token_data(self, token: str) -> Optional[FreeAuditToken]:
        return await self._token_repo.get_by_token(token)

    async def claim_token(self, token: str) -> Optional[FreeAuditToken]:
        return await self._token_repo.mark_claimed(token)
