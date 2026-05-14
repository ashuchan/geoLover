"""Unit tests for Publishing adapters."""

from __future__ import annotations

import pytest

from app.modules.publishing.adapters import (
    ChannelDescriptor,
    GBPAdapter,
    PublisherRegistry,
    WebsiteSnippetAdapter,
    WordPressAdapter,
)


class TestPublisherRegistry:
    def test_for_channel_gbp(self):
        registry = PublisherRegistry()
        adapter = registry.for_channel("google_business_profile")
        assert isinstance(adapter, GBPAdapter)

    def test_for_channel_wordpress(self):
        registry = PublisherRegistry()
        adapter = registry.for_channel("wordpress")
        assert isinstance(adapter, WordPressAdapter)

    def test_for_channel_website_snippet(self):
        registry = PublisherRegistry()
        adapter = registry.for_channel("website_snippet")
        assert isinstance(adapter, WebsiteSnippetAdapter)

    def test_for_channel_missing_raises_key_error(self):
        registry = PublisherRegistry()
        with pytest.raises(KeyError, match="No adapter registered"):
            registry.for_channel("nonexistent_channel")

    def test_all_channels_returns_3(self):
        registry = PublisherRegistry()
        channels = registry.all_channels()
        assert len(channels) == 3

    def test_all_channels_returns_channel_descriptors(self):
        registry = PublisherRegistry()
        channels = registry.all_channels()
        for ch in channels:
            assert isinstance(ch, ChannelDescriptor)

    def test_all_channels_names(self):
        registry = PublisherRegistry()
        channel_names = {c.channel for c in registry.all_channels()}
        assert "google_business_profile" in channel_names
        assert "wordpress" in channel_names
        assert "website_snippet" in channel_names


class TestGBPAdapter:
    def setup_method(self):
        self.adapter = GBPAdapter()

    def test_channel_descriptor(self):
        assert self.adapter.channel.channel == "google_business_profile"
        assert self.adapter.channel.requires_oauth is True

    @pytest.mark.asyncio
    async def test_initiate_connection_raises(self):
        with pytest.raises(NotImplementedError):
            await self.adapter.initiate_connection("Biz", "https://example.com/cb")

    @pytest.mark.asyncio
    async def test_complete_connection_raises(self):
        with pytest.raises(NotImplementedError):
            await self.adapter.complete_connection({})

    @pytest.mark.asyncio
    async def test_refresh_token_raises(self):
        with pytest.raises(NotImplementedError):
            await self.adapter.refresh_token(b"", b"", b"", "v1")

    @pytest.mark.asyncio
    async def test_publish_raises(self):
        with pytest.raises(NotImplementedError):
            await self.adapter.publish(
                asset_id="a",
                content_markdown="md",
                target_external_id="t",
                idempotency_key="k",
                meta={},
            )

    @pytest.mark.asyncio
    async def test_verify_raises(self):
        with pytest.raises(NotImplementedError):
            await self.adapter.verify(
                external_object_id="o",
                target_external_id="t",
                meta={},
            )

    def test_is_retryable_timeout(self):
        assert self.adapter.is_retryable_error(TimeoutError()) is True

    def test_is_retryable_connection_error(self):
        assert self.adapter.is_retryable_error(ConnectionError()) is True

    def test_is_retryable_value_error(self):
        assert self.adapter.is_retryable_error(ValueError()) is False


class TestWordPressAdapter:
    def setup_method(self):
        self.adapter = WordPressAdapter()

    def test_channel_descriptor(self):
        assert self.adapter.channel.channel == "wordpress"
        assert self.adapter.channel.requires_oauth is False

    @pytest.mark.asyncio
    async def test_initiate_connection_returns_instructions(self):
        result = await self.adapter.initiate_connection("My Blog", "https://cb.example.com")
        assert result.channel == "wordpress"
        assert result.oauth_url is None
        assert "WordPress" in result.instructions

    @pytest.mark.asyncio
    async def test_complete_connection_raises(self):
        with pytest.raises(NotImplementedError):
            await self.adapter.complete_connection({})

    @pytest.mark.asyncio
    async def test_refresh_token_raises(self):
        with pytest.raises(NotImplementedError):
            await self.adapter.refresh_token(b"", b"", b"", "v1")

    @pytest.mark.asyncio
    async def test_publish_raises(self):
        with pytest.raises(NotImplementedError):
            await self.adapter.publish(
                asset_id="a",
                content_markdown="md",
                target_external_id="t",
                idempotency_key="k",
                meta={},
            )

    @pytest.mark.asyncio
    async def test_verify_raises(self):
        with pytest.raises(NotImplementedError):
            await self.adapter.verify(
                external_object_id="o",
                target_external_id="t",
                meta={},
            )

    def test_is_retryable_timeout(self):
        assert self.adapter.is_retryable_error(TimeoutError()) is True

    def test_is_retryable_connection_error(self):
        assert self.adapter.is_retryable_error(ConnectionError()) is True

    def test_is_retryable_value_error(self):
        assert self.adapter.is_retryable_error(ValueError()) is False


class TestWebsiteSnippetAdapter:
    def setup_method(self):
        self.adapter = WebsiteSnippetAdapter()

    def test_channel_descriptor(self):
        assert self.adapter.channel.channel == "website_snippet"
        assert self.adapter.channel.requires_oauth is False

    @pytest.mark.asyncio
    async def test_initiate_connection_returns_instructions(self):
        result = await self.adapter.initiate_connection("My Site", "https://cb.example.com")
        assert result.channel == "website_snippet"
        assert result.oauth_url is None
        assert result.instructions is not None

    @pytest.mark.asyncio
    async def test_complete_connection_raises(self):
        with pytest.raises(NotImplementedError):
            await self.adapter.complete_connection({})

    @pytest.mark.asyncio
    async def test_refresh_token_raises(self):
        with pytest.raises(NotImplementedError):
            await self.adapter.refresh_token(b"", b"", b"", "v1")

    @pytest.mark.asyncio
    async def test_publish_success(self):
        result = await self.adapter.publish(
            asset_id="asset-123",
            content_markdown="# Hello World",
            target_external_id="https://example.com",
            idempotency_key="idem-key-abc",
            meta={},
        )
        assert result.success is True
        assert result.external_object_id == "idem-key-abc"
        assert result.public_url is None
        assert result.failure_reason is None
        assert result.is_retryable is False

    @pytest.mark.asyncio
    async def test_verify_returns_still_pending(self):
        result = await self.adapter.verify(
            external_object_id="idem-key-abc",
            target_external_id="https://example.com",
            meta={},
        )
        assert result.outcome == "still_pending"
        assert result.public_url is None

    def test_is_retryable_timeout(self):
        assert self.adapter.is_retryable_error(TimeoutError()) is True

    def test_is_retryable_connection_error(self):
        assert self.adapter.is_retryable_error(ConnectionError()) is True

    def test_is_retryable_value_error(self):
        assert self.adapter.is_retryable_error(ValueError()) is False
