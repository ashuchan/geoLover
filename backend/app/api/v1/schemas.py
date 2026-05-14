"""Pydantic v2 request/response schemas for Phase 1 API."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_URL_RE = re.compile(r"^https?://[^\s]{1,2000}$", re.IGNORECASE)

from app.modules.audit.models import AuditStatus, AuditTrigger
from app.modules.business_profile.models import (
    AliasType,
    BusinessSource,
    BusinessStatus,
    CompetitorStatus,
    KeywordSource,
)
from app.modules.identity.models import TenantType, UserRole


# ── Tenant schemas ─────────────────────────────────────────────────────────────


class TenantCreate(BaseModel):
    type: TenantType
    display_name: str = Field(..., min_length=1, max_length=200)
    slug: str = Field(..., min_length=3, max_length=40, pattern=r"^[a-z0-9-]+$")
    primary_country: str = Field(default="IN", min_length=2, max_length=2)


class TenantUpdate(BaseModel):
    display_name: Optional[str] = Field(None, min_length=1, max_length=200)
    primary_country: Optional[str] = Field(None, min_length=2, max_length=2)


class TenantResponse(BaseModel):
    id: uuid.UUID
    type: TenantType
    display_name: str
    slug: str
    primary_country: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── User / Auth schemas ───────────────────────────────────────────────────────


class MembershipResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    tenant_id: Optional[uuid.UUID]
    role: UserRole
    granted_at: datetime

    model_config = {"from_attributes": True}


class MeResponse(BaseModel):
    user_id: uuid.UUID
    display_name: str
    email_normalized: str
    locale: str
    memberships: list[MembershipResponse]

    model_config = {"from_attributes": True}


# ── Membership management ─────────────────────────────────────────────────────


class MemberInvite(BaseModel):
    email: str = Field(..., description="Email of the user to invite")
    role: UserRole
    business_scope_ids: list[uuid.UUID] = []


class MemberRevokeResponse(BaseModel):
    membership_id: uuid.UUID
    revoked: bool = True


# ── Business schemas ───────────────────────────────────────────────────────────


class BusinessCreate(BaseModel):
    canonical_name: str = Field(..., min_length=2, max_length=200)
    category_id: uuid.UUID
    subcategory_ids: list[uuid.UUID] = []
    description: Optional[str] = Field(None, max_length=2000)
    website_url: Optional[str] = Field(None, max_length=2048)
    primary_email: Optional[str] = Field(None, max_length=254)
    primary_phone: Optional[str] = Field(None, max_length=20)
    locale: str = "en-IN"
    source: BusinessSource = BusinessSource.self_signup

    @field_validator("primary_email")
    @classmethod
    def _validate_email(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _EMAIL_RE.match(v):
            raise ValueError("Invalid email format")
        return v

    @field_validator("website_url")
    @classmethod
    def _validate_url(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _URL_RE.match(v):
            raise ValueError("website_url must start with http:// or https://")
        return v


class BusinessUpdate(BaseModel):
    canonical_name: Optional[str] = Field(None, min_length=2, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    website_url: Optional[str] = Field(None, max_length=2048)
    primary_email: Optional[str] = Field(None, max_length=254)
    primary_phone: Optional[str] = Field(None, max_length=20)
    status: Optional[BusinessStatus] = None

    @field_validator("primary_email")
    @classmethod
    def _validate_email(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _EMAIL_RE.match(v):
            raise ValueError("Invalid email format")
        return v

    @field_validator("website_url")
    @classmethod
    def _validate_url(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _URL_RE.match(v):
            raise ValueError("website_url must start with http:// or https://")
        return v


class BusinessResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    canonical_name: str
    name_normalized: str
    category_id: uuid.UUID
    status: BusinessStatus
    source: BusinessSource
    description: Optional[str]
    website_url: Optional[str]
    identity_uniqueness_score: Optional[float]
    locale: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Location schemas ───────────────────────────────────────────────────────────


class LocationCreate(BaseModel):
    city: str = Field(..., min_length=1, max_length=200)
    locality: Optional[str] = Field(None, max_length=200)
    label: Optional[str] = Field(None, max_length=200)
    address_line_1: Optional[str] = Field(None, max_length=500)
    address_line_2: Optional[str] = Field(None, max_length=500)
    postal_code: Optional[str] = Field(None, max_length=20)
    state: Optional[str] = Field(None, max_length=100)
    country: str = "IN"
    is_primary: bool = False


class LocationResponse(BaseModel):
    id: uuid.UUID
    business_id: uuid.UUID
    city: str
    locality: Optional[str]
    label: Optional[str]
    is_primary: bool
    country: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Alias schemas ──────────────────────────────────────────────────────────────


class AliasCreate(BaseModel):
    alias_text: str = Field(..., min_length=1, max_length=200)
    alias_type: AliasType
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class AliasResponse(BaseModel):
    id: uuid.UUID
    business_id: uuid.UUID
    alias_text: str
    alias_text_normalized: str
    alias_type: AliasType
    confidence: float
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Keyword schemas ────────────────────────────────────────────────────────────


class KeywordsAdd(BaseModel):
    keywords: list[str] = Field(..., min_length=1, max_length=50)

    @field_validator("keywords")
    @classmethod
    def _non_empty(cls, v: list[str]) -> list[str]:
        cleaned = [kw.strip() for kw in v if kw.strip()]
        if not cleaned:
            raise ValueError("At least one non-empty keyword required")
        for kw in cleaned:
            if len(kw) > 200:
                raise ValueError("Each keyword must be 200 characters or fewer")
        return cleaned


class KeywordResponse(BaseModel):
    id: uuid.UUID
    business_id: uuid.UUID
    keyword: str
    keyword_normalized: str
    source: KeywordSource
    priority: int
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Category schemas ──────────────────────────────────────────────────────────


class CategoryResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    parent_category_id: Optional[uuid.UUID]
    default_keyword_suggestions: list[str]

    model_config = {"from_attributes": True}


# ── Free audit schemas ─────────────────────────────────────────────────────────


class FreeAuditStartRequest(BaseModel):
    business_name: str = Field(..., min_length=2, max_length=200)
    city: str = Field(..., min_length=1)
    email: str = Field(..., max_length=254)
    category_id: uuid.UUID
    website_url: Optional[str] = Field(None, max_length=2048)
    locality: Optional[str] = None

    @field_validator("email")
    @classmethod
    def _validate_email(cls, v: str) -> str:
        if not _EMAIL_RE.match(v):
            raise ValueError("Invalid email format")
        return v

    @field_validator("website_url")
    @classmethod
    def _validate_url(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _URL_RE.match(v):
            raise ValueError("website_url must start with http:// or https://")
        return v


class FreeAuditStartResponse(BaseModel):
    audit_token: str
    business_id: uuid.UUID
    expires_at: datetime


class FreeAuditStatusResponse(BaseModel):
    token: str
    business_id: uuid.UUID
    status: str  # "pending" | "in_progress" | "complete" (Phase 2 populates)
    expires_at: datetime
    claimed: bool


# ── Audit schemas ──────────────────────────────────────────────────────────────


class AuditRunCreate(BaseModel):
    business_id: uuid.UUID
    trigger: AuditTrigger = AuditTrigger.manual


class AuditRunResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    business_id: uuid.UUID
    trigger: AuditTrigger
    status: AuditStatus
    ai_visibility_score: Optional[float]
    completeness_pct: Optional[float]
    queries_total: int
    queries_successful: int
    queries_cited: int
    queries_negative: int
    algorithm_version: str
    workflow_run_id: Optional[str]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Error schemas ─────────────────────────────────────────────────────────────


class ErrorResponse(BaseModel):
    error: str
    message: str
    detail: Optional[object] = None
