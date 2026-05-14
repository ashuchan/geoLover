from functools import lru_cache
from typing import Literal

from pydantic import Field, FieldValidationInfo, PostgresDsn, RedisDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ALLOWED_JWT_ALGORITHMS = Literal["HS256", "HS384", "HS512", "RS256", "ES256"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Environment
    environment: Literal["development", "staging", "production"] = "development"
    debug: bool = False
    log_level: str = "INFO"

    # Application
    app_name: str = "CitedBy"
    app_version: str = "0.1.0"
    secret_key: SecretStr = Field(..., description="JWT signing secret; min 32 chars")
    # Empty list = no restriction (dev only); production must provide explicit allowlist.
    allowed_hosts: list[str] = []

    # Database (main pool — citedby_app role)
    database_url: PostgresDsn = Field(
        ...,
        description="asyncpg DSN; e.g. postgresql+asyncpg://citedby_app:pw@host/citedby",
    )
    db_pool_min_size: int = 5
    db_pool_max_size: int = 20
    db_pool_max_inactive_connection_lifetime: float = 300.0

    # Database (public audit pool — citedby_public_audit role)
    public_audit_database_url: PostgresDsn | None = None
    public_audit_pool_min_size: int = 2
    public_audit_pool_max_size: int = 5

    # Redis
    redis_url: RedisDsn = Field(..., description="redis://host:6379/0")
    redis_max_connections: int = 20

    # JWT — constrained to known-secure algorithms; "none" is explicitly excluded
    jwt_algorithm: _ALLOWED_JWT_ALGORITHMS = "HS256"  # type: ignore[valid-type]
    jwt_access_token_expire_minutes: int = 60
    jwt_refresh_token_expire_days: int = 30

    # Encryption (KMS envelope)
    encryption_master_key: SecretStr = Field(
        ...,
        description="32-byte base64-encoded AES-256 master key for DEK wrapping",
    )

    # LLM
    anthropic_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    llm_default_provider: Literal["anthropic", "openai", "static"] = "anthropic"
    llm_request_timeout_seconds: int = 60

    # Temporal (workflow orchestration)
    temporal_host: str = "localhost:7233"
    temporal_namespace: str = "citedby"

    # Proxy / scraping
    proxy_gateway_url: str | None = None
    proxy_api_key: SecretStr | None = None

    # White-label branding leak guard
    whitelabel_forbidden_strings: list[str] = ["citedby", "CitedBy"]

    # Free-audit public endpoint rate limit (per IP per hour)
    free_audit_rate_limit: int = 5

    @field_validator("secret_key", mode="before")
    @classmethod
    def _secret_key_min_length(cls, v: object) -> object:
        raw = v.get_secret_value() if isinstance(v, SecretStr) else str(v)
        if len(raw) < 32:
            raise ValueError("secret_key must be at least 32 characters")
        return v

    @field_validator("allowed_hosts", mode="after")
    @classmethod
    def _no_wildcard_in_production(cls, v: list[str], info: FieldValidationInfo) -> list[str]:
        env = info.data.get("environment", "development")
        if env == "production" and "*" in v:
            raise ValueError("allowed_hosts must not contain '*' in production environments")
        return v

    @field_validator("environment", mode="before")
    @classmethod
    def _normalise_env(cls, v: str) -> str:
        return v.lower()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
