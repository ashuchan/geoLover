"""Unit tests for notification channel adapters and registry."""

from __future__ import annotations

import pytest

from app.modules.notifications.channels import (
    ChannelRegistry,
    EmailChannel,
    InAppChannel,
    RenderedMessage,
    SendResult,
    WhatsAppChannel,
)


class TestChannelRegistry:
    def test_for_name_email(self):
        registry = ChannelRegistry()
        ch = registry.for_name("email")
        assert ch.name == "email"
        assert isinstance(ch, EmailChannel)

    def test_for_name_in_app(self):
        registry = ChannelRegistry()
        ch = registry.for_name("in_app")
        assert ch.name == "in_app"
        assert isinstance(ch, InAppChannel)

    def test_for_name_whatsapp(self):
        registry = ChannelRegistry()
        ch = registry.for_name("whatsapp")
        assert ch.name == "whatsapp"
        assert isinstance(ch, WhatsAppChannel)

    def test_for_name_unknown_raises(self):
        registry = ChannelRegistry()
        with pytest.raises(KeyError):
            registry.for_name("unknown_channel")

    def test_all_names_returns_three(self):
        registry = ChannelRegistry()
        names = registry.all_names()
        assert len(names) == 3
        assert "email" in names
        assert "in_app" in names
        assert "whatsapp" in names


class TestEmailChannel:
    @pytest.mark.asyncio
    async def test_send_raises_not_implemented(self):
        ch = EmailChannel()
        rendered = RenderedMessage(subject="Hello", body="World", channel="email")
        with pytest.raises(NotImplementedError):
            await ch.send("notif-id-1", "user@example.com", rendered)

    @pytest.mark.asyncio
    async def test_supports_valid_email(self):
        ch = EmailChannel()
        assert await ch.supports("test@example.com") is True

    @pytest.mark.asyncio
    async def test_supports_invalid_email(self):
        ch = EmailChannel()
        assert await ch.supports("notanemail") is False

    @pytest.mark.asyncio
    async def test_supports_empty_email(self):
        ch = EmailChannel()
        assert await ch.supports("") is False

    @pytest.mark.asyncio
    async def test_supports_none_email(self):
        ch = EmailChannel()
        assert await ch.supports(None) is False  # type: ignore


class TestInAppChannel:
    @pytest.mark.asyncio
    async def test_send_returns_success(self):
        ch = InAppChannel()
        rendered = RenderedMessage(subject=None, body="In-app message", channel="in_app")
        result = await ch.send("notif-id-2", "user@example.com", rendered)
        assert isinstance(result, SendResult)
        assert result.success is True
        assert result.provider_message_id == "notif-id-2"
        assert result.failure_reason is None
        assert result.is_retryable is False

    @pytest.mark.asyncio
    async def test_supports_always_true(self):
        ch = InAppChannel()
        assert await ch.supports("") is True
        assert await ch.supports("anything") is True


class TestWhatsAppChannel:
    @pytest.mark.asyncio
    async def test_send_raises_not_implemented(self):
        ch = WhatsAppChannel()
        rendered = RenderedMessage(subject=None, body="WA message", channel="whatsapp")
        with pytest.raises(NotImplementedError):
            await ch.send("notif-id-3", "+919999999999", rendered)

    @pytest.mark.asyncio
    async def test_supports_always_false(self):
        ch = WhatsAppChannel()
        assert await ch.supports("+919999999999") is False
        assert await ch.supports("user@example.com") is False
        assert await ch.supports("") is False
