"""Unit tests for app.core.config."""

from __future__ import annotations

import base64
import os

import pytest
from pydantic import ValidationError as PydanticValidationError


def _make_settings_kwargs(overrides: dict | None = None) -> dict:
    """Return a dict with lowercase field names suitable for Settings(**kwargs)."""
    base = {
        "secret_key": "a" * 32,
        "database_url": "postgresql+asyncpg://user:pw@localhost/db",
        "redis_url": "redis://localhost:6379/0",
        "encryption_master_key": base64.b64encode(os.urandom(32)).decode(),
    }
    if overrides:
        base.update(overrides)
    return base


class TestSettings:
    def test_valid_settings_loads(self):
        from app.core.config import Settings

        s = Settings(**_make_settings_kwargs())
        assert s.app_name == "CitedBy"
        assert s.environment == "development"

    def test_secret_key_too_short_raises(self):
        from app.core.config import Settings

        with pytest.raises(PydanticValidationError, match="32 characters"):
            Settings(**_make_settings_kwargs({"secret_key": "short"}))

    def test_environment_normalised_to_lowercase(self):
        from app.core.config import Settings

        s = Settings(**_make_settings_kwargs({"environment": "STAGING"}))
        assert s.environment == "staging"

    def test_invalid_environment_raises(self):
        from app.core.config import Settings

        with pytest.raises(PydanticValidationError):
            Settings(**_make_settings_kwargs({"environment": "invalid_env"}))

    def test_default_values(self):
        from app.core.config import Settings

        s = Settings(**_make_settings_kwargs())
        assert s.db_pool_min_size == 5
        assert s.db_pool_max_size == 20
        assert s.jwt_algorithm == "HS256"
        assert s.llm_default_provider == "anthropic"
        assert s.free_audit_rate_limit == 5

    def test_optional_fields_default_none(self):
        from app.core.config import Settings

        s = Settings(**_make_settings_kwargs())
        assert s.anthropic_api_key is None
        assert s.openai_api_key is None
        assert s.public_audit_database_url is None

    def test_whitelabel_forbidden_strings_default(self):
        from app.core.config import Settings

        s = Settings(**_make_settings_kwargs())
        assert "citedby" in s.whitelabel_forbidden_strings
        assert "CitedBy" in s.whitelabel_forbidden_strings

    def test_missing_required_fields_raises(self):
        from app.core.config import Settings

        with pytest.raises(PydanticValidationError):
            Settings(secret_key="a" * 32)  # type: ignore[call-arg]

    def test_debug_flag_default_false(self):
        from app.core.config import Settings

        s = Settings(**_make_settings_kwargs())
        assert s.debug is False

    def test_get_settings_is_cached(self):
        """get_settings() should have lru_cache wrapper."""
        from app.core.config import get_settings

        assert callable(get_settings)
        assert hasattr(get_settings, "cache_info")

    def test_pool_sizes(self):
        from app.core.config import Settings

        s = Settings(**_make_settings_kwargs({"db_pool_min_size": 3, "db_pool_max_size": 15}))
        assert s.db_pool_min_size == 3
        assert s.db_pool_max_size == 15

    def test_jwt_expire_defaults(self):
        from app.core.config import Settings

        s = Settings(**_make_settings_kwargs())
        assert s.jwt_access_token_expire_minutes == 60
        assert s.jwt_refresh_token_expire_days == 30

    def test_jwt_algorithm_default(self):
        from app.core.config import Settings

        s = Settings(**_make_settings_kwargs())
        assert s.jwt_algorithm == "HS256"

    def test_allowed_hosts_default_empty(self):
        from app.core.config import Settings

        s = Settings(**_make_settings_kwargs())
        assert s.allowed_hosts == []

    def test_wildcard_allowed_hosts_in_production_raises(self):
        from app.core.config import Settings
        from pydantic import ValidationError as PydanticValidationError

        with pytest.raises(PydanticValidationError, match="must not contain"):
            Settings(**_make_settings_kwargs({"environment": "production", "allowed_hosts": ["*"]}))

    def test_wildcard_allowed_hosts_in_development_ok(self):
        from app.core.config import Settings

        s = Settings(**_make_settings_kwargs({"environment": "development", "allowed_hosts": ["*"]}))
        assert "*" in s.allowed_hosts

    def test_empty_allowed_hosts_in_production_raises(self):
        from app.core.config import Settings

        with pytest.raises(PydanticValidationError, match="non-empty"):
            Settings(**_make_settings_kwargs({"environment": "production", "allowed_hosts": []}))

    def test_valid_production_settings(self):
        from app.core.config import Settings

        s = Settings(
            **_make_settings_kwargs({
                "environment": "production",
                "allowed_hosts": ["api.citedby.app", "*.citedby.app"],
            })
        )
        assert s.environment == "production"
        assert len(s.allowed_hosts) == 2

    def test_jwt_audience_and_issuer_default_none(self):
        from app.core.config import Settings

        s = Settings(**_make_settings_kwargs())
        assert s.jwt_audience is None
        assert s.jwt_issuer is None

    def test_jwt_audience_and_issuer_can_be_set(self):
        from app.core.config import Settings

        s = Settings(**_make_settings_kwargs({
            "jwt_audience": "https://api.citedby.app",
            "jwt_issuer": "https://citedby.auth0.com/",
        }))
        assert s.jwt_audience == "https://api.citedby.app"
        assert s.jwt_issuer == "https://citedby.auth0.com/"
