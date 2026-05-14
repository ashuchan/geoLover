"""Publisher adapter protocols and implementations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable


@dataclass
class ChannelDescriptor:
    channel: str
    display_name: str
    requires_oauth: bool


@dataclass
class ConnectionInitiation:
    channel: str
    oauth_url: Optional[str]
    instructions: Optional[str]


@dataclass
class ConnectionResult:
    access_token: str
    refresh_token: str
    expires_at: str  # ISO format
    scope: str
    account_subject: str
    provider: str


@dataclass
class PublishResult:
    success: bool
    external_object_id: Optional[str]
    public_url: Optional[str]
    failure_reason: Optional[str]
    is_retryable: bool


@dataclass
class VerificationOutcome:
    outcome: str  # verified | not_found | error | still_pending
    public_url: Optional[str]


@runtime_checkable
class PublisherAdapter(Protocol):
    channel: ChannelDescriptor

    async def initiate_connection(self, business_name: str, redirect_uri: str) -> ConnectionInitiation: ...
    async def complete_connection(self, callback_payload: dict) -> ConnectionResult: ...
    async def refresh_token(self, access_token_encrypted: bytes, refresh_token_encrypted: bytes, wrapped_dek: bytes, kms_key_version: str) -> ConnectionResult: ...
    async def publish(self, *, asset_id: str, content_markdown: str, target_external_id: str, idempotency_key: str, meta: dict) -> PublishResult: ...
    async def verify(self, *, external_object_id: str, target_external_id: str, meta: dict) -> VerificationOutcome: ...
    def is_retryable_error(self, exc: Exception) -> bool: ...


class GBPAdapter:
    """Google Business Profile adapter stub."""
    channel = ChannelDescriptor(channel="google_business_profile", display_name="Google Business Profile", requires_oauth=True)

    async def initiate_connection(self, business_name: str, redirect_uri: str) -> ConnectionInitiation:
        raise NotImplementedError("GBP OAuth requires Google API credentials")

    async def complete_connection(self, callback_payload: dict) -> ConnectionResult:
        raise NotImplementedError("GBP OAuth requires Google API credentials")

    async def refresh_token(self, access_token_encrypted: bytes, refresh_token_encrypted: bytes, wrapped_dek: bytes, kms_key_version: str) -> ConnectionResult:
        raise NotImplementedError("GBP token refresh requires Google API credentials")

    async def publish(self, *, asset_id: str, content_markdown: str, target_external_id: str, idempotency_key: str, meta: dict) -> PublishResult:
        raise NotImplementedError("GBP publish requires Google API credentials")

    async def verify(self, *, external_object_id: str, target_external_id: str, meta: dict) -> VerificationOutcome:
        raise NotImplementedError("GBP verify requires Google API credentials")

    def is_retryable_error(self, exc: Exception) -> bool:
        return isinstance(exc, (TimeoutError, ConnectionError))


class WordPressAdapter:
    """WordPress REST API adapter stub."""
    channel = ChannelDescriptor(channel="wordpress", display_name="WordPress", requires_oauth=False)

    async def initiate_connection(self, business_name: str, redirect_uri: str) -> ConnectionInitiation:
        return ConnectionInitiation(
            channel="wordpress",
            oauth_url=None,
            instructions="Enter your WordPress site URL and Application Password in the form below.",
        )

    async def complete_connection(self, callback_payload: dict) -> ConnectionResult:
        raise NotImplementedError("WordPress connection requires site URL and Application Password")

    async def refresh_token(self, access_token_encrypted: bytes, refresh_token_encrypted: bytes, wrapped_dek: bytes, kms_key_version: str) -> ConnectionResult:
        raise NotImplementedError("WordPress Application Passwords do not expire")

    async def publish(self, *, asset_id: str, content_markdown: str, target_external_id: str, idempotency_key: str, meta: dict) -> PublishResult:
        raise NotImplementedError("WordPress publish requires site credentials")

    async def verify(self, *, external_object_id: str, target_external_id: str, meta: dict) -> VerificationOutcome:
        raise NotImplementedError("WordPress verify requires site credentials")

    def is_retryable_error(self, exc: Exception) -> bool:
        return isinstance(exc, (TimeoutError, ConnectionError))


class WebsiteSnippetAdapter:
    """Website snippet (non-WordPress) adapter."""
    channel = ChannelDescriptor(channel="website_snippet", display_name="Website Snippet", requires_oauth=False)
    _SNIPPET_TEMPLATE = '<div class="citedby-snippet" data-asset="{asset_id}" data-key="{idempotency_key}">{content}</div><!-- cb:{idempotency_key} -->'

    async def initiate_connection(self, business_name: str, redirect_uri: str) -> ConnectionInitiation:
        return ConnectionInitiation(
            channel="website_snippet",
            oauth_url=None,
            instructions="Add the generated snippet to your website's HTML.",
        )

    async def complete_connection(self, callback_payload: dict) -> ConnectionResult:
        raise NotImplementedError("Website snippet does not require OAuth")

    async def refresh_token(self, access_token_encrypted: bytes, refresh_token_encrypted: bytes, wrapped_dek: bytes, kms_key_version: str) -> ConnectionResult:
        raise NotImplementedError("Website snippet does not use tokens")

    async def publish(self, *, asset_id: str, content_markdown: str, target_external_id: str, idempotency_key: str, meta: dict) -> PublishResult:
        snippet = self._SNIPPET_TEMPLATE.format(
            asset_id=asset_id,
            idempotency_key=idempotency_key,
            content=content_markdown,
        )
        return PublishResult(
            success=True,
            external_object_id=idempotency_key,
            public_url=None,  # customer must install and provide URL
            failure_reason=None,
            is_retryable=False,
        )

    async def verify(self, *, external_object_id: str, target_external_id: str, meta: dict) -> VerificationOutcome:
        # Would fetch target_external_id URL and check for the idempotency_key marker
        return VerificationOutcome(outcome="still_pending", public_url=None)

    def is_retryable_error(self, exc: Exception) -> bool:
        return isinstance(exc, (TimeoutError, ConnectionError))


_REGISTRY: dict[str, PublisherAdapter] = {}


def _register(adapter: PublisherAdapter) -> None:
    _REGISTRY[adapter.channel.channel] = adapter


_register(GBPAdapter())
_register(WordPressAdapter())
_register(WebsiteSnippetAdapter())


class PublisherRegistry:
    def for_channel(self, channel: str) -> PublisherAdapter:
        adapter = _REGISTRY.get(channel)
        if adapter is None:
            raise KeyError(f"No adapter registered for channel '{channel}'")
        return adapter

    def all_channels(self) -> list[ChannelDescriptor]:
        return [a.channel for a in _REGISTRY.values()]
