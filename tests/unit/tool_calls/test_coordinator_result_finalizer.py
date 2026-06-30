# -*- coding: utf-8 -*-
"""Tests for ToolCoordinator final response limiting."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

import pytest
from agentscope.message import TextBlock, ToolResultBlock
from agentscope.tool import ToolResponse

from qwenpaw.tool_calls import ToolCoordinator, ToolCoordinatorMiddleware
from qwenpaw.tool_calls._context import ToolCallContext
from qwenpaw.tool_calls._entry import ToolCallEntry
from qwenpaw.tool_calls._result_limiter import ToolResultLimiter
from qwenpaw.tool_calls._stream import ToolStream


@dataclass
class _ToolCall:
    id: str = "call-1"
    name: str = "test_tool"
    input: dict[str, Any] = field(default_factory=dict)


def _text_response(tool_call_id: str, text: str) -> ToolResponse:
    return ToolResponse(
        content=[TextBlock(type="text", text=text)],
        id=tool_call_id,
    )


def _tool_response_text_bytes(response: ToolResponse) -> int:
    return sum(
        len(block.text.encode("utf-8"))
        for block in response.content
        if getattr(block, "type", None) == "text"
    )


def _tool_result_output_text_bytes(block: ToolResultBlock) -> int:
    if isinstance(block.output, str):
        return len(block.output.encode("utf-8"))
    return sum(
        len(output.text.encode("utf-8"))
        for output in block.output
        if getattr(output, "type", None) == "text"
    )


async def _collect(
    iterator: AsyncGenerator[Any, None],
) -> list[Any]:
    events: list[Any] = []
    async for item in iterator:
        events.append(item)
    return events


async def _wait_for_hint(
    coordinator: ToolCoordinator,
    session_id: str,
) -> Any:
    while True:
        hints = await coordinator.pop_pending_hints(session_id)
        if hints:
            return hints[0]
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_foreground_finalizer_runs_after_after_hook(tmp_path):
    coordinator = ToolCoordinator()
    tool_call = _ToolCall(name="expanding_tool")
    limiter = ToolResultLimiter(
        enabled=True,
        max_text_bytes=512,
        cache_dir=tmp_path,
    )
    finalizer_calls = 0
    after_started = asyncio.Event()
    release_after = asyncio.Event()

    async def next_handler(
        tool_call: _ToolCall,
    ) -> AsyncGenerator[Any, None]:
        yield _text_response(tool_call.id, "small")

    async def after_hook(
        response: ToolResponse,
        ctx: ToolCallContext,
    ) -> ToolResponse:
        assert response.content[0].text == "small"
        after_started.set()
        await release_after.wait()
        return _text_response(ctx.tool_call_id, "x" * 2000)

    def finalizer(
        response: ToolResponse,
        ctx: ToolCallContext,
    ) -> ToolResponse:
        nonlocal finalizer_calls
        finalizer_calls += 1
        return limiter.limit(response, ctx)

    coordinator.hooks.register("expanding_tool", after=after_hook)
    task = asyncio.create_task(
        _collect(
            coordinator.execute(
                tool_call=tool_call,
                next_handler=next_handler,
                session_id="session-1",
                agent_id="agent-1",
                root_session_id="root-1",
                result_finalizer=finalizer,
            ),
        ),
    )

    await asyncio.wait_for(after_started.wait(), timeout=1)
    await asyncio.sleep(0)
    assert not task.done()

    release_after.set()
    events = await asyncio.wait_for(task, timeout=1)
    final = events[-1]

    assert isinstance(final, ToolResponse)
    assert _tool_response_text_bytes(final) <= 512
    assert finalizer_calls == 1


@pytest.mark.asyncio
async def test_middleware_caller_observes_capped_response(tmp_path):
    coordinator = ToolCoordinator()
    limiter = ToolResultLimiter(
        enabled=True,
        max_text_bytes=512,
        cache_dir=tmp_path,
    )
    middleware = ToolCoordinatorMiddleware(
        coordinator=coordinator,
        result_limiter=limiter,
    )
    agent = type(
        "AgentStub",
        (),
        {
            "_request_context": {
                "session_id": "session-1",
                "agent_id": "agent-1",
                "root_session_id": "root-1",
            },
        },
    )()
    tool_call = _ToolCall()

    async def next_handler(
        tool_call: _ToolCall,
    ) -> AsyncGenerator[Any, None]:
        yield _text_response(tool_call.id, "x" * 2000)

    events = await _collect(
        middleware.on_acting(
            agent,
            {"tool_call": tool_call},
            next_handler,
        ),
    )

    assert _tool_response_text_bytes(events[-1]) <= 512


@pytest.mark.asyncio
async def test_async_finalizer_is_awaited():
    coordinator = ToolCoordinator()
    tool_call = _ToolCall()

    async def next_handler(
        tool_call: _ToolCall,
    ) -> AsyncGenerator[Any, None]:
        yield _text_response(tool_call.id, "x" * 2000)

    async def finalizer(
        _response: ToolResponse,
        ctx: ToolCallContext,
    ) -> ToolResponse:
        await asyncio.sleep(0)
        return _text_response(ctx.tool_call_id, "finalized")

    events = await _collect(
        coordinator.execute(
            tool_call=tool_call,
            next_handler=next_handler,
            session_id="session-1",
            agent_id="agent-1",
            root_session_id="root-1",
            result_finalizer=finalizer,
        ),
    )

    assert events[-1].content[0].text == "finalized"


@pytest.mark.asyncio
async def test_background_completion_hint_uses_finalized_response(tmp_path):
    coordinator = ToolCoordinator(default_timeout_secs=0.001)
    tool_call = _ToolCall(id="call-bg", name="slow_tool")
    limiter = ToolResultLimiter(
        enabled=True,
        max_text_bytes=512,
        cache_dir=tmp_path,
    )
    finalizer_calls = 0

    async def next_handler(
        tool_call: _ToolCall,
    ) -> AsyncGenerator[Any, None]:
        await asyncio.sleep(0.02)
        yield _text_response(tool_call.id, "x" * 2000)

    def finalizer(
        response: ToolResponse,
        ctx: ToolCallContext,
    ) -> ToolResponse:
        nonlocal finalizer_calls
        finalizer_calls += 1
        return limiter.limit(response, ctx)

    events = await _collect(
        coordinator.execute(
            tool_call=tool_call,
            next_handler=next_handler,
            session_id="session-bg",
            agent_id="agent-1",
            root_session_id="root-1",
            result_finalizer=finalizer,
        ),
    )
    hint = await asyncio.wait_for(
        _wait_for_hint(coordinator, "session-bg"),
        timeout=1,
    )
    tool_result = next(
        block
        for block in hint.content
        if getattr(block, "type", None) == "tool_result"
    )

    assert events[-1].metadata["offloaded"] is True
    assert hint.role == "assistant"
    assert _tool_result_output_text_bytes(tool_result) <= 512
    assert finalizer_calls == 1


@pytest.mark.asyncio
async def test_caller_cancellation_does_not_cancel_background_task():
    # pylint: disable=protected-access
    bg_started = asyncio.Event()
    bg_can_finish = asyncio.Event()
    tool_call = _ToolCall(id="call-cancel", name="slow_tool")

    async def background() -> None:
        bg_started.set()
        await bg_can_finish.wait()

    bg_task = asyncio.create_task(background())
    entry = ToolCallEntry(
        ctx=ToolCallContext(
            tool_call_id=tool_call.id,
            tool_name=tool_call.name,
            session_id="session-cancel",
            agent_id="agent-1",
            root_session_id="root-1",
            started_at=0.0,
            deadline=None,
            cancel_event=asyncio.Event(),
        ),
        stream=ToolStream(
            tool_call_id=tool_call.id,
            session_id="session-cancel",
        ),
        final_response=ToolResponse(id=tool_call.id),
        background_task=bg_task,
    )

    waiter = asyncio.create_task(
        ToolCoordinator._await_background_task(entry),
    )
    await asyncio.wait_for(bg_started.wait(), timeout=1)
    await asyncio.sleep(0)

    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter

    assert not bg_task.cancelled()
    assert not bg_task.done()

    bg_can_finish.set()
    await asyncio.wait_for(bg_task, timeout=1)
