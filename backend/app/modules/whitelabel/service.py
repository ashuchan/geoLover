"""WhitelabelService, DomainService, BulkImportService for Phase 7."""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.whitelabel.models import (
    BrandingLeakReport,
    BulkImportJob,
    BulkImportStatus,
    DomainMapping,
    DomainType,
    DomainVerificationStatus,
    ThemeAsset,
    WhitelabelConfig,
)
from app.modules.whitelabel.repository import (
    BrandingLeakReportRepository,
    BulkImportJobRepository,
    DomainMappingRepository,
    ThemeAssetRepository,
    WhitelabelConfigRepository,
)
from app.modules.whitelabel.sanitizer import (
    check_color_contrast,
    scan_for_branding_leak,
    validate_font_family,
    validate_hex_color,
    parse_csv_row,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Domain Events ──────────────────────────────────────────────────────────────


@dataclass
class DomainVerified:
    name: str = "DomainVerified"
    mapping_id: uuid.UUID = None  # type: ignore[assignment]
    tenant_id: uuid.UUID = None  # type: ignore[assignment]
    domain: str = ""


@dataclass
class DomainRevoked:
    name: str = "DomainRevoked"
    mapping_id: uuid.UUID = None  # type: ignore[assignment]
    tenant_id: uuid.UUID = None  # type: ignore[assignment]


@dataclass
class WhitelabelConfigUpdated:
    name: str = "WhitelabelConfigUpdated"
    tenant_id: uuid.UUID = None  # type: ignore[assignment]


@dataclass
class BulkImportCompleted:
    name: str = "BulkImportCompleted"
    job_id: uuid.UUID = None  # type: ignore[assignment]
    tenant_id: uuid.UUID = None  # type: ignore[assignment]
    succeeded: int = 0
    failed: int = 0


# ── Services ───────────────────────────────────────────────────────────────────

_ALLOWED_CONTENT_TYPES = frozenset([
    "image/png",
    "image/svg+xml",
    "image/jpeg",
    "image/webp",
])


class WhitelabelService:
    """Manages whitelabel config, theme assets, and branding leak scans."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = WhitelabelConfigRepository(session)
        self._asset_repo = ThemeAssetRepository(session)
        self._leak_repo = BrandingLeakReportRepository(session)
        self._pending_events: list = []

    @property
    def pending_events(self) -> list:
        return list(self._pending_events)

    async def get_or_create_config(self, tenant_id: uuid.UUID) -> WhitelabelConfig:
        """Get existing config or create with defaults."""
        config = await self._repo.get_by_tenant(tenant_id)
        if config is None:
            config = await self._repo.create(
                tenant_id=tenant_id,
                updated_at=_utcnow(),
            )
        return config

    async def update_config(self, *, tenant_id: uuid.UUID, **kwargs) -> WhitelabelConfig:
        """Validate and update whitelabel config."""
        if "primary_color_hex" in kwargs and kwargs["primary_color_hex"] is not None:
            if not validate_hex_color(kwargs["primary_color_hex"]):
                raise ValueError(f"Invalid hex color: {kwargs['primary_color_hex']}")
        if "secondary_color_hex" in kwargs and kwargs["secondary_color_hex"] is not None:
            if not validate_hex_color(kwargs["secondary_color_hex"]):
                raise ValueError(f"Invalid hex color: {kwargs['secondary_color_hex']}")
        if "font_family" in kwargs and kwargs["font_family"] is not None:
            if not validate_font_family(kwargs["font_family"]):
                raise ValueError(f"Invalid font family: {kwargs['font_family']}")

        # Strip None values so we don't overwrite with NULL
        update_kwargs = {k: v for k, v in kwargs.items() if v is not None}
        await self._repo.update(tenant_id, **update_kwargs)
        self._pending_events.append(WhitelabelConfigUpdated(tenant_id=tenant_id))
        config = await self._repo.get_by_tenant(tenant_id)
        return config  # type: ignore[return-value]

    def get_contrast_warnings(
        self, *, primary_color_hex: str, secondary_color_hex: str
    ) -> list[str]:
        """Return WCAG contrast warnings for the given colors."""
        return check_color_contrast(primary_color_hex, secondary_color_hex)

    async def register_theme_asset(
        self,
        *,
        tenant_id: uuid.UUID,
        asset_kind: str,
        content_type: str,
        gcs_object_path: str,
        width_px: Optional[int] = None,
        height_px: Optional[int] = None,
        safe_for_email: bool = False,
        uploaded_by_user_id: Optional[uuid.UUID] = None,
    ) -> ThemeAsset:
        """Register a new theme asset after upload."""
        if content_type not in _ALLOWED_CONTENT_TYPES:
            raise ValueError(
                f"Invalid content type: {content_type}. "
                f"Allowed: {sorted(_ALLOWED_CONTENT_TYPES)}"
            )
        asset = await self._asset_repo.create(
            tenant_id=tenant_id,
            asset_kind=asset_kind,
            content_type=content_type,
            gcs_object_path=gcs_object_path,
            width_px=width_px,
            height_px=height_px,
            safe_for_email=safe_for_email,
            uploaded_by_user_id=uploaded_by_user_id,
        )
        return asset

    async def scan_for_branding_leaks(
        self,
        *,
        scan_run_id: str,
        scan_target: str,
        content: str,
    ) -> BrandingLeakReport:
        """Scan content for CitedBy branding tokens and persist a report."""
        findings = scan_for_branding_leak(content)
        verdict = "fail" if findings else "clean"
        report = await self._leak_repo.create(
            scan_run_id=scan_run_id,
            scan_target=scan_target,
            findings=findings,
            verdict=verdict,
        )
        return report

    def get_dns_instructions(self, *, domain: str, tenant_id: uuid.UUID) -> dict:
        """Return DNS record instructions for the domain."""
        return {
            "domain": domain,
            "tenant_id": str(tenant_id),
            "instructions": [
                {
                    "type": "CNAME",
                    "name": domain,
                    "value": "portal.citedby.app",
                    "ttl": 300,
                }
            ],
        }


class DomainService:
    """Manages custom domain mappings and verification."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._domain_repo = DomainMappingRepository(session)
        self._pending_events: list = []

    @property
    def pending_events(self) -> list:
        return list(self._pending_events)

    async def add_domain(
        self,
        *,
        tenant_id: uuid.UUID,
        domain: str,
        domain_type: str = "custom",
        verification_method: str = "dns_txt",
    ) -> DomainMapping:
        """Add a domain mapping and generate a verification token."""
        token = secrets.token_urlsafe(32)
        # Platform subdomains are auto-verified
        if domain_type == DomainType.platform_subdomain or domain_type == "platform_subdomain":
            verification_status = DomainVerificationStatus.verified
            verified_at = _utcnow()
        else:
            verification_status = DomainVerificationStatus.pending
            verified_at = None

        mapping = await self._domain_repo.create(
            tenant_id=tenant_id,
            domain=domain,
            domain_type=domain_type,
            verification_method=verification_method,
            verification_token=token,
            verification_status=verification_status,
            verified_at=verified_at,
        )
        return mapping

    async def verify_domain(
        self, *, mapping_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> tuple[bool, str]:
        """Attempt to verify a pending domain mapping."""
        mapping = await self._domain_repo.get(mapping_id, tenant_id)
        if mapping is None:
            return False, "Domain mapping not found"
        if mapping.verification_status == DomainVerificationStatus.verified:
            return True, "already_verified"

        now = _utcnow()
        await self._domain_repo.update_verification(
            mapping_id,
            DomainVerificationStatus.verified,
            verified_at=now,
        )
        self._pending_events.append(
            DomainVerified(
                mapping_id=mapping_id,
                tenant_id=tenant_id,
                domain=mapping.domain,
            )
        )
        return True, "verified"

    async def revoke_domain(
        self, *, mapping_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> None:
        """Revoke a domain mapping."""
        await self._domain_repo.revoke(mapping_id)
        self._pending_events.append(
            DomainRevoked(mapping_id=mapping_id, tenant_id=tenant_id)
        )

    def get_verification_instructions(self, mapping: DomainMapping) -> dict:
        """Return DNS verification instructions for a mapping."""
        return {
            "method": mapping.verification_method,
            "token": mapping.verification_token,
            "dns_record": {
                "type": "TXT",
                "name": f"_citedby-verify.{mapping.domain}",
                "value": f"citedby-verify={mapping.verification_token}",
                "ttl": 300,
            },
        }


class BulkImportService:
    """Manages bulk business CSV import jobs."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._job_repo = BulkImportJobRepository(session)
        self._pending_events: list = []

    @property
    def pending_events(self) -> list:
        return list(self._pending_events)

    async def create_job(
        self,
        *,
        tenant_id: uuid.UUID,
        initiated_by_user_id: uuid.UUID,
        source_object_path: str,
    ) -> BulkImportJob:
        """Create a new bulk import job in queued status."""
        job = await self._job_repo.create(
            tenant_id=tenant_id,
            initiated_by_user_id=initiated_by_user_id,
            source_object_path=source_object_path,
            status=BulkImportStatus.queued,
        )
        return job

    async def process_csv_rows(
        self,
        *,
        job_id: uuid.UUID,
        tenant_id: uuid.UUID,
        rows: list[dict],
    ) -> dict:
        """Process CSV rows and update job status."""
        outcomes = []
        succeeded = 0
        failed = 0
        skipped = 0
        seen_keys: set[str] = set()

        for i, row in enumerate(rows):
            validated, error = parse_csv_row(row, i)
            if error is not None:
                failed += 1
                outcomes.append({"row": i, "status": "failed", "error": error})
                continue

            # Check for duplicate idempotency key
            ikey = validated["idempotency_key"]  # type: ignore[index]
            if ikey in seen_keys:
                skipped += 1
                outcomes.append({"row": i, "status": "skipped", "reason": "duplicate"})
                continue

            seen_keys.add(ikey)
            succeeded += 1
            outcomes.append({"row": i, "status": "succeeded", "data": validated})

        now = _utcnow()
        await self._job_repo.update_status(
            job_id,
            BulkImportStatus.completed,
            total_rows=len(rows),
            succeeded_rows=succeeded,
            failed_rows=failed,
            completed_at=now,
        )
        self._pending_events.append(
            BulkImportCompleted(
                job_id=job_id,
                tenant_id=tenant_id,
                succeeded=succeeded,
                failed=failed,
            )
        )
        return {
            "succeeded": succeeded,
            "failed": failed,
            "skipped": skipped,
            "outcomes": outcomes,
        }

    async def get_job(
        self, *, job_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Optional[BulkImportJob]:
        """Fetch a bulk import job."""
        return await self._job_repo.get(job_id, tenant_id)
