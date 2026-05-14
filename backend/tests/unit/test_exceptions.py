"""Unit tests for app.core.exceptions."""

import pytest
from http import HTTPStatus

from app.core.exceptions import (
    AuthenticationError,
    BusinessAlreadyExistsError,
    BusinessNotFoundError,
    BusinessSuspendedError,
    CitedByError,
    ConflictError,
    DecryptionError,
    EncryptionError,
    ExternalServiceError,
    LLMContentPolicyError,
    LLMError,
    LLMProviderUnavailableError,
    NotFoundError,
    PermissionDeniedError,
    ProxyGatewayError,
    RateLimitError,
    TenantContextMissingError,
    TenantNotFoundError,
    TenantSuspendedError,
    ValidationError,
    WorkflowAlreadyRunningError,
    WorkflowError,
)


class TestCitedByError:
    def test_base_attributes(self):
        err = CitedByError("something broke")
        assert str(err) == "something broke"
        assert err.message == "something broke"
        assert err.detail is None
        assert err.http_status == HTTPStatus.INTERNAL_SERVER_ERROR
        assert err.error_code == "internal_error"

    def test_with_detail(self):
        err = CitedByError("oops", detail={"field": "x"})
        assert err.detail == {"field": "x"}

    def test_to_dict_without_detail(self):
        err = CitedByError("base error")
        d = err.to_dict()
        assert d == {"error": "internal_error", "message": "base error"}
        assert "detail" not in d

    def test_to_dict_with_detail(self):
        err = CitedByError("base error", detail={"k": "v"})
        d = err.to_dict()
        assert d["detail"] == {"k": "v"}

    def test_is_exception(self):
        with pytest.raises(CitedByError):
            raise CitedByError("test")


class TestClientErrors:
    @pytest.mark.parametrize(
        "cls, expected_status, expected_code",
        [
            (ValidationError, HTTPStatus.UNPROCESSABLE_ENTITY, "validation_error"),
            (NotFoundError, HTTPStatus.NOT_FOUND, "not_found"),
            (ConflictError, HTTPStatus.CONFLICT, "conflict"),
            (AuthenticationError, HTTPStatus.UNAUTHORIZED, "authentication_error"),
            (PermissionDeniedError, HTTPStatus.FORBIDDEN, "permission_denied"),
        ],
    )
    def test_status_and_code(self, cls, expected_status, expected_code):
        err = cls("msg")
        assert err.http_status == expected_status
        assert err.error_code == expected_code

    def test_rate_limit_default(self):
        err = RateLimitError()
        assert err.http_status == HTTPStatus.TOO_MANY_REQUESTS
        assert err.error_code == "rate_limit_exceeded"
        assert err.retry_after is None
        assert err.detail is None

    def test_rate_limit_with_retry_after(self):
        err = RateLimitError("slow down", retry_after=30)
        assert err.retry_after == 30
        assert err.detail == {"retry_after": 30}


class TestTenancyErrors:
    def test_tenant_context_missing(self):
        err = TenantContextMissingError("no tenant")
        assert err.http_status == HTTPStatus.INTERNAL_SERVER_ERROR
        assert err.error_code == "tenant_context_missing"
        assert isinstance(err, CitedByError)

    def test_tenant_not_found_is_not_found(self):
        err = TenantNotFoundError("t1 not found")
        assert err.http_status == HTTPStatus.NOT_FOUND
        assert isinstance(err, NotFoundError)

    def test_tenant_suspended_is_permission_denied(self):
        err = TenantSuspendedError("suspended")
        assert err.http_status == HTTPStatus.FORBIDDEN
        assert isinstance(err, PermissionDeniedError)


class TestBusinessErrors:
    def test_business_not_found(self):
        err = BusinessNotFoundError("biz gone")
        assert isinstance(err, NotFoundError)
        assert err.error_code == "business_not_found"

    def test_business_already_exists(self):
        err = BusinessAlreadyExistsError("dup")
        assert isinstance(err, ConflictError)
        assert err.error_code == "business_already_exists"

    def test_business_suspended(self):
        err = BusinessSuspendedError("suspended")
        assert isinstance(err, PermissionDeniedError)


class TestEncryptionErrors:
    def test_encryption_error(self):
        err = EncryptionError("bad key")
        assert isinstance(err, CitedByError)
        assert err.error_code == "encryption_error"

    def test_decryption_error(self):
        err = DecryptionError("tampered")
        assert isinstance(err, CitedByError)
        assert err.error_code == "decryption_error"


class TestLLMErrors:
    def test_llm_error_hierarchy(self):
        err = LLMError("llm fail")
        assert isinstance(err, CitedByError)

    def test_llm_provider_unavailable(self):
        err = LLMProviderUnavailableError("anthropic down")
        assert isinstance(err, LLMError)

    def test_llm_content_policy(self):
        err = LLMContentPolicyError("policy block")
        assert err.http_status == HTTPStatus.UNPROCESSABLE_ENTITY
        assert isinstance(err, LLMError)


class TestExternalErrors:
    def test_external_service_error(self):
        err = ExternalServiceError("ext fail")
        assert isinstance(err, CitedByError)

    def test_proxy_gateway_error(self):
        err = ProxyGatewayError("proxy down")
        assert isinstance(err, ExternalServiceError)


class TestWorkflowErrors:
    def test_workflow_error(self):
        err = WorkflowError("wf fail")
        assert isinstance(err, CitedByError)

    def test_workflow_already_running(self):
        err = WorkflowAlreadyRunningError("already running")
        assert err.http_status == HTTPStatus.CONFLICT
        assert isinstance(err, WorkflowError)
