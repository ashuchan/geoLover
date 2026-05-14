"""Typed exception hierarchy for the CitedBy platform.

All domain and infrastructure exceptions derive from CitedByError so callers can
catch the root type while still branching on concrete subtypes.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any


class CitedByError(Exception):
    """Root exception.  All application exceptions inherit from this."""

    http_status: int = HTTPStatus.INTERNAL_SERVER_ERROR
    error_code: str = "internal_error"

    def __init__(self, message: str, *, detail: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "error": self.error_code,
            "message": self.message,
        }
        if self.detail is not None:
            payload["detail"] = self.detail
        return payload


# ── 4xx client errors ──────────────────────────────────────────────────────────


class ValidationError(CitedByError):
    http_status = HTTPStatus.UNPROCESSABLE_ENTITY
    error_code = "validation_error"


class NotFoundError(CitedByError):
    http_status = HTTPStatus.NOT_FOUND
    error_code = "not_found"


class ConflictError(CitedByError):
    http_status = HTTPStatus.CONFLICT
    error_code = "conflict"


class AuthenticationError(CitedByError):
    http_status = HTTPStatus.UNAUTHORIZED
    error_code = "authentication_error"


class PermissionDeniedError(CitedByError):
    http_status = HTTPStatus.FORBIDDEN
    error_code = "permission_denied"


class RateLimitError(CitedByError):
    http_status = HTTPStatus.TOO_MANY_REQUESTS
    error_code = "rate_limit_exceeded"

    def __init__(self, message: str = "Rate limit exceeded", *, retry_after: int | None = None) -> None:
        super().__init__(message, detail={"retry_after": retry_after} if retry_after else None)
        self.retry_after = retry_after


# ── Tenancy errors ─────────────────────────────────────────────────────────────


class TenantContextMissingError(CitedByError):
    """Raised when RLS session variable is not set before a DB query."""

    http_status = HTTPStatus.INTERNAL_SERVER_ERROR
    error_code = "tenant_context_missing"


class TenantNotFoundError(NotFoundError):
    error_code = "tenant_not_found"


class TenantSuspendedError(PermissionDeniedError):
    error_code = "tenant_suspended"


# ── Business profile errors ────────────────────────────────────────────────────


class BusinessNotFoundError(NotFoundError):
    error_code = "business_not_found"


class BusinessAlreadyExistsError(ConflictError):
    error_code = "business_already_exists"


class BusinessSuspendedError(PermissionDeniedError):
    error_code = "business_suspended"


# ── Encryption / security errors ───────────────────────────────────────────────


class EncryptionError(CitedByError):
    error_code = "encryption_error"


class DecryptionError(CitedByError):
    error_code = "decryption_error"


# ── LLM / AI errors ────────────────────────────────────────────────────────────


class LLMError(CitedByError):
    error_code = "llm_error"


class LLMProviderUnavailableError(LLMError):
    error_code = "llm_provider_unavailable"


class LLMContentPolicyError(LLMError):
    http_status = HTTPStatus.UNPROCESSABLE_ENTITY
    error_code = "llm_content_policy"


# ── External service errors ────────────────────────────────────────────────────


class ExternalServiceError(CitedByError):
    error_code = "external_service_error"


class ProxyGatewayError(ExternalServiceError):
    error_code = "proxy_gateway_error"


# ── Workflow / Temporal errors ─────────────────────────────────────────────────


class WorkflowError(CitedByError):
    error_code = "workflow_error"


class WorkflowAlreadyRunningError(WorkflowError):
    http_status = HTTPStatus.CONFLICT
    error_code = "workflow_already_running"
