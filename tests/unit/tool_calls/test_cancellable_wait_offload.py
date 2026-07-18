# -*- coding: utf-8 -*-
"""Tests for offload-aware cancellable_wait.

Verifies that:
- When offload_reason is set, the task is NOT cancelled (subprocess keeps running)
- When offload_reason is NOT set, the task IS cancelled (normal cancel behavior)
"""
import asyncio
import pytest
from unittest.mock import MagicMock, patch

from qwenpaw.tool_calls._timeout_helper import cancellable_wait
from qwenpaw.tool_calls._context import (
    ToolCallContext,
    OffloadReason,
    CancelReason,
)
from qwenpaw.tool_calls._ctxvars import set_call_context


@pytest.fixture
def mock_ctx():
    """Create a mock ToolCallContext."""
    import time
    ctx = ToolCallContext(
        tool_call_id="test-123",
        tool_name="execute_shell_command",
        session_id="sess-1",
        agent_id="default",
        root_session_id="root-1",
        started_at=time.monotonic(),
        deadline=time.monotonic() + 10.0,
        cancel_event=asyncio.Event(),
    )
    return ctx


@pytest.mark.asyncio
async def test_cancellable_wait_offload_does_not_cancel_task(mock_ctx):
    """When offload_reason is set, task should NOT be cancelled."""
    mock_ctx.offload_reason = OffloadReason.TIMEOUT
    mock_ctx.cancel_event.set()

    task_cancelled = False

    async def long_running_task():
        nonlocal task_cancelled
        try:
            await asyncio.sleep(100)
        except asyncio.CancelledError:
            task_cancelled = True
            raise

    from qwenpaw.tool_calls._ctxvars import reset_call_context
    token = set_call_context(mock_ctx)
    try:
        with pytest.raises(asyncio.CancelledError, match="offloaded"):
            await cancellable_wait(long_running_task(), fallback_secs=1.0)
    finally:
        reset_call_context(token)

    assert not task_cancelled, "Task should NOT be cancelled when offloading"


@pytest.mark.asyncio
async def test_cancellable_wait_cancel_does_cancel_task(mock_ctx):
    """When offload_reason is NOT set (user cancel), task SHOULD be cancelled."""
    mock_ctx.cancel_reason = CancelReason.USER
    mock_ctx.cancel_event.set()

    task_cancelled = False

    async def long_running_task():
        nonlocal task_cancelled
        try:
            await asyncio.sleep(100)
        except asyncio.CancelledError:
            task_cancelled = True
            raise

    from qwenpaw.tool_calls._ctxvars import reset_call_context
    token = set_call_context(mock_ctx)
    try:
        with pytest.raises(asyncio.CancelledError, match="cancelled by manager"):
            await cancellable_wait(long_running_task(), fallback_secs=1.0)
    finally:
        reset_call_context(token)

    assert task_cancelled, "Task SHOULD be cancelled when user cancels"
