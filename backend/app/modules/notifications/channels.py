"""Notification channel adapters and registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable


@dataclass
class RenderedMessage:
    subject: Optional[str]
    body: str
    channel: str


@dataclass
class SendResult:
    success: bool
    provider_message_id: Optional[str]
    failure_reason: Optional[str]
    is_retryable: bool


@runtime_checkable
class NotificationChannel(Protocol):
    name: str

    async def send(self, notification_id: str, recipient_email: str, rendered: RenderedMessage) -> SendResult: ...
    async def supports(self, recipient_email: str) -> bool: ...


class EmailChannel:
    """Email channel adapter using Resend."""
    name = "email"

    async def send(self, notification_id: str, recipient_email: str, rendered: RenderedMessage) -> SendResult:
        raise NotImplementedError("EmailChannel requires Resend API key")

    async def supports(self, recipient_email: str) -> bool:
        return bool(recipient_email and "@" in recipient_email)


class InAppChannel:
    """In-app notification channel — persists to dashboard inbox."""
    name = "in_app"

    async def send(self, notification_id: str, recipient_email: str, rendered: RenderedMessage) -> SendResult:
        return SendResult(success=True, provider_message_id=notification_id, failure_reason=None, is_retryable=False)

    async def supports(self, recipient_email: str) -> bool:
        return True


class WhatsAppChannel:
    """WhatsApp channel adapter — feature-flag disabled until Phase 8 WABA setup."""
    name = "whatsapp"

    async def send(self, notification_id: str, recipient_email: str, rendered: RenderedMessage) -> SendResult:
        raise NotImplementedError("WhatsApp channel requires WABA approval (Phase 8)")

    async def supports(self, recipient_email: str) -> bool:
        return False  # disabled until feature flag enabled


_CHANNELS: dict[str, NotificationChannel] = {}


def _register_channel(ch: NotificationChannel) -> None:
    _CHANNELS[ch.name] = ch


_register_channel(EmailChannel())
_register_channel(InAppChannel())
_register_channel(WhatsAppChannel())


class ChannelRegistry:
    def for_name(self, name: str) -> NotificationChannel:
        ch = _CHANNELS.get(name)
        if ch is None:
            raise KeyError(f"No channel registered: '{name}'")
        return ch

    def all_names(self) -> list[str]:
        return list(_CHANNELS.keys())
