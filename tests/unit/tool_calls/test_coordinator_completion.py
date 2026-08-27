# -*- coding: utf-8 -*-
"""Tests for ToolCoordinator completion and offload lifecycle."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

import pytest
from agentscope.message import TextBlock, ToolResultBlock
from agentscope.tool import ToolResponse

from qwenpaw.tool_calls import ToolCoordinator, ToolCoordinatorMiddleware
from qwenpaw.tool_calls._context import CancelReason, ToolCallContext
from qwenpaw.tool_calls._entry import ToolCallEntry
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
async def test_after_hook_transforms_final_response_and_blocks_caller():
    coordinator = ToolCoordinator()
    tool_call = _ToolCall(name="expanding_tool")
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

    coordinator.hooks.register("expanding_tool", after=after_hook)
    task = asyncio.create_task(
        _collect(
            coordinator.execute(
                tool_call=tool_call,
                next_handler=next_handler,
                session_id="session-1",
                agent_id="agent-1",
                root_session_id="root-1",
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
    assert _tool_response_text_bytes(final) == 2000


@pytest.mark.asyncio
async def test_middleware_caller_observes_coordinator_response():
    coordinator = ToolCoordinator()
    middleware = ToolCoordinatorMiddleware(
        coordinator=coordinator,
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

    assert _tool_response_text_bytes(events[-1]) == 2000


@pytest.mark.asyncio
async def test_background_completion_emits_hint():
    coordinator = ToolCoordinator(
        default_timeout_secs=0.001,
        offload_on_deadline=True,
    )
    tool_call = _ToolCall(id="call-bg", name="slow_tool")

    async def next_handler(
        tool_call: _ToolCall,
    ) -> AsyncGenerator[Any, None]:
        await asyncio.sleep(0.05)
        yield _text_response(tool_call.id, "x" * 2000)

    events = await _collect(
        coordinator.execute(
            tool_call=tool_call,
            next_handler=next_handler,
            session_id="session-bg",
            agent_id="agent-1",
            root_session_id="root-1",
        ),
    )
    hint = await asyncio.wait_for(
        _wait_for_hint(coordinator, "session-bg"),
        timeout=2,
    )

    assert events[-1].metadata["offloaded"] is True
    assert hint.role == "assistant"
    text_block = next(
        block
        for block in hint.content
        if getattr(block, "type", None) == "text"
    )
    assert "slow_tool" in text_block.text


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
            offload_deadline=None,
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


@pytest.mark.asyncio
async def test_offload_disabled_clears_offload_deadline():
    """When offload_on_deadline=False, reaching offload_deadline should
    clear it and continue foreground execution instead of offloading."""
    coordinator = ToolCoordinator(
        default_timeout_secs=0.01,
        offload_on_deadline=False,
    )
    tool_call = _ToolCall(id="call-noop", name="fast_tool")

    async def next_handler(
        tool_call: _ToolCall,
    ) -> AsyncGenerator[Any, None]:
        await asyncio.sleep(0.05)
        yield _text_response(tool_call.id, "done")

    events = await _collect(
        coordinator.execute(
            tool_call=tool_call,
            next_handler=next_handler,
            session_id="session-noop",
            agent_id="agent-1",
            root_session_id="root-1",
        ),
    )

    final = events[-1]
    assert isinstance(final, ToolResponse)
    assert final.content[0].text == "done"
    assert final.metadata.get("offloaded") is not True


@pytest.mark.asyncio
async def test_kill_deadline_terminates_execution():
    """When kill_deadline is reached, the tool should be terminated."""
    coordinator = ToolCoordinator(offload_on_deadline=False)
    tool_call = _ToolCall(id="call-kill", name="kill_tool")

    async def next_handler(
        tool_call: _ToolCall,
    ) -> AsyncGenerator[Any, None]:
        from qwenpaw.tool_calls import cancellable_wait

        await cancellable_wait(
            asyncio.sleep(10),
            fallback_secs=0.05,
            as_kill_deadline=True,
        )
        yield _text_response(tool_call.id, "should not reach")

    events = await asyncio.wait_for(
        _collect(
            coordinator.execute(
                tool_call=tool_call,
                next_handler=next_handler,
                session_id="session-kill",
                agent_id="agent-1",
                root_session_id="root-1",
            ),
        ),
        timeout=5,
    )

    final = events[-1]
    assert isinstance(final, ToolResponse)
    assert "should not reach" not in final.content[0].text

    entry = coordinator.get("call-kill")
    if entry is not None:
        assert entry.ctx.cancel_event.is_set()
        assert entry.ctx.cancel_reason == CancelReason.TIMEOUT


@pytest.mark.asyncio
async def test_completed_cache_keeps_final_response():
    """Finalize still allows get() via the short TTL completed cache."""
    coordinator = ToolCoordinator(offload_on_deadline=False)
    tool_call = _ToolCall(id="call-cache", name="fast_tool")

    async def next_handler(
        tool_call: _ToolCall,
    ) -> AsyncGenerator[Any, None]:
        yield _text_response(tool_call.id, "cached-result")

    await _collect(
        coordinator.execute(
            tool_call=tool_call,
            next_handler=next_handler,
            session_id="session-cache",
            agent_id="agent-1",
            root_session_id="root-1",
        ),
    )

    # Hot table should not list it as in-flight
    assert all(
        e.ctx.tool_call_id != "call-cache" for e in coordinator.list_entries()
    )

    entry = coordinator.get("call-cache")
    assert entry is not None
    assert entry.final_response is not None
    assert entry.final_response.content[0].text == "cached-result"


@pytest.mark.asyncio
async def test_offload_policy_runtime_toggle():
    """offload_on_deadline can be toggled at runtime via the property."""
    coordinator = ToolCoordinator(offload_on_deadline=False)
    assert not coordinator.offload_on_deadline

    coordinator.offload_on_deadline = True
    assert coordinator.offload_on_deadline

    coordinator.offload_on_deadline = False
    assert not coordinator.offload_on_deadline


@pytest.mark.asyncio
async def test_extend_offload_deadline():
    """extend_offload_deadline should extend the offload wait time."""
    coordinator = ToolCoordinator(default_timeout_secs=0.5)
    tool_call = _ToolCall(id="call-extend", name="extend_tool")

    async def next_handler(
        tool_call: _ToolCall,
    ) -> AsyncGenerator[Any, None]:
        await asyncio.sleep(0.1)
        yield _text_response(tool_call.id, "ok")

    task = asyncio.create_task(
        _collect(
            coordinator.execute(
                tool_call=tool_call,
                next_handler=next_handler,
                session_id="session-ext",
                agent_id="agent-1",
                root_session_id="root-1",
            ),
        ),
    )

    await asyncio.sleep(0.01)
    ok = await coordinator.extend_offload_deadline(
        "call-extend",
        seconds=30,
    )
    assert ok is True

    events = await asyncio.wait_for(task, timeout=2)
    final = events[-1]
    assert isinstance(final, ToolResponse)
    assert final.content[0].text == "ok"


@pytest.mark.asyncio
async def test_extend_offload_deadline_rejects_after_offload():
    """extend_offload_deadline should return False for offloaded entries."""
    coordinator = ToolCoordinator(
        default_timeout_secs=0.001,
        offload_on_deadline=True,
    )
    tool_call = _ToolCall(id="call-ext-rej", name="slow_ext_tool")

    async def next_handler(
        tool_call: _ToolCall,
    ) -> AsyncGenerator[Any, None]:
        from qwenpaw.tool_calls import cancellable_wait

        await cancellable_wait(
            asyncio.sleep(1),
            fallback_secs=5.0,
            as_kill_deadline=True,
        )
        yield _text_response(tool_call.id, "done")

    events = await asyncio.wait_for(
        _collect(
            coordinator.execute(
                tool_call=tool_call,
                next_handler=next_handler,
                session_id="session-ext-rej",
                agent_id="agent-1",
                root_session_id="root-1",
            ),
        ),
        timeout=2,
    )

    assert events[-1].metadata["offloaded"] is True

    ok = await coordinator.extend_offload_deadline(
        "call-ext-rej",
        seconds=10,
    )
    assert ok is False


@pytest.mark.asyncio
async def test_offload_does_not_set_cancel_event_background_keeps_running():
    """Regression #6056: auto-offload must not signal cancel_event.

    The background task must keep running after the foreground yields the
    offloaded ToolResponse.
    """
    coordinator = ToolCoordinator(
        default_timeout_secs=0.001,
        offload_on_deadline=True,
    )
    tool_call = _ToolCall(id="call-offload-alive", name="slow_tool")
    release = asyncio.Event()
    still_running = asyncio.Event()

    async def next_handler(
        tool_call: _ToolCall,
    ) -> AsyncGenerator[Any, None]:
        from qwenpaw.tool_calls import cancellable_wait, get_call_context

        # Arm a long kill so seeded post-offload kill does not race this test.
        await cancellable_wait(
            asyncio.sleep(0.05),
            fallback_secs=5.0,
            as_kill_deadline=True,
        )
        ctx = get_call_context()
        assert ctx is not None
        assert not ctx.cancel_event.is_set()
        still_running.set()
        await release.wait()
        yield _text_response(tool_call.id, "bg-done")

    events = await asyncio.wait_for(
        _collect(
            coordinator.execute(
                tool_call=tool_call,
                next_handler=next_handler,
                session_id="session-offload-alive",
                agent_id="agent-1",
                root_session_id="root-1",
            ),
        ),
        timeout=2,
    )

    assert events[-1].metadata.get("offloaded") is True
    entry = coordinator.get("call-offload-alive")
    assert entry is not None
    assert entry.status.value == "offloaded"
    assert not entry.ctx.cancel_event.is_set()
    assert entry.background_task is not None
    assert not entry.background_task.done()
    assert entry.ctx.kill_deadline is not None

    await asyncio.wait_for(still_running.wait(), timeout=1)
    release.set()
    await asyncio.wait_for(
        _wait_for_hint(coordinator, "session-offload-alive"),
        timeout=2,
    )


@pytest.mark.asyncio
async def test_keep_foreground_survives_offload_deadline_then_kill():
    """Regression #6245: with offload_on_deadline=False, clearing the
    offload deadline must not strand the session — kill_deadline still
    terminates and execute() returns.
    """
    coordinator = ToolCoordinator(
        default_timeout_secs=0.02,
        offload_on_deadline=False,
    )
    tool_call = _ToolCall(id="call-keep-kill", name="keep_kill_tool")

    async def next_handler(
        tool_call: _ToolCall,
    ) -> AsyncGenerator[Any, None]:
        from qwenpaw.tool_calls import cancellable_wait

        # Offload window (~0.02s) clears first; kill (~0.08s) must still fire.
        await cancellable_wait(
            asyncio.sleep(10),
            fallback_secs=0.08,
            as_kill_deadline=True,
        )
        yield _text_response(tool_call.id, "should not reach")

    events = await asyncio.wait_for(
        _collect(
            coordinator.execute(
                tool_call=tool_call,
                next_handler=next_handler,
                session_id="session-keep-kill",
                agent_id="agent-1",
                root_session_id="root-1",
            ),
        ),
        timeout=5,
    )

    final = events[-1]
    assert isinstance(final, ToolResponse)
    assert "should not reach" not in final.content[0].text
    entry = coordinator.get("call-keep-kill")
    if entry is not None:
        assert entry.ctx.cancel_event.is_set()
        assert entry.ctx.cancel_reason == CancelReason.TIMEOUT


@pytest.mark.asyncio
async def test_keep_foreground_timeout_gt_hook_survives_offload_window():
    """Regression: tool timeout > hook offload must not be killed at offload.

    Mirrors chat_with_agent(timeout=600) under hook default_timeout=300 with
    keep_foreground: after offload clears, kill_deadline still bounds
    execution.
    """
    coordinator = ToolCoordinator(
        default_timeout_secs=0.05,
        offload_on_deadline=False,
    )
    tool_call = _ToolCall(id="call-long-timeout", name="chat_with_agent")

    async def next_handler(
        tool_call: _ToolCall,
    ) -> AsyncGenerator[Any, None]:
        from qwenpaw.tool_calls import cancellable_wait

        # Offload ~0.05s; tool timeout / kill ~0.2s.
        await cancellable_wait(
            asyncio.sleep(0.12),
            fallback_secs=0.25,
            as_kill_deadline=True,
        )
        yield _text_response(tool_call.id, "peer-reply")

    events = await asyncio.wait_for(
        _collect(
            coordinator.execute(
                tool_call=tool_call,
                next_handler=next_handler,
                session_id="session-long-timeout",
                agent_id="agent-1",
                root_session_id="root-1",
            ),
        ),
        timeout=2,
    )

    final = events[-1]
    assert isinstance(final, ToolResponse)
    assert final.content[0].text == "peer-reply"
    assert final.metadata.get("offloaded") is not True


@pytest.mark.asyncio
async def test_keep_foreground_without_kill_cancels_on_offload_expiry():
    """#6245 without as_kill_deadline: keep_foreground must not hang forever.

    When offload expires and kill_deadline was never armed, fall back to
    cancel + grace/force so execute() returns.
    """
    coordinator = ToolCoordinator(
        default_timeout_secs=0.03,
        offload_on_deadline=False,
        cancel_grace_period_secs=0.05,
    )
    tool_call = _ToolCall(id="call-no-kill", name="sleep_only_tool")

    async def next_handler(
        tool_call: _ToolCall,
    ) -> AsyncGenerator[Any, None]:
        # Non-cooperative: ignores cancel_event, never arms kill_deadline.
        await asyncio.sleep(10)
        yield _text_response(tool_call.id, "should not reach")

    events = await asyncio.wait_for(
        _collect(
            coordinator.execute(
                tool_call=tool_call,
                next_handler=next_handler,
                session_id="session-no-kill",
                agent_id="agent-1",
                root_session_id="root-1",
            ),
        ),
        timeout=2,
    )

    final = events[-1]
    assert isinstance(final, ToolResponse)
    assert "should not reach" not in final.content[0].text
    entry = coordinator.get("call-no-kill")
    assert entry is not None
    assert entry.ctx.cancel_reason == CancelReason.TIMEOUT
    assert entry.force_cancelled is True


@pytest.mark.asyncio
async def test_foreground_cancel_force_cancels_non_cooperative_tool():
    """Foreground Cancel must grace then force_cancel non-cooperative tools."""
    coordinator = ToolCoordinator(
        offload_on_deadline=False,
        cancel_grace_period_secs=0.05,
    )
    tool_call = _ToolCall(id="call-fg-cancel", name="ignore_cancel_tool")

    async def next_handler(
        tool_call: _ToolCall,
    ) -> AsyncGenerator[Any, None]:
        await asyncio.sleep(10)
        yield _text_response(tool_call.id, "should not reach")

    task = asyncio.create_task(
        _collect(
            coordinator.execute(
                tool_call=tool_call,
                next_handler=next_handler,
                session_id="session-fg-cancel",
                agent_id="agent-1",
                root_session_id="root-1",
            ),
        ),
    )

    await asyncio.sleep(0.02)
    ok = await coordinator.cancel(
        "call-fg-cancel",
        reason=CancelReason.USER,
    )
    assert ok is True

    events = await asyncio.wait_for(task, timeout=2)
    final = events[-1]
    assert isinstance(final, ToolResponse)
    assert "should not reach" not in final.content[0].text
    entry = coordinator.get("call-fg-cancel")
    assert entry is not None
    assert entry.ctx.cancel_reason == CancelReason.USER
    assert entry.force_cancelled is True


@pytest.mark.asyncio
async def test_background_cancel_force_cancels_non_cooperative_tool():
    """Background Cancel must not busy-continue; grace + force instead."""
    coordinator = ToolCoordinator(
        default_timeout_secs=30.0,
        offload_on_deadline=False,
        cancel_grace_period_secs=0.05,
    )
    tool_call = _ToolCall(id="call-bg-cancel", name="bg_ignore_cancel")
    started = asyncio.Event()

    async def next_handler(
        tool_call: _ToolCall,
    ) -> AsyncGenerator[Any, None]:
        started.set()
        await asyncio.sleep(10)
        yield _text_response(tool_call.id, "should not reach")

    task = asyncio.create_task(
        _collect(
            coordinator.execute(
                tool_call=tool_call,
                next_handler=next_handler,
                session_id="session-bg-cancel",
                agent_id="agent-1",
                root_session_id="root-1",
            ),
        ),
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    assert await coordinator.request_offload("call-bg-cancel") is True
    events = await asyncio.wait_for(task, timeout=2)
    assert events[-1].metadata.get("offloaded") is True

    entry = coordinator.get("call-bg-cancel")
    assert entry is not None
    assert entry.background_task is not None
    assert not entry.background_task.done()

    ok = await coordinator.cancel(
        "call-bg-cancel",
        reason=CancelReason.USER,
    )
    assert ok is True

    await asyncio.wait_for(entry.background_task, timeout=2)
    assert entry.force_cancelled is True
    assert entry.ctx.cancel_reason == CancelReason.USER


@pytest.mark.asyncio
async def test_offload_without_kill_seeds_kill_deadline():
    """Offload of unbound tools must seed kill_deadline (no forever bg)."""
    coordinator = ToolCoordinator(
        default_timeout_secs=0.02,
        offload_on_deadline=True,
    )
    tool_call = _ToolCall(id="call-seed-kill", name="unbound_tool")
    release = asyncio.Event()

    async def next_handler(
        tool_call: _ToolCall,
    ) -> AsyncGenerator[Any, None]:
        await release.wait()
        yield _text_response(tool_call.id, "bg-done")

    events = await asyncio.wait_for(
        _collect(
            coordinator.execute(
                tool_call=tool_call,
                next_handler=next_handler,
                session_id="session-seed-kill",
                agent_id="agent-1",
                root_session_id="root-1",
            ),
        ),
        timeout=2,
    )
    assert events[-1].metadata.get("offloaded") is True
    entry = coordinator.get("call-seed-kill")
    assert entry is not None
    assert entry.ctx.kill_deadline is not None
    assert not entry.ctx.cancel_event.is_set()
    release.set()
    await asyncio.wait_for(
        _wait_for_hint(coordinator, "session-seed-kill"),
        timeout=2,
    )


@pytest.mark.asyncio
async def test_request_offload_rejects_when_no_kill_bound_available():
    """Manual offload without kill and without seedable timeout must fail."""
    coordinator = ToolCoordinator(
        default_timeout_secs=None,
        offload_on_deadline=False,
    )
    tool_call = _ToolCall(id="call-no-bound", name="no_timeout_tool")
    started = asyncio.Event()

    async def next_handler(
        tool_call: _ToolCall,
    ) -> AsyncGenerator[Any, None]:
        started.set()
        await asyncio.sleep(10)
        yield _text_response(tool_call.id, "done")

    task = asyncio.create_task(
        _collect(
            coordinator.execute(
                tool_call=tool_call,
                next_handler=next_handler,
                session_id="session-no-bound",
                agent_id="agent-1",
                root_session_id="root-1",
            ),
        ),
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    entry = coordinator.get("call-no-bound")
    assert entry is not None
    assert entry.ctx.kill_deadline is None
    assert entry.ctx.offload_deadline is None

    ok = await coordinator.request_offload("call-no-bound")
    assert ok is False

    await coordinator.cancel(
        "call-no-bound",
        reason=CancelReason.USER,
        force=True,
    )
    await asyncio.wait_for(task, timeout=2)


@pytest.mark.asyncio
async def test_user_offload_message_tells_agent_not_to_rerun():
    """Manual offload ToolResponse must attribute the user and forbid rerun."""
    from qwenpaw.tool_calls._context import OffloadReason

    coordinator = ToolCoordinator(
        default_timeout_secs=30.0,
        offload_on_deadline=False,
    )
    tool_call = _ToolCall(id="call-user-offload", name="shell_tool")
    started = asyncio.Event()
    release = asyncio.Event()

    async def next_handler(
        tool_call: _ToolCall,
    ) -> AsyncGenerator[Any, None]:
        from qwenpaw.tool_calls import cancellable_wait

        started.set()
        await cancellable_wait(
            release.wait(),
            fallback_secs=30.0,
            as_kill_deadline=True,
        )
        yield _text_response(tool_call.id, "done")

    task = asyncio.create_task(
        _collect(
            coordinator.execute(
                tool_call=tool_call,
                next_handler=next_handler,
                session_id="session-user-offload",
                agent_id="agent-1",
                root_session_id="root-1",
            ),
        ),
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    assert await coordinator.request_offload(
        "call-user-offload",
        reason=OffloadReason.USER,
    )
    events = await asyncio.wait_for(task, timeout=2)
    text = events[-1].content[0].text
    assert "user moved tool" in text.lower() or "reason=user" in text
    assert "do not re-run" in text.lower()
    release.set()


@pytest.mark.asyncio
async def test_user_cancel_message_tells_agent_not_to_retry():
    """User cancel ToolResponse must say cancelled by user and not to retry."""
    coordinator = ToolCoordinator(
        offload_on_deadline=False,
        cancel_grace_period_secs=0.05,
    )
    tool_call = _ToolCall(id="call-user-msg", name="slow_tool")
    started = asyncio.Event()

    async def next_handler(
        tool_call: _ToolCall,
    ) -> AsyncGenerator[Any, None]:
        started.set()
        await asyncio.sleep(10)
        yield _text_response(tool_call.id, "should not reach")

    task = asyncio.create_task(
        _collect(
            coordinator.execute(
                tool_call=tool_call,
                next_handler=next_handler,
                session_id="session-user-msg",
                agent_id="agent-1",
                root_session_id="root-1",
            ),
        ),
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    await coordinator.cancel(
        "call-user-msg",
        reason=CancelReason.USER,
        force=True,
    )
    events = await asyncio.wait_for(task, timeout=2)
    text = events[-1].content[0].text
    assert "cancelled by the user" in text.lower()
    assert "do not retry" in text.lower()


@pytest.mark.asyncio
async def test_force_cancel_sets_cancel_event_before_task_cancel():
    """force=True must set cancel_event so process bridges can stop workers."""
    coordinator = ToolCoordinator(
        offload_on_deadline=False,
        cancel_grace_period_secs=0.05,
    )
    tool_call = _ToolCall(id="call-force", name="force_tool")
    started = asyncio.Event()

    async def next_handler(
        tool_call: _ToolCall,
    ) -> AsyncGenerator[Any, None]:
        started.set()
        await asyncio.sleep(10)
        yield _text_response(tool_call.id, "should not reach")

    task = asyncio.create_task(
        _collect(
            coordinator.execute(
                tool_call=tool_call,
                next_handler=next_handler,
                session_id="session-force",
                agent_id="agent-1",
                root_session_id="root-1",
            ),
        ),
    )

    await asyncio.wait_for(started.wait(), timeout=1)
    entry = coordinator.get("call-force")
    assert entry is not None
    assert not entry.ctx.cancel_event.is_set()

    ok = await coordinator.cancel(
        "call-force",
        reason=CancelReason.USER,
        force=True,
    )
    assert ok is True
    assert entry.ctx.cancel_event.is_set()
    assert entry.ctx.cancel_reason == CancelReason.USER
    assert entry.force_cancelled is True

    await asyncio.wait_for(task, timeout=2)


@pytest.mark.asyncio
async def test_equal_timeout_budget_offloads_before_kill():
    """Default equal offload/kill budgets must still auto-offload.

    Regression for review P1: when hook timeout equals tool kill timeout,
    kill must not win at the same instant and skip backgrounding.
    """
    coordinator = ToolCoordinator(
        default_timeout_secs=0.08,
        offload_on_deadline=True,
    )
    tool_call = _ToolCall(id="call-equal-budget", name="equal_budget_tool")
    release = asyncio.Event()
    saw_cancel = asyncio.Event()

    async def next_handler(
        tool_call: _ToolCall,
    ) -> AsyncGenerator[Any, None]:
        from qwenpaw.tool_calls import cancellable_wait

        # Arm kill to the same budget the coordinator resolved for offload.
        try:
            await cancellable_wait(
                release.wait(),
                fallback_secs=0.08,
                as_kill_deadline=True,
            )
        except asyncio.CancelledError:
            saw_cancel.set()
            raise
        yield _text_response(tool_call.id, "should-not-matter")

    events = await asyncio.wait_for(
        _collect(
            coordinator.execute(
                tool_call=tool_call,
                next_handler=next_handler,
                session_id="session-equal-budget",
                agent_id="agent-1",
                root_session_id="root-1",
            ),
        ),
        timeout=2,
    )

    assert events[-1].metadata.get("offloaded") is True
    entry = coordinator.get("call-equal-budget")
    assert entry is not None
    assert entry.status.value == "offloaded"
    assert not entry.ctx.cancel_event.is_set()
    assert entry.ctx.kill_deadline is not None
    remaining = entry.ctx.kill_deadline - asyncio.get_running_loop().time()
    assert remaining > 0.02
    assert not saw_cancel.is_set()

    release.set()
    await asyncio.wait_for(
        _wait_for_hint(coordinator, "session-equal-budget"),
        timeout=2,
    )


@pytest.mark.asyncio
async def test_extend_kill_allows_tool_past_original_budget():
    """extend_kill must keep a tool alive past its first kill budget."""
    coordinator = ToolCoordinator(offload_on_deadline=False)
    tool_call = _ToolCall(id="call-extend-e2e", name="slow_tool")
    started = asyncio.Event()

    async def next_handler(
        tool_call: _ToolCall,
    ) -> AsyncGenerator[Any, None]:
        from qwenpaw.tool_calls import cancellable_wait

        started.set()
        await cancellable_wait(
            asyncio.sleep(0.25),
            fallback_secs=0.08,
            as_kill_deadline=True,
        )
        yield _text_response(tool_call.id, "survived-extend")

    async def extend_soon() -> None:
        await started.wait()
        ok = await coordinator.extend_kill_deadline(
            "call-extend-e2e",
            seconds=1.0,
        )
        assert ok is True

    ext_task = asyncio.create_task(extend_soon())
    events = await asyncio.wait_for(
        _collect(
            coordinator.execute(
                tool_call=tool_call,
                next_handler=next_handler,
                session_id="session-extend-e2e",
                agent_id="agent-1",
                root_session_id="root-1",
            ),
        ),
        timeout=2,
    )
    await ext_task
    assert any(
        getattr(evt, "content", None)
        and any(
            getattr(b, "text", "") == "survived-extend" for b in evt.content
        )
        for evt in events
    )


@pytest.mark.asyncio
async def test_extend_kill_keeps_chat_style_async_collect_alive():
    """chat_with_agent-style async wait must survive past original timeout."""
    coordinator = ToolCoordinator(offload_on_deadline=False)
    tool_call = _ToolCall(id="call-chat-extend", name="chat_with_agent")
    started = asyncio.Event()
    release = asyncio.Event()

    async def next_handler(
        tool_call: _ToolCall,
    ) -> AsyncGenerator[Any, None]:
        from qwenpaw.tool_calls import cancellable_wait

        async def collect_hang() -> str:
            started.set()
            await release.wait()
            return "peer-ok"

        await cancellable_wait(
            collect_hang(),
            fallback_secs=0.08,
            as_kill_deadline=True,
        )
        yield _text_response(tool_call.id, "chat-survived-extend")

    async def extend_soon() -> None:
        await started.wait()
        ok = await coordinator.extend_kill_deadline(
            "call-chat-extend",
            seconds=1.0,
        )
        assert ok is True
        # Past original 0.08s kill budget; tool must still be running.
        await asyncio.sleep(0.08)
        assert release.is_set() is False
        release.set()

    ext_task = asyncio.create_task(extend_soon())
    events = await asyncio.wait_for(
        _collect(
            coordinator.execute(
                tool_call=tool_call,
                next_handler=next_handler,
                session_id="session-chat-extend",
                agent_id="agent-1",
                root_session_id="root-1",
            ),
        ),
        timeout=2,
    )
    await ext_task
    assert any(
        getattr(evt, "content", None)
        and any(
            getattr(b, "text", "") == "chat-survived-extend"
            for b in evt.content
        )
        for evt in events
    )


@pytest.mark.asyncio
async def test_offloaded_rejects_clearing_kill_deadline():
    """OFFLOADED tasks must keep a hard kill bound (no_deadline refused)."""
    coordinator = ToolCoordinator(
        default_timeout_secs=0.05,
        offload_on_deadline=True,
    )
    tool_call = _ToolCall(id="call-no-clear-kill", name="bound_tool")
    release = asyncio.Event()

    async def next_handler(
        tool_call: _ToolCall,
    ) -> AsyncGenerator[Any, None]:
        from qwenpaw.tool_calls import cancellable_wait

        await cancellable_wait(
            release.wait(),
            fallback_secs=5.0,
            as_kill_deadline=True,
        )
        yield _text_response(tool_call.id, "done")

    events = await asyncio.wait_for(
        _collect(
            coordinator.execute(
                tool_call=tool_call,
                next_handler=next_handler,
                session_id="session-no-clear-kill",
                agent_id="agent-1",
                root_session_id="root-1",
            ),
        ),
        timeout=2,
    )
    assert events[-1].metadata.get("offloaded") is True

    ok = await coordinator.extend_kill_deadline(
        "call-no-clear-kill",
        no_deadline=True,
    )
    assert ok is False
    entry = coordinator.get("call-no-clear-kill")
    assert entry is not None
    assert entry.ctx.kill_deadline is not None

    release.set()
    await asyncio.wait_for(
        _wait_for_hint(coordinator, "session-no-clear-kill"),
        timeout=2,
    )


@pytest.mark.asyncio
async def test_extend_kill_refuses_past_max_internal_and_no_deadline():
    """API must not promise more than a tool's internal executor ceiling."""
    from qwenpaw.tool_calls import COORDINATOR_OWNED_EXEC_TIMEOUT_SECS

    coordinator = ToolCoordinator(offload_on_deadline=False)
    coordinator.hooks.register(
        "execute_shell_command",
        max_internal_timeout_secs=float(COORDINATOR_OWNED_EXEC_TIMEOUT_SECS),
    )
    tool_call = _ToolCall(id="call-cap", name="execute_shell_command")
    started = asyncio.Event()
    release = asyncio.Event()

    async def next_handler(
        tool_call: _ToolCall,
    ) -> AsyncGenerator[Any, None]:
        from qwenpaw.tool_calls import cancellable_wait

        started.set()
        await cancellable_wait(
            release.wait(),
            fallback_secs=30.0,
            as_kill_deadline=True,
        )
        yield _text_response(tool_call.id, "done")

    task = asyncio.create_task(
        _collect(
            coordinator.execute(
                tool_call=tool_call,
                next_handler=next_handler,
                session_id="session-cap",
                agent_id="agent-1",
                root_session_id="root-1",
            ),
        ),
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    entry = coordinator.get("call-cap")
    assert entry is not None

    # Jump kill near the ceiling, then refuse another +30 days.
    loop = asyncio.get_running_loop()
    entry.ctx.kill_deadline = (
        entry.ctx.started_at + float(COORDINATOR_OWNED_EXEC_TIMEOUT_SECS) - 1.0
    )
    ok = await coordinator.extend_kill_deadline("call-cap", seconds=86400.0)
    assert ok is False
    ok_clear = await coordinator.extend_kill_deadline(
        "call-cap",
        no_deadline=True,
    )
    assert ok_clear is False
    assert entry.ctx.kill_deadline is not None

    # Small extend still under the ceiling succeeds.
    ok_small = await coordinator.extend_kill_deadline("call-cap", seconds=0.5)
    assert ok_small is True
    assert entry.ctx.kill_deadline <= (
        entry.ctx.started_at
        + float(COORDINATOR_OWNED_EXEC_TIMEOUT_SECS)
        + 1e-6
    )
    assert entry.ctx.kill_deadline > loop.time()

    await coordinator.cancel("call-cap", force=True)
    release.set()
    await asyncio.wait_for(task, timeout=2)


@pytest.mark.asyncio
async def test_request_offload_rejects_short_kill_without_bound():
    """Refuse offload when kill remaining is tiny and cannot be topped up."""
    coordinator = ToolCoordinator(
        default_timeout_secs=None,
        offload_on_deadline=False,
    )
    tool_call = _ToolCall(id="call-short-kill", name="delegate_external_agent")
    started = asyncio.Event()

    async def next_handler(
        tool_call: _ToolCall,
    ) -> AsyncGenerator[Any, None]:
        started.set()
        await asyncio.sleep(10)
        yield _text_response(tool_call.id, "done")

    task = asyncio.create_task(
        _collect(
            coordinator.execute(
                tool_call=tool_call,
                next_handler=next_handler,
                session_id="session-short-kill",
                agent_id="agent-1",
                root_session_id="root-1",
            ),
        ),
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    entry = coordinator.get("call-short-kill")
    assert entry is not None
    entry.ctx.kill_deadline = asyncio.get_running_loop().time() + 0.01

    ok = await coordinator.request_offload("call-short-kill")
    assert ok is False

    await coordinator.cancel(
        "call-short-kill",
        reason=CancelReason.USER,
        force=True,
    )
    await asyncio.wait_for(task, timeout=2)
