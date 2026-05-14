"""Repository layer for the Whitelabel & Agency Portal module."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.whitelabel.models import (
    BrandingLeakReport,
    BulkImportJob,
    BulkImportStatus,
    DomainMapping,
    DomainVerificationStatus,
    EmailSenderDomain,
    EmailSenderStatus,
    SslCertStatus,
    ThemeAsset,
    WhitelabelConfig,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class WhitelabelConfigRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, **kwargs) -> WhitelabelConfig:
        obj = WhitelabelConfig(**kwargs)
        self._session.add(obj)
        await self._session.flush()
        return obj

    async def get_by_tenant(self, tenant_id: uuid.UUID) -> Optional[WhitelabelConfig]:
        result = await self._session.execute(
            select(WhitelabelConfig).where(WhitelabelConfig.tenant_id == tenant_id)
        )
        return result.scalar_one_or_none()

    async def update(self, tenant_id: uuid.UUID, **kwargs) -> None:
        vals = {**kwargs, "updated_at": _utcnow()}
        await self._session.execute(
            update(WhitelabelConfig)
            .where(WhitelabelConfig.tenant_id == tenant_id)
            .values(**vals)
        )


class DomainMappingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, **kwargs) -> DomainMapping:
        obj = DomainMapping(**kwargs)
        self._session.add(obj)
        await self._session.flush()
        return obj

    async def get(self, mapping_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[DomainMapping]:
        result = await self._session.execute(
            select(DomainMapping).where(
                DomainMapping.id == mapping_id,
                DomainMapping.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_domain(self, domain: str) -> Optional[DomainMapping]:
        """No tenant filter — domain is unique across all tenants."""
        result = await self._session.execute(
            select(DomainMapping).where(DomainMapping.domain == domain)
        )
        return result.scalar_one_or_none()

    async def list_for_tenant(self, tenant_id: uuid.UUID) -> list[DomainMapping]:
        """Exclude revoked mappings."""
        result = await self._session.execute(
            select(DomainMapping).where(
                DomainMapping.tenant_id == tenant_id,
                DomainMapping.revoked_at.is_(None),
            )
        )
        return list(result.scalars().all())

    async def update_verification(
        self,
        mapping_id: uuid.UUID,
        status: DomainVerificationStatus,
        verified_at: Optional[datetime] = None,
    ) -> None:
        vals: dict = {"verification_status": status}
        if verified_at is not None:
            vals["verified_at"] = verified_at
        await self._session.execute(
            update(DomainMapping).where(DomainMapping.id == mapping_id).values(**vals)
        )

    async def update_ssl(
        self,
        mapping_id: uuid.UUID,
        ssl_cert_status: SslCertStatus,
        ssl_cert_resource_id: Optional[str] = None,
        ssl_active_at: Optional[datetime] = None,
    ) -> None:
        vals: dict = {"ssl_cert_status": ssl_cert_status}
        if ssl_cert_resource_id is not None:
            vals["ssl_cert_resource_id"] = ssl_cert_resource_id
        if ssl_active_at is not None:
            vals["ssl_active_at"] = ssl_active_at
        await self._session.execute(
            update(DomainMapping).where(DomainMapping.id == mapping_id).values(**vals)
        )

    async def revoke(self, mapping_id: uuid.UUID) -> None:
        await self._session.execute(
            update(DomainMapping)
            .where(DomainMapping.id == mapping_id)
            .values(revoked_at=_utcnow())
        )


class ThemeAssetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, **kwargs) -> ThemeAsset:
        obj = ThemeAsset(**kwargs)
        self._session.add(obj)
        await self._session.flush()
        return obj

    async def get(self, asset_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[ThemeAsset]:
        result = await self._session.execute(
            select(ThemeAsset).where(
                ThemeAsset.id == asset_id,
                ThemeAsset.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_tenant(self, tenant_id: uuid.UUID) -> list[ThemeAsset]:
        result = await self._session.execute(
            select(ThemeAsset).where(ThemeAsset.tenant_id == tenant_id)
        )
        return list(result.scalars().all())


class EmailSenderDomainRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, **kwargs) -> EmailSenderDomain:
        obj = EmailSenderDomain(**kwargs)
        self._session.add(obj)
        await self._session.flush()
        return obj

    async def get(self, domain_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[EmailSenderDomain]:
        result = await self._session.execute(
            select(EmailSenderDomain).where(
                EmailSenderDomain.id == domain_id,
                EmailSenderDomain.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_tenant_domain(
        self, tenant_id: uuid.UUID, domain: str
    ) -> Optional[EmailSenderDomain]:
        result = await self._session.execute(
            select(EmailSenderDomain).where(
                EmailSenderDomain.tenant_id == tenant_id,
                EmailSenderDomain.domain == domain,
            )
        )
        return result.scalar_one_or_none()

    async def list_verified(self, tenant_id: Optional[uuid.UUID] = None) -> list[EmailSenderDomain]:
        """If tenant_id is None, return all verified domains."""
        stmt = select(EmailSenderDomain).where(
            EmailSenderDomain.verification_status == EmailSenderStatus.verified
        )
        if tenant_id is not None:
            stmt = stmt.where(EmailSenderDomain.tenant_id == tenant_id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def update_status(
        self,
        domain_id: uuid.UUID,
        status: EmailSenderStatus,
        **kwargs,
    ) -> None:
        vals = {"verification_status": status, **kwargs}
        await self._session.execute(
            update(EmailSenderDomain)
            .where(EmailSenderDomain.id == domain_id)
            .values(**vals)
        )


class BulkImportJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, **kwargs) -> BulkImportJob:
        obj = BulkImportJob(**kwargs)
        self._session.add(obj)
        await self._session.flush()
        return obj

    async def get(self, job_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[BulkImportJob]:
        result = await self._session.execute(
            select(BulkImportJob).where(
                BulkImportJob.id == job_id,
                BulkImportJob.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_tenant(self, tenant_id: uuid.UUID) -> list[BulkImportJob]:
        result = await self._session.execute(
            select(BulkImportJob).where(BulkImportJob.tenant_id == tenant_id)
        )
        return list(result.scalars().all())

    async def update_status(
        self,
        job_id: uuid.UUID,
        status: BulkImportStatus,
        **kwargs,
    ) -> None:
        vals = {"status": status, **kwargs}
        await self._session.execute(
            update(BulkImportJob).where(BulkImportJob.id == job_id).values(**vals)
        )


class BrandingLeakReportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, **kwargs) -> BrandingLeakReport:
        obj = BrandingLeakReport(**kwargs)
        self._session.add(obj)
        await self._session.flush()
        return obj

    async def list_recent(self, limit: int = 50) -> list[BrandingLeakReport]:
        result = await self._session.execute(
            select(BrandingLeakReport)
            .order_by(BrandingLeakReport.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
