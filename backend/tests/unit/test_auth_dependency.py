"""Unit tests for FastAPI auth dependency layer."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.dependencies.auth import (
    TenantContext,
    TokenPayload,
    _decode_jwt,
    _resolve_tenant_from_host,
)
from app.core.exceptions import AuthenticationError, PermissionDeniedError, TenantNotFoundError
from app.modules.identity.models import Membership, TenantType, UserRole


def _make_membership(**kw) -> Membership:
    defaults = dict(
        user_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        role=UserRole.agency_admin,
    )
    defaults.update(kw)
    return Membership(**defaults)


# ── _decode_jwt ───────────────────────────────────────────────────────────────


class TestDecodeJwt:
    def _make_token(self, payload: dict, secret: str = "a" * 32, algorithm: str = "HS256") -> str:
        import time
        from jose import jwt

        payload.setdefault("exp", int(time.time()) + 3600)
        return jwt.encode(payload, secret, algorithm=algorithm)

    def test_valid_token(self):
        secret = "a" * 32
        token = self._make_token({"sub": "auth0|123", "is_platform_admin": False}, secret)
        payload = _decode_jwt(token, secret, "HS256")
        assert payload.sub == "auth0|123"
        assert payload.is_platform_admin is False

    def test_invalid_token_raises_auth_error(self):
        with pytest.raises(AuthenticationError):
            _decode_jwt("bad.token.here", "secret", "HS256")

    def test_wrong_secret_raises_auth_error(self):
        token = self._make_token({"sub": "auth0|xyz"}, "correct_secret" * 3)
        with pytest.raises(AuthenticationError):
            _decode_jwt(token, "wrong_secret" * 3, "HS256")

    def test_payload_with_tenant_id(self):
        tid = str(uuid.uuid4())
        secret = "s" * 32
        token = self._make_token({"sub": "auth0|abc", "tenant_id": tid}, secret)
        payload = _decode_jwt(token, secret, "HS256")
        assert payload.tenant_id == tid

    def test_missing_exp_raises_auth_error(self):
        from jose import jwt

        secret = "a" * 32
        token = jwt.encode({"sub": "auth0|123"}, secret, algorithm="HS256")
        with pytest.raises(AuthenticationError):
            _decode_jwt(token, secret, "HS256")

    def test_expired_token_raises_auth_error(self):
        import time
        from jose import jwt

        secret = "a" * 32
        token = jwt.encode({"sub": "auth0|123", "exp": int(time.time()) - 10}, secret, algorithm="HS256")
        with pytest.raises(AuthenticationError):
            _decode_jwt(token, secret, "HS256")

    def test_audience_mismatch_raises_auth_error(self):
        secret = "a" * 32
        token = self._make_token({"sub": "auth0|123", "aud": "https://api.correct.com"}, secret)
        with pytest.raises(AuthenticationError):
            _decode_jwt(token, secret, "HS256", audience="https://api.other.com")

    def test_audience_matched(self):
        secret = "a" * 32
        aud = "https://api.citedby.app"
        token = self._make_token({"sub": "auth0|123", "aud": aud}, secret)
        payload = _decode_jwt(token, secret, "HS256", audience=aud)
        assert payload.sub == "auth0|123"

    def test_issuer_mismatch_raises_auth_error(self):
        secret = "a" * 32
        token = self._make_token({"sub": "auth0|123", "iss": "https://wrong.auth0.com/"}, secret)
        with pytest.raises(AuthenticationError):
            _decode_jwt(token, secret, "HS256", issuer="https://correct.auth0.com/")

    def test_issuer_matched(self):
        secret = "a" * 32
        iss = "https://citedby.auth0.com/"
        token = self._make_token({"sub": "auth0|123", "iss": iss}, secret)
        payload = _decode_jwt(token, secret, "HS256", issuer=iss)
        assert payload.sub == "auth0|123"


# ── _resolve_tenant_from_host ─────────────────────────────────────────────────


class TestResolveTenantFromHost:
    @pytest.mark.asyncio
    async def test_valid_subdomain_returns_tenant_id(self):
        from app.modules.identity.models import Tenant

        tenant = MagicMock()
        tenant.id = uuid.uuid4()

        tenant_repo = MagicMock()
        tenant_repo.get_by_slug = AsyncMock(return_value=tenant)

        result = await _resolve_tenant_from_host("myagency.citedby.app", tenant_repo)
        assert result == tenant.id
        tenant_repo.get_by_slug.assert_called_once_with("myagency")

    @pytest.mark.asyncio
    async def test_reserved_subdomain_returns_none(self):
        tenant_repo = MagicMock()

        result = await _resolve_tenant_from_host("www.citedby.app", tenant_repo)
        assert result is None
        tenant_repo.get_by_slug.assert_not_called()

    @pytest.mark.asyncio
    async def test_app_subdomain_returns_none(self):
        tenant_repo = MagicMock()

        result = await _resolve_tenant_from_host("app.citedby.app", tenant_repo)
        assert result is None

    @pytest.mark.asyncio
    async def test_missing_tenant_returns_none(self):
        tenant_repo = MagicMock()
        tenant_repo.get_by_slug = AsyncMock(side_effect=TenantNotFoundError("not found"))

        result = await _resolve_tenant_from_host("unknown.citedby.app", tenant_repo)
        assert result is None

    @pytest.mark.asyncio
    async def test_non_citedby_host_returns_none(self):
        tenant_repo = MagicMock()

        result = await _resolve_tenant_from_host("mysite.example.com", tenant_repo)
        assert result is None

    @pytest.mark.asyncio
    async def test_dev_domain_works(self):
        tenant = MagicMock()
        tenant.id = uuid.uuid4()
        tenant_repo = MagicMock()
        tenant_repo.get_by_slug = AsyncMock(return_value=tenant)

        result = await _resolve_tenant_from_host("myagency.citedby.dev", tenant_repo)
        assert result == tenant.id

    @pytest.mark.asyncio
    async def test_mixed_case_host_is_lowercased(self):
        tenant = MagicMock()
        tenant.id = uuid.uuid4()
        tenant_repo = MagicMock()
        tenant_repo.get_by_slug = AsyncMock(return_value=tenant)

        result = await _resolve_tenant_from_host("MYAGENCY.citedby.app", tenant_repo)
        assert result == tenant.id
        tenant_repo.get_by_slug.assert_called_once_with("myagency")


# ── TenantContext ─────────────────────────────────────────────────────────────


class TestTenantContext:
    def _make_ctx(self, **kw) -> TenantContext:
        tid = uuid.uuid4()
        uid = uuid.uuid4()
        defaults = dict(
            user_id=uid,
            auth_provider_id="auth0|test",
            tenant_id=tid,
            is_platform_admin=False,
            memberships=[],
        )
        defaults.update(kw)
        return TenantContext(**defaults)

    def test_assert_tenant_returns_tenant_id(self):
        tid = uuid.uuid4()
        ctx = self._make_ctx(tenant_id=tid)
        assert ctx.assert_tenant() == tid

    def test_assert_tenant_raises_when_none(self):
        ctx = self._make_ctx(tenant_id=None)
        with pytest.raises(PermissionDeniedError):
            ctx.assert_tenant()

    def test_has_role_platform_admin_returns_true_for_any_role(self):
        ctx = self._make_ctx(is_platform_admin=True)
        assert ctx.has_role(UserRole.agency_admin) is True
        assert ctx.has_role(UserRole.business_member) is True

    def test_has_role_matching_membership(self):
        tid = uuid.uuid4()
        uid = uuid.uuid4()
        m = _make_membership(user_id=uid, tenant_id=tid, role=UserRole.agency_admin)
        ctx = TenantContext(
            user_id=uid,
            auth_provider_id="auth0|x",
            tenant_id=tid,
            is_platform_admin=False,
            memberships=[m],
        )
        assert ctx.has_role(UserRole.agency_admin) is True

    def test_has_role_no_matching_membership(self):
        tid = uuid.uuid4()
        uid = uuid.uuid4()
        m = _make_membership(user_id=uid, tenant_id=tid, role=UserRole.agency_member)
        ctx = TenantContext(
            user_id=uid,
            auth_provider_id="auth0|x",
            tenant_id=tid,
            is_platform_admin=False,
            memberships=[m],
        )
        assert ctx.has_role(UserRole.agency_admin) is False

    def test_assert_role_raises_on_missing_role(self):
        ctx = self._make_ctx(is_platform_admin=False, memberships=[])
        with pytest.raises(PermissionDeniedError):
            ctx.assert_role(UserRole.agency_admin)

    def test_assert_role_passes_for_platform_admin(self):
        ctx = self._make_ctx(is_platform_admin=True)
        ctx.assert_role(UserRole.platform_admin)  # should not raise

    def test_to_request_context_raises_without_tenant(self):
        ctx = self._make_ctx(tenant_id=None)
        with pytest.raises(PermissionDeniedError):
            ctx.to_request_context()

    def test_to_request_context_empty_scope(self):
        ctx = self._make_ctx()
        rctx = ctx.to_request_context()
        assert rctx.tenant_id == ctx.tenant_id
        assert rctx.user_id == ctx.user_id
        assert rctx.business_scope_ids == []

    def test_to_request_context_with_business_scope(self):
        tid = uuid.uuid4()
        uid = uuid.uuid4()
        bid = uuid.uuid4()
        m = _make_membership(user_id=uid, tenant_id=tid, role=UserRole.business_member)
        m.business_scope_ids = [bid]
        ctx = TenantContext(
            user_id=uid,
            auth_provider_id="auth0|x",
            tenant_id=tid,
            is_platform_admin=False,
            memberships=[m],
        )
        rctx = ctx.to_request_context()
        assert bid in rctx.business_scope_ids
