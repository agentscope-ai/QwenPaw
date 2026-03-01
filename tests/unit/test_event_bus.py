# -*- coding: utf-8 -*-
"""Unit tests for the event bus and SSE event stream.

Covers: EventBus (emit/subscribe/filter/overflow/cleanup),
        Event model, EventType constants.
"""
from __future__ import annotations

import asyncio

import pytest

from copaw.app.events.types import Event, EventType, ALL_EVENT_TYPES
from copaw.app.events.bus import EventBus


# ── EventType ────────────────────────────────────────────────────────


class TestEventType:
    def test_known_types(self):
        assert EventType.AGENT_QUERY_START == "agent.query_start"
        assert EventType.AGENT_QUERY_COMPLETE == "agent.query_complete"
        assert EventType.AGENT_TOOL_CALL == "agent.tool_call"
        assert EventType.AGENT_TOOL_RESULT == "agent.tool_result"
        assert EventType.CONFIG_CHANGED == "config.changed"
        assert EventType.CRON_TRIGGERED == "cron.triggered"
        assert EventType.CRON_COMPLETED == "cron.completed"
        assert EventType.SESSION_STATUS == "session.status"

    def test_all_event_types_set(self):
        assert len(ALL_EVENT_TYPES) == 8
        assert EventType.AGENT_TOOL_CALL in ALL_EVENT_TYPES


# ── Event model ──────────────────────────────────────────────────────


class TestEventModel:
    def test_defaults(self):
        e = Event(type="test.event")
        assert e.id  # auto-generated
        assert len(e.id) == 12
        assert e.timestamp > 0
        assert e.data == {}
        assert e.session_id is None

    def test_with_data(self):
        e = Event(
            type=EventType.AGENT_TOOL_CALL,
            data={"tool_name": "read_file"},
            session_id="abc123",
        )
        assert e.type == "agent.tool_call"
        assert e.data["tool_name"] == "read_file"
        assert e.session_id == "abc123"

    def test_serialization(self):
        e = Event(type="test", data={"key": "value"})
        d = e.model_dump()
        assert d["type"] == "test"
        assert d["data"]["key"] == "value"
        assert "id" in d
        assert "timestamp" in d


# ── EventBus ─────────────────────────────────────────────────────────


class TestEventBusEmitSubscribe:
    @pytest.mark.asyncio
    async def test_single_subscriber(self):
        bus = EventBus()
        received = []

        async def consume():
            async for event in bus.subscribe():
                received.append(event)
                if len(received) >= 2:
                    break

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.01)

        bus.emit(Event(type="a"))
        bus.emit(Event(type="b"))
        await asyncio.wait_for(task, timeout=1.0)

        assert len(received) == 2
        assert received[0].type == "a"
        assert received[1].type == "b"

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self):
        bus = EventBus()
        received_1 = []
        received_2 = []

        async def consume(out: list):
            async for event in bus.subscribe():
                out.append(event)
                if len(out) >= 1:
                    break

        t1 = asyncio.create_task(consume(received_1))
        t2 = asyncio.create_task(consume(received_2))
        await asyncio.sleep(0.01)

        bus.emit(Event(type="broadcast"))
        await asyncio.wait_for(asyncio.gather(t1, t2), timeout=1.0)

        assert len(received_1) == 1
        assert len(received_2) == 1
        assert received_1[0].type == "broadcast"

    @pytest.mark.asyncio
    async def test_subscriber_count(self):
        bus = EventBus()
        assert bus.subscriber_count == 0

        received = []

        async def consume():
            async for event in bus.subscribe():
                received.append(event)
                break

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.01)
        assert bus.subscriber_count == 1

        bus.emit(Event(type="done"))
        await asyncio.wait_for(task, timeout=1.0)
        await asyncio.sleep(0.01)
        assert bus.subscriber_count == 0


class TestEventBusFilter:
    @pytest.mark.asyncio
    async def test_filter_by_type(self):
        bus = EventBus()
        received = []

        async def consume():
            async for event in bus.subscribe(event_types={"agent.tool_call"}):
                received.append(event)
                if len(received) >= 1:
                    break

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.01)

        bus.emit(Event(type="config.changed"))
        bus.emit(Event(type="agent.tool_call", data={"tool": "shell"}))
        await asyncio.wait_for(task, timeout=1.0)

        assert len(received) == 1
        assert received[0].type == "agent.tool_call"

    @pytest.mark.asyncio
    async def test_filter_multiple_types(self):
        bus = EventBus()
        received = []

        async def consume():
            types = {"agent.tool_call", "cron.triggered"}
            async for event in bus.subscribe(event_types=types):
                received.append(event)
                if len(received) >= 2:
                    break

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.01)

        bus.emit(Event(type="config.changed"))
        bus.emit(Event(type="agent.tool_call"))
        bus.emit(Event(type="session.status"))
        bus.emit(Event(type="cron.triggered"))
        await asyncio.wait_for(task, timeout=1.0)

        assert len(received) == 2
        types = {e.type for e in received}
        assert types == {"agent.tool_call", "cron.triggered"}

    @pytest.mark.asyncio
    async def test_no_filter_receives_all(self):
        bus = EventBus()
        received = []

        async def consume():
            async for event in bus.subscribe(event_types=None):
                received.append(event)
                if len(received) >= 3:
                    break

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.01)

        bus.emit(Event(type="a"))
        bus.emit(Event(type="b"))
        bus.emit(Event(type="c"))
        await asyncio.wait_for(task, timeout=1.0)

        assert len(received) == 3


class TestEventBusOverflow:
    @pytest.mark.asyncio
    async def test_overflow_discards_oldest(self):
        bus = EventBus()
        # Don't consume — let the queue fill up.
        gen = bus.subscribe()
        # Start the generator to register the subscriber.
        task = asyncio.create_task(gen.__anext__())
        await asyncio.sleep(0.01)

        # Emit more than maxsize (256) events.
        for i in range(300):
            bus.emit(Event(type="flood", data={"i": i}))

        # The subscriber should still work (oldest dropped).
        event = await asyncio.wait_for(task, timeout=1.0)
        assert event.type == "flood"
        # The first events should have been dropped.
        assert event.data["i"] > 0

        await gen.aclose()


class TestEventBusCleanup:
    @pytest.mark.asyncio
    async def test_subscriber_removed_on_close(self):
        bus = EventBus()

        gen = bus.subscribe()
        # Start consuming to register subscriber.
        task = asyncio.create_task(gen.__anext__())
        await asyncio.sleep(0.01)
        assert bus.subscriber_count == 1

        # Close the generator.
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await gen.aclose()
        await asyncio.sleep(0.01)
        assert bus.subscriber_count == 0

    @pytest.mark.asyncio
    async def test_emit_with_no_subscribers(self):
        bus = EventBus()
        # Should not raise.
        bus.emit(Event(type="lonely"))
        assert bus.subscriber_count == 0


# ── get_event_bus singleton ──────────────────────────────────────────


class TestGetEventBus:
    def test_singleton(self):
        from copaw.app.events.bus import get_event_bus

        bus1 = get_event_bus()
        bus2 = get_event_bus()
        assert bus1 is bus2
