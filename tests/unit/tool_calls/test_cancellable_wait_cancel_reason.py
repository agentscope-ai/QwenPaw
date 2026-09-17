# -*- coding: utf-8 -*-
"""cancellable_wait cancel vs timeout reason separation."""
from __future__ import annotations

import asyncio

import pytest

from qwenpaw.tool_calls import (
    OFFLOAD_TIMEOUT_RATIO,
    arm_kill_deadline,
    cancellable_wait,
    reset_call_context,
    set_call_context,
)
from qwenpaw.tool_calls._context import CancelReason, ToolCallContext


@pytest.mark.asyncio
async def test_arm_kill_deadline_pulls_offload_when_shorter():
    """Direct kill arming (Windows host / ACP) must share pull-back logic."""
    loop = asyncio.get_running_loop()
    now = loop.time()
    ctx = ToolCallContext(
        tool_call_id="tc-arm-kill",
        tool_name="shell",
        session_id="s",
        agent_id="a",
        root_session_id="r",
        started_at=now,
        offload_deadline=now + 30.0,
        cancel_event=asyncio.Event(),
    )
    assert arm_kill_deadline(ctx, 12.0) is True
    assert ctx.kill_deadline is not None
    assert ctx.offload_deadline is not None
    assert ctx.offload_deadline < ctx.kill_deadline
    assert ctx.offload_deadline - now == pytest.approx(
        12.0 * OFFLOAD_TIMEOUT_RATIO,
        abs=0.05,
    )


@pytest.mark.asyncio
async def test_user_cancel_raises_cancelled_with_user_reason():
    ctx = ToolCallContext(
        tool_call_id="tc-cancel",
        tool_name="shell",
        session_id="s",
        agent_id="a",
        root_session_id="r",
        started_at=0.0,
        offload_deadline=None,
        cancel_event=asyncio.Event(),
    )
    token = set_call_context(ctx)
    try:

        async def work() -> str:
            await asyncio.sleep(10)
            return "done"

        async def cancel_soon() -> None:
            await asyncio.sleep(0.01)
            ctx.cancel_reason = CancelReason.USER
            ctx.cancel_event.set()

        asyncio.create_task(cancel_soon())
        with pytest.raises(asyncio.CancelledError) as exc_info:
            await cancellable_wait(
                work(),
                fallback_secs=5,
                as_kill_deadline=True,
            )
        assert "reason=user" in str(exc_info.value)
    finally:
        reset_call_context(token)


@pytest.mark.asyncio
async def test_shorter_kill_pulls_offload_deadline_back():
    """When tool kill budget is shorter than offload, shrink offload."""
    loop = asyncio.get_running_loop()
    now = loop.time()
    ctx = ToolCallContext(
        tool_call_id="tc-pull-offload",
        tool_name="shell",
        session_id="s",
        agent_id="a",
        root_session_id="r",
        started_at=now,
        offload_deadline=now + 30.0,
        cancel_event=asyncio.Event(),
    )
    token = set_call_context(ctx)
    try:

        async def work() -> str:
            return "ok"

        await cancellable_wait(
            work(),
            fallback_secs=20.0,
            as_kill_deadline=True,
        )
        assert ctx.kill_deadline is not None
        assert ctx.offload_deadline is not None
        assert ctx.offload_deadline < ctx.kill_deadline
        # ~ half of the 20s kill budget
        assert ctx.offload_deadline - now == pytest.approx(10.0, abs=0.05)
    finally:
        reset_call_context(token)


@pytest.mark.asyncio
async def test_timeout_cancel_raises_cancelled_with_timeout_reason():
    ctx = ToolCallContext(
        tool_call_id="tc-timeout",
        tool_name="shell",
        session_id="s",
        agent_id="a",
        root_session_id="r",
        started_at=0.0,
        offload_deadline=None,
        cancel_event=asyncio.Event(),
    )
    token = set_call_context(ctx)
    try:

        async def work() -> str:
            await asyncio.sleep(10)
            return "done"

        async def timeout_soon() -> None:
            await asyncio.sleep(0.01)
            ctx.cancel_reason = CancelReason.TIMEOUT
            ctx.cancel_event.set()

        asyncio.create_task(timeout_soon())
        with pytest.raises(asyncio.CancelledError) as exc_info:
            await cancellable_wait(
                work(),
                fallback_secs=5,
                as_kill_deadline=True,
            )
        assert "reason=timeout" in str(exc_info.value)
    finally:
        reset_call_context(token)
