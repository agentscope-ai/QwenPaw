# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""``QwenPawAgent`` surfaces middleware-injected exchanges as tool events,
live, while the reasoning generator is still waiting."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from agentscope.event import (
    ToolCallDeltaEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
    ToolResultEndEvent,
    ToolResultStartEvent,
    ToolResultTextDeltaEvent,
)
from agentscope.message import ToolResultState

from qwenpaw.agents.react_agent import QwenPawAgent


def _bare_agent() -> QwenPawAgent:
    agent = QwenPawAgent.__new__(QwenPawAgent)
    agent._injected_events = None
    agent.state = SimpleNamespace(reply_id="reply-1")
    return agent


def test_begin_stream_finish_emit_a_complete_tool_call_and_result():
    agent = _bare_agent()
    agent.begin_injected_exchange(
        call_id="c1",
        name="consult_advisor",
        arguments='{"question": "plan?"}',
    )
    agent.stream_injected_output(call_id="c1", delta="THE PLAN")
    agent.finish_injected_exchange(call_id="c1")
    events = list(agent._drain_injected_exchange_events())
    assert [type(e) for e in events] == [
        ToolCallStartEvent,
        ToolCallDeltaEvent,
        ToolCallEndEvent,
        ToolResultStartEvent,
        ToolResultTextDeltaEvent,
        ToolResultEndEvent,
    ]
    assert all(e.reply_id == "reply-1" for e in events)
    assert all(e.tool_call_id == "c1" for e in events)
    assert events[0].tool_call_name == "consult_advisor"
    assert events[1].delta == '{"question": "plan?"}'
    assert events[4].delta == "THE PLAN"
    assert events[5].state == ToolResultState.SUCCESS
    assert not list(agent._drain_injected_exchange_events()), "drained"


def test_empty_arguments_and_output_skip_the_deltas():
    agent = _bare_agent()
    agent.begin_injected_exchange(call_id="c2", name="x", arguments="")
    agent.stream_injected_output(call_id="c2", delta="")
    agent.finish_injected_exchange(call_id="c2")
    events = list(agent._drain_injected_exchange_events())
    assert [type(e) for e in events] == [
        ToolCallStartEvent,
        ToolCallEndEvent,
        ToolResultStartEvent,
        ToolResultEndEvent,
    ]


def test_begin_stream_finish_build_the_exchange_incrementally():
    agent = _bare_agent()
    agent.begin_injected_exchange(call_id="c3", name="t", arguments="{}")
    agent.stream_injected_output(call_id="c3", delta="hel")
    agent.stream_injected_output(call_id="c3", delta="")  # ignored
    agent.stream_injected_output(call_id="c3", delta="lo")
    agent.finish_injected_exchange(call_id="c3", state=ToolResultState.ERROR)
    events = list(agent._drain_injected_exchange_events())
    assert [type(e) for e in events] == [
        ToolCallStartEvent,
        ToolCallDeltaEvent,
        ToolCallEndEvent,
        ToolResultStartEvent,
        ToolResultTextDeltaEvent,
        ToolResultTextDeltaEvent,
        ToolResultEndEvent,
    ]
    assert [e.delta for e in events[4:6]] == ["hel", "lo"]
    assert events[-1].state == ToolResultState.ERROR


# ── live merge ──────────────────────────────────────────────────────────


async def _collect(agent, inner):
    return [evt async for evt in agent._with_live_injections(inner)]


async def test_events_queued_during_a_long_await_come_out_immediately():
    """The whole point: an exchange queued while the inner generator is
    blocked is yielded before the inner produces anything."""
    agent = _bare_agent()
    release = asyncio.Event()
    order: list[str] = []

    async def inner():
        # Simulates the middleware asking the advisor inside the model
        # call: it queues events, then keeps waiting.
        agent.emit_injected_event("plan-start")
        await release.wait()
        yield "model-1"
        yield "model-2"

    async def consume():
        async for evt in agent._with_live_injections(inner()):
            order.append(evt)
            if evt == "plan-start":
                # Seen live: the inner is still blocked here.
                assert not release.is_set()
                agent.emit_injected_event("plan-delta")
                release.set()

    await asyncio.wait_for(consume(), timeout=2)
    assert order == ["plan-start", "plan-delta", "model-1", "model-2"]


async def test_queued_events_precede_the_inner_event_of_the_same_step():
    agent = _bare_agent()

    async def inner():
        agent.emit_injected_event("injected")
        yield "model"

    assert await _collect(agent, inner()) == ["injected", "model"]


async def test_inner_exceptions_propagate_unchanged():
    agent = _bare_agent()
    boom = RuntimeError("model down")

    async def inner():
        yield "first"
        raise boom

    with pytest.raises(RuntimeError) as info:
        await _collect(agent, inner())
    assert info.value is boom


async def test_cancellation_reaches_the_inner_generator():
    agent = _bare_agent()
    cleaned = asyncio.Event()
    started = asyncio.Event()

    async def inner():
        started.set()
        try:
            await asyncio.sleep(10)
        finally:
            cleaned.set()
        yield "never"  # pragma: no cover

    task = asyncio.create_task(_collect(agent, inner()))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cleaned.is_set(), "inner finally ran"


async def test_stopping_early_closes_the_inner_generator():
    agent = _bare_agent()
    closed = asyncio.Event()

    async def inner():
        try:
            yield "a"
            yield "b"
        finally:
            closed.set()

    gen = agent._with_live_injections(inner())
    assert await gen.__anext__() == "a"
    await gen.aclose()
    assert closed.is_set()


async def test_empty_inner_with_nothing_queued():
    agent = _bare_agent()

    async def inner():
        for item in ():  # an async generator that yields nothing
            yield item

    assert await _collect(agent, inner()) == []
