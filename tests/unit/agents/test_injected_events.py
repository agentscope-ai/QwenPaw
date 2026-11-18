# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Middleware-injected events reach the chat stream live, while the
reasoning generator is still waiting."""
from __future__ import annotations

import asyncio

import pytest

from qwenpaw.agents.injected_events import merge_injected_events
from qwenpaw.agents.react_agent import QwenPawAgent


async def _collect(inner, queue):
    return [evt async for evt in merge_injected_events(inner, queue)]


def test_unarmed_agent_drops_injected_events():
    agent = object.__new__(QwenPawAgent)
    agent._injected_events = None
    assert agent.emit_injected_event("plan") is False


def test_armed_agent_queues_injected_events():
    agent = object.__new__(QwenPawAgent)
    agent._injected_events = asyncio.Queue()
    assert agent.emit_injected_event("plan") is True
    assert agent._injected_events.get_nowait() == "plan"


async def test_events_queued_during_a_long_await_come_out_immediately():
    """The whole point: an event queued while the inner generator is
    blocked is yielded before the inner produces anything."""
    queue: asyncio.Queue = asyncio.Queue()
    release = asyncio.Event()
    order: list[str] = []

    async def inner():
        # Simulates the middleware asking the advisor inside the model
        # call: it queues events, then keeps waiting.
        queue.put_nowait("plan-start")
        await release.wait()
        yield "model-1"
        yield "model-2"

    async def consume():
        async for evt in merge_injected_events(inner(), queue):
            order.append(evt)
            if evt == "plan-start":
                # Seen live: the inner is still blocked here.
                assert not release.is_set()
                queue.put_nowait("plan-delta")
                release.set()

    await asyncio.wait_for(consume(), timeout=2)
    assert order == ["plan-start", "plan-delta", "model-1", "model-2"]


async def test_queued_events_precede_the_inner_event_of_the_same_step():
    queue: asyncio.Queue = asyncio.Queue()

    async def inner():
        queue.put_nowait("injected")
        yield "model"

    assert await _collect(inner(), queue) == ["injected", "model"]


async def test_inner_exceptions_propagate_unchanged():
    boom = RuntimeError("model down")

    async def inner():
        yield "first"
        raise boom

    with pytest.raises(RuntimeError) as info:
        await _collect(inner(), asyncio.Queue())
    assert info.value is boom


async def test_cancellation_reaches_the_inner_generator():
    cleaned = asyncio.Event()
    started = asyncio.Event()

    async def inner():
        started.set()
        try:
            await asyncio.sleep(10)
        finally:
            cleaned.set()
        yield "never"  # pragma: no cover

    task = asyncio.create_task(_collect(inner(), asyncio.Queue()))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cleaned.is_set(), "inner finally ran"


async def test_stopping_early_closes_the_inner_generator():
    closed = asyncio.Event()

    async def inner():
        try:
            yield "a"
            yield "b"
        finally:
            closed.set()

    gen = merge_injected_events(inner(), asyncio.Queue())
    assert await gen.__anext__() == "a"
    await gen.aclose()
    assert closed.is_set()


async def test_empty_inner_with_nothing_queued():
    async def inner():
        for item in ():  # an async generator that yields nothing
            yield item

    assert await _collect(inner(), asyncio.Queue()) == []
