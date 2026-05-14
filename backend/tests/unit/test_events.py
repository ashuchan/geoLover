"""Unit tests for app.core.events — domain event bus."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass

import pytest

from app.core.events import DomainEvent, EventBus


# ── Test event types ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ThingHappened(DomainEvent):
    thing_id: uuid.UUID = uuid.uuid4()


@dataclass(frozen=True)
class OtherThingHappened(DomainEvent):
    name: str = "test"


# ── DomainEvent tests ─────────────────────────────────────────────────────────


class TestDomainEvent:
    def test_has_event_id(self):
        evt = ThingHappened()
        assert isinstance(evt.event_id, uuid.UUID)

    def test_unique_event_ids(self):
        e1, e2 = ThingHappened(), ThingHappened()
        assert e1.event_id != e2.event_id

    def test_has_occurred_at(self):
        from datetime import timezone
        evt = ThingHappened()
        assert evt.occurred_at.tzinfo == timezone.utc

    def test_event_type_is_class_name(self):
        evt = ThingHappened()
        assert evt.event_type == "ThingHappened"

    def test_frozen(self):
        evt = ThingHappened()
        with pytest.raises((AttributeError, TypeError)):
            evt.event_id = uuid.uuid4()  # type: ignore[misc]


# ── EventBus tests ────────────────────────────────────────────────────────────


class TestEventBus:
    @pytest.fixture
    def bus(self) -> EventBus:
        return EventBus()

    @pytest.mark.asyncio
    async def test_subscribe_and_publish(self, bus):
        received = []

        @bus.subscribe(ThingHappened)
        async def handler(evt: ThingHappened):
            received.append(evt)

        evt = ThingHappened()
        await bus.publish(evt)
        assert received == [evt]

    @pytest.mark.asyncio
    async def test_multiple_handlers_called_in_order(self, bus):
        order = []

        @bus.subscribe(ThingHappened)
        async def first(evt):
            order.append("first")

        @bus.subscribe(ThingHappened)
        async def second(evt):
            order.append("second")

        await bus.publish(ThingHappened())
        assert order == ["first", "second"]

    @pytest.mark.asyncio
    async def test_unrelated_event_not_dispatched(self, bus):
        received = []

        @bus.subscribe(ThingHappened)
        async def handler(evt):
            received.append(evt)

        await bus.publish(OtherThingHappened())
        assert received == []

    @pytest.mark.asyncio
    async def test_handler_error_suppressed_by_default(self, bus):
        @bus.subscribe(ThingHappened)
        async def bad_handler(evt):
            raise ValueError("boom")

        # Should not raise
        await bus.publish(ThingHappened())

    @pytest.mark.asyncio
    async def test_propagate_errors_flag(self, bus):
        @bus.subscribe(ThingHappened)
        async def bad_handler(evt):
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            await bus.publish(ThingHappened(), propagate_errors=True)

    def test_register_programmatic(self, bus):
        calls = []

        async def handler(evt):
            calls.append(evt)

        bus.register(ThingHappened, handler)
        assert bus.handler_count(ThingHappened) == 1

    def test_unregister(self, bus):
        async def handler(evt):
            pass

        bus.register(ThingHappened, handler)
        assert bus.handler_count(ThingHappened) == 1
        bus.unregister(ThingHappened, handler)
        assert bus.handler_count(ThingHappened) == 0

    def test_unregister_nonexistent_is_noop(self, bus):
        async def handler(evt):
            pass

        bus.unregister(ThingHappened, handler)  # should not raise

    def test_clear_specific_type(self, bus):
        bus.register(ThingHappened, lambda e: None)
        bus.register(OtherThingHappened, lambda e: None)
        bus.clear(ThingHappened)
        assert bus.handler_count(ThingHappened) == 0
        assert bus.handler_count(OtherThingHappened) == 1

    def test_clear_all(self, bus):
        bus.register(ThingHappened, lambda e: None)
        bus.register(OtherThingHappened, lambda e: None)
        bus.clear()
        assert bus.handler_count(ThingHappened) == 0
        assert bus.handler_count(OtherThingHappened) == 0

    def test_handler_count_no_handlers(self, bus):
        assert bus.handler_count(ThingHappened) == 0

    @pytest.mark.asyncio
    async def test_publish_no_handlers_is_noop(self, bus):
        await bus.publish(ThingHappened())  # must not raise
