# -*- coding: utf-8 -*-
"""Tests for cooperative tool-call timeout helpers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

import pytest
from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from qwenpaw.tool_calls import (
    ToolCallContext,
    ToolCoordinator,
    reset_call_context,
    reschedule_call_timeout,
    set_call_context,
)


@dataclass
class _ToolCall:
    id: str = "call-1"
    name: str = "execute_shell_command"
    input: dict[str, Any] = field(default_factory=dict)


@pytest.mark.asyncio
async def test_reschedule_call_timeout_updates_active_context() -> None:
    loop = asyncio.get_running_loop()
    ctx = ToolCallContext(
        tool_call_id="call-1",
        tool_name="execute_shell_command",
        session_id="session-1",
        agent_id="agent-1",
        root_session_id="root-1",
        started_at=loop.time(),
        deadline=loop.time() + 60.0,
        cancel_event=asyncio.Event(),
    )
    token = set_call_context(ctx)

    try:
        before = loop.time()
        assert reschedule_call_timeout(240.0) is True
    finally:
        reset_call_context(token)

    assert ctx.deadline is not None
    assert before + 240.0 <= ctx.deadline <= loop.time() + 240.0
    assert ctx.deadline_changed_event.is_set()


def test_reschedule_call_timeout_without_context_is_noop() -> None:
    assert reschedule_call_timeout(240.0) is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "timeout",
    [0.0, -1.0, float("inf"), float("nan"), "invalid", None],
)
async def test_invalid_timeout_does_not_change_context(timeout: Any) -> None:
    loop = asyncio.get_running_loop()
    original_deadline = loop.time() + 60.0
    ctx = ToolCallContext(
        tool_call_id="call-1",
        tool_name="execute_shell_command",
        session_id="session-1",
        agent_id="agent-1",
        root_session_id="root-1",
        started_at=loop.time(),
        deadline=original_deadline,
        cancel_event=asyncio.Event(),
    )
    token = set_call_context(ctx)

    try:
        assert reschedule_call_timeout(timeout) is False
    finally:
        reset_call_context(token)

    assert ctx.deadline == original_deadline
    assert not ctx.deadline_changed_event.is_set()


@pytest.mark.asyncio
async def test_coordinator_observes_rescheduled_timeout() -> None:
    coordinator = ToolCoordinator(default_timeout_secs=0.01)
    tool_call = _ToolCall()

    async def next_handler(
        tool_call: _ToolCall,
    ) -> AsyncGenerator[ToolResponse, None]:
        assert reschedule_call_timeout(0.2) is True
        await asyncio.sleep(0.03)
        yield ToolResponse(
            content=[TextBlock(type="text", text="completed")],
            id=tool_call.id,
        )

    events = [
        item
        async for item in coordinator.execute(
            tool_call=tool_call,
            next_handler=next_handler,
            session_id="session-1",
            agent_id="agent-1",
            root_session_id="root-1",
        )
    ]

    assert len(events[-1].content) == 1
    assert events[-1].content[0].text == "completed"
    assert events[-1].metadata.get("offloaded") is not True
