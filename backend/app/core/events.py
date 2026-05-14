"""In-process domain event bus.

Modules publish domain events; other modules subscribe handlers.  This keeps
modules decoupled — no direct cross-module imports or table reads.

Usage:
    # Publishing (in a service):
    await event_bus.publish(BusinessCreatedEvent(business_id=..., tenant_id=...))

    # Subscribing (in module startup / lifespan):
    @event_bus.subscribe(BusinessCreatedEvent)
    async def _on_business_created(evt: BusinessCreatedEvent) -> None:
        ...

All handlers are called sequentially in subscription order.  Errors in handlers
do NOT propagate to the publisher by default; they are logged.  For critical
side-effects that must succeed transactionally, use the outbox pattern instead.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Type, TypeVar
import uuid

logger = logging.getLogger(__name__)

E = TypeVar("E", bound="DomainEvent")
Handler = Callable[[Any], Awaitable[None]]


# ── Base event ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DomainEvent:
    """Base class for all domain events."""

    event_id: uuid.UUID = field(default_factory=uuid.uuid4)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def event_type(self) -> str:
        return type(self).__name__


# ── Event bus ─────────────────────────────────────────────────────────────────


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[type, list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: Type[E]) -> Callable[[Handler], Handler]:
        """Decorator that registers *fn* as a handler for *event_type*."""

        def decorator(fn: Handler) -> Handler:
            self._handlers[event_type].append(fn)
            return fn

        return decorator

    def register(self, event_type: Type[E], handler: Handler) -> None:
        """Programmatically register *handler* for *event_type*."""
        self._handlers[event_type].append(handler)

    def unregister(self, event_type: Type[E], handler: Handler) -> None:
        """Remove a previously registered handler (useful in tests)."""
        try:
            self._handlers[event_type].remove(handler)
        except ValueError:
            pass

    def clear(self, event_type: Type[E] | None = None) -> None:
        """Remove all handlers, or only handlers for *event_type*."""
        if event_type is None:
            self._handlers.clear()
        else:
            self._handlers.pop(event_type, None)

    async def publish(self, event: DomainEvent, *, propagate_errors: bool = False) -> None:
        """Call all registered handlers for *event* in order.

        Args:
            event: The domain event to dispatch.
            propagate_errors: If True, the first handler exception re-raises.
                              Default False — errors are logged and suppressed.
        """
        handlers = self._handlers.get(type(event), [])
        for handler in handlers:
            try:
                await handler(event)
            except Exception:
                if propagate_errors:
                    raise
                logger.exception(
                    "Unhandled error in event handler",
                    extra={"event_type": event.event_type, "event_id": str(event.event_id)},
                )

    def handler_count(self, event_type: Type[E]) -> int:
        return len(self._handlers.get(event_type, []))


# ── Singleton ─────────────────────────────────────────────────────────────────

event_bus = EventBus()
