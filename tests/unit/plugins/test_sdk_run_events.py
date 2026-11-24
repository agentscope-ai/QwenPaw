# -*- coding: utf-8 -*-
"""Live run subscriptions leave the unobserved stream untouched."""

import asyncio
from contextlib import aclosing
from unittest.mock import Mock

import pytest

from qwenpaw.plugins import _events
from qwenpaw.plugins.commands import CommandSpec
from qwenpaw.plugins.events import EventSubscription
from qwenpaw.schemas import AgentRequest


async def test_unobserved_stream_does_not_convert_or_classify_events(
    sdk_component,
    monkeypatch,
):
    convert = Mock(wraps=_events.chat_event)
    classify = Mock(wraps=_events._stream_outcome)
    monkeypatch.setattr(_events, "chat_event", convert)
    monkeypatch.setattr(_events, "_stream_outcome", classify)
    terminal = {"object": "response", "status": "completed"}

    @_events.observe_stream
    async def stream(workspace, request):
        yield terminal

    async with sdk_component() as (host, _):
        workspace = await host._workspace("test")
        assert [item async for item in stream(workspace, AgentRequest())] == [
            terminal,
        ]
    convert.assert_not_called()
    classify.assert_not_called()


@pytest.mark.parametrize("join_after_terminal", [False, True])
async def test_subscribing_during_a_run_delivers_remaining_events(
    sdk_component,
    join_after_terminal,
):
    received = asyncio.Queue()

    async def receive(call, event):
        received.put_nowait(event)

    first = {"object": "message", "status": "completed", "content": []}
    terminal = {"object": "response", "status": "cancelled"}

    @_events.observe_stream
    async def stream(workspace, request):
        yield first
        yield terminal

    async with sdk_component(capabilities=("events",)) as (host, ctx):
        workspace = await host._workspace("test")
        request = AgentRequest(
            request_id="request-id",
            session_id="test",
            channel="console",
        )
        async with aclosing(stream(workspace, request)) as events:
            assert await anext(events) is first
            if join_after_terminal:
                assert await anext(events) is terminal
            async with ctx.subscribe_events(EventSubscription(receive)):
                expected = [] if join_after_terminal else [terminal]
                assert [event async for event in events] == expected
                async with asyncio.timeout(5):
                    if not join_after_terminal:
                        updated = await received.get()
                        assert updated.kind == "run.updated"
                        assert updated.event.object == "response"
                        assert updated.run_id == request.request_id
                    completed = await received.get()
                assert completed.kind == "run.cancelled"
                assert completed.run_id == request.request_id


@pytest.mark.parametrize("status", ["completed", "cancelled"])
async def test_terminal_event_is_kept_while_subscribers_change(
    sdk_component,
    status,
):
    first_events, last_events = asyncio.Queue(), asyncio.Queue()

    async def first_listener(call, event):
        first_events.put_nowait(event)

    async def last_listener(call, event):
        last_events.put_nowait(event)

    created = {"object": "response", "status": "created"}
    terminal = {"object": "response", "status": status}
    trailing = {"object": "metrics"}

    @_events.observe_stream
    async def stream(workspace, request):
        yield created
        yield terminal
        yield trailing

    async with sdk_component(capabilities=("events",)) as (host, ctx):
        workspace = await host._workspace("test")
        request = AgentRequest(request_id="subscriber-switch")
        async with aclosing(stream(workspace, request)) as events:
            async with ctx.subscribe_events(EventSubscription(first_listener)):
                assert await anext(events) is created
                assert (
                    await asyncio.wait_for(first_events.get(), 5)
                ).kind == ("run.started")
            assert await anext(events) is terminal
            assert await anext(events) is trailing
            async with ctx.subscribe_events(EventSubscription(last_listener)):
                assert [item async for item in events] == []
                result = await asyncio.wait_for(last_events.get(), 5)
                assert result.kind == f"run.{status}"
                assert result.run_id == request.request_id


async def test_cancelled_runtime_closes_work_before_notifying_observers(
    sdk_component,
):
    entered = asyncio.Event()
    finished = asyncio.Event()
    notified = asyncio.Event()

    def declare(ctx):
        async def slow(call, arguments):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                finished.set()

        async def observe(call, event):
            if finished.is_set():
                notified.set()

        ctx.register_command(CommandSpec("slow-run", slow))
        ctx.on_activate(
            lambda active: active.subscribe_events(
                EventSubscription(observe, kinds=("run.cancelled",)),
            ),
        )

    async def run(host):
        return [event async for event in host.stream_chat("/slow-run")]

    async with sdk_component(declare, capabilities=("commands", "events")) as (
        host,
        _,
    ):
        task = asyncio.create_task(run(host))
        await asyncio.wait_for(entered.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(notified.wait(), 5)
