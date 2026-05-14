"""Repository layer for Business Profile module.

All queries run under RLS — the calling session must have app.current_tenant set.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessNotFoundError, ConflictError
from app.modules.business_profile.models import (
    AliasType,
    Business,
    BusinessAlias,
    BusinessCompetitor,
    BusinessKeyword,
    BusinessLocation,
    BusinessSource,
    BusinessStatus,
    CompetitorSource,
    CompetitorStatus,
    FreeAuditToken,
    KeywordSource,
)
from app.modules.categories.models import Category


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── BusinessRepository ────────────────────────────────────────────────────────


class BusinessRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, business_id: uuid.UUID) -> Business:
        result = await self._session.execute(
            select(Business).where(
                Business.id == business_id,
                Business.deleted_at.is_(None),
            )
        )
        business = result.scalar_one_or_none()
        if business is None:
            raise BusinessNotFoundError(f"Business {business_id} not found")
        return business

    async def list_for_tenant(
        self,
        tenant_id: uuid.UUID,
        *,
        status: Optional[BusinessStatus] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Business]:
        stmt = select(Business).where(
            Business.tenant_id == tenant_id,
            Business.deleted_at.is_(None),
        )
        if status is not None:
            stmt = stmt.where(Business.status == status)
        stmt = stmt.limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        canonical_name: str,
        name_normalized: str,
        category_id: uuid.UUID,
        source: BusinessSource,
        description: Optional[str] = None,
        website_url: Optional[str] = None,
        primary_email_encrypted: Optional[bytes] = None,
        primary_phone_encrypted: Optional[bytes] = None,
        locale: str = "en-IN",
        status: BusinessStatus = BusinessStatus.trial,
        subcategory_ids: Optional[list[uuid.UUID]] = None,
    ) -> Business:
        business = Business(
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
            subcategory_ids=subcategory_ids or [],
        )
        self._session.add(business)
        await self._session.flush()
        return business

    async def update(
        self,
        business_id: uuid.UUID,
        *,
        canonical_name: Optional[str] = None,
        name_normalized: Optional[str] = None,
        description: Optional[str] = None,
        website_url: Optional[str] = None,
        status: Optional[BusinessStatus] = None,
        primary_email_encrypted: Optional[bytes] = None,
        primary_phone_encrypted: Optional[bytes] = None,
        identity_uniqueness_score: Optional[float] = None,
        primary_location_id: Optional[uuid.UUID] = None,
    ) -> Business:
        business = await self.get_by_id(business_id)
        if canonical_name is not None:
            business.canonical_name = canonical_name
        if name_normalized is not None:
            business.name_normalized = name_normalized
        if description is not None:
            business.description = description
        if website_url is not None:
            business.website_url = website_url
        if status is not None:
            business.status = status
        if primary_email_encrypted is not None:
            business.primary_email_encrypted = primary_email_encrypted
        if primary_phone_encrypted is not None:
            business.primary_phone_encrypted = primary_phone_encrypted
        if identity_uniqueness_score is not None:
            business.identity_uniqueness_score = identity_uniqueness_score
        if primary_location_id is not None:
            business.primary_location_id = primary_location_id
        business.updated_at = _utcnow()
        await self._session.flush()
        return business

    async def soft_delete(self, business_id: uuid.UUID) -> Business:
        business = await self.get_by_id(business_id)
        business.deleted_at = _utcnow()
        business.status = BusinessStatus.deleted
        await self._session.flush()
        return business


# ── BusinessAliasRepository ───────────────────────────────────────────────────


class BusinessAliasRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_business(self, business_id: uuid.UUID) -> Sequence[BusinessAlias]:
        result = await self._session.execute(
            select(BusinessAlias).where(BusinessAlias.business_id == business_id)
        )
        return result.scalars().all()

    async def create(
        self,
        *,
        business_id: uuid.UUID,
        tenant_id: uuid.UUID,
        alias_text: str,
        alias_text_normalized: str,
        alias_type: AliasType,
        confidence: float = 1.0,
    ) -> BusinessAlias:
        alias = BusinessAlias(
            business_id=business_id,
            tenant_id=tenant_id,
            alias_text=alias_text,
            alias_text_normalized=alias_text_normalized,
            alias_type=alias_type,
            confidence=confidence,
        )
        self._session.add(alias)
        await self._session.flush()
        return alias

    async def delete(self, alias_id: uuid.UUID, *, tenant_id: uuid.UUID) -> None:
        result = await self._session.execute(
            select(BusinessAlias).where(
                BusinessAlias.id == alias_id,
                BusinessAlias.tenant_id == tenant_id,
            )
        )
        alias = result.scalar_one_or_none()
        if alias is None:
            raise BusinessNotFoundError(f"Alias {alias_id} not found")
        await self._session.delete(alias)
        await self._session.flush()


# ── BusinessLocationRepository ────────────────────────────────────────────────


class BusinessLocationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_business(self, business_id: uuid.UUID) -> Sequence[BusinessLocation]:
        result = await self._session.execute(
            select(BusinessLocation).where(BusinessLocation.business_id == business_id)
        )
        return result.scalars().all()

    async def create(
        self,
        *,
        business_id: uuid.UUID,
        tenant_id: uuid.UUID,
        city: str,
        is_primary: bool = False,
        label: Optional[str] = None,
        locality: Optional[str] = None,
        address_line_1: Optional[str] = None,
        address_line_2: Optional[str] = None,
        postal_code: Optional[str] = None,
        state: Optional[str] = None,
        country: str = "IN",
        geo_lat: Optional[float] = None,
        geo_lng: Optional[float] = None,
    ) -> BusinessLocation:
        location = BusinessLocation(
            business_id=business_id,
            tenant_id=tenant_id,
            city=city,
            is_primary=is_primary,
            label=label,
            locality=locality,
            address_line_1=address_line_1,
            address_line_2=address_line_2,
            postal_code=postal_code,
            state=state,
            country=country,
            geo_lat=geo_lat,
            geo_lng=geo_lng,
        )
        self._session.add(location)
        await self._session.flush()
        return location


# ── BusinessKeywordRepository ─────────────────────────────────────────────────


class BusinessKeywordRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_business(self, business_id: uuid.UUID) -> Sequence[BusinessKeyword]:
        result = await self._session.execute(
            select(BusinessKeyword).where(BusinessKeyword.business_id == business_id)
        )
        return result.scalars().all()

    async def create_batch(
        self,
        *,
        business_id: uuid.UUID,
        tenant_id: uuid.UUID,
        keywords: list[tuple[str, str]],  # (keyword, keyword_normalized)
        source: KeywordSource = KeywordSource.user,
        priority: int = 100,
    ) -> list[BusinessKeyword]:
        created = []
        for keyword, keyword_normalized in keywords:
            kw = BusinessKeyword(
                business_id=business_id,
                tenant_id=tenant_id,
                keyword=keyword,
                keyword_normalized=keyword_normalized,
                source=source,
                priority=priority,
            )
            self._session.add(kw)
            created.append(kw)
        await self._session.flush()
        return created


# ── FreeAuditTokenRepository ──────────────────────────────────────────────────


class FreeAuditTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_token(self, token: str) -> Optional[FreeAuditToken]:
        result = await self._session.execute(
            select(FreeAuditToken).where(
                FreeAuditToken.token == token,
                FreeAuditToken.expires_at > _utcnow(),
            )
        )
        return result.scalar_one_or_none()

    async def get_active_for_business(
        self, business_id: uuid.UUID
    ) -> Optional[FreeAuditToken]:
        result = await self._session.execute(
            select(FreeAuditToken).where(
                FreeAuditToken.business_id == business_id,
                FreeAuditToken.claimed_at.is_(None),
                FreeAuditToken.expires_at > _utcnow(),
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        token: str,
        business_id: uuid.UUID,
        tenant_id: uuid.UUID,
        expires_at: datetime,
    ) -> FreeAuditToken:
        fat = FreeAuditToken(
            token=token,
            business_id=business_id,
            tenant_id=tenant_id,
            expires_at=expires_at,
        )
        self._session.add(fat)
        await self._session.flush()
        return fat

    async def mark_claimed(self, token: str) -> Optional[FreeAuditToken]:
        fat = await self.get_by_token(token)
        if fat:
            fat.claimed_at = _utcnow()
            await self._session.flush()
        return fat


# ── CategoryRepository ────────────────────────────────────────────────────────


class CategoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, category_id: uuid.UUID) -> Category:
        result = await self._session.execute(
            select(Category).where(Category.id == category_id)
        )
        cat = result.scalar_one_or_none()
        if cat is None:
            raise BusinessNotFoundError(f"Category {category_id} not found")
        return cat

    async def list_root(self) -> Sequence[Category]:
        result = await self._session.execute(
            select(Category).where(Category.parent_category_id.is_(None))
        )
        return result.scalars().all()

    async def list_children(self, parent_id: uuid.UUID) -> Sequence[Category]:
        result = await self._session.execute(
            select(Category).where(Category.parent_category_id == parent_id)
        )
        return result.scalars().all()
