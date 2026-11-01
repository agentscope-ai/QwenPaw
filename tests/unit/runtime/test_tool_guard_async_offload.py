# -*- coding: utf-8 -*-
"""Ensure ToolGuard engine.guard is offloaded off the event loop."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from qwenpaw.security.tool_guard.models import ToolGuardResult


@pytest.mark.asyncio
async def test_guarded_permissions_offloads_engine_guard():
    """Async permission adapter must not call engine.guard on the loop."""
    from qwenpaw.runtime.tool_guard import _guarded_tool_check_permissions

    engine = MagicMock()
    engine.enabled = True
    engine.is_denied.return_value = False
    engine.is_guarded.return_value = True
    engine.should_auto_deny_result.return_value = False
    engine.guard.return_value = ToolGuardResult(
        tool_name="execute_shell_command",
        params={"command": "echo ok"},
    )

    tool = SimpleNamespace(
        name="execute_shell_command",
        _resolve_execution_level=lambda: "auto",
    )

    with (
        patch(
            "qwenpaw.security.tool_guard.engine.get_guard_engine",
            return_value=engine,
        ),
        patch(
            "qwenpaw.runtime.tool_guard.asyncio.to_thread",
            new_callable=AsyncMock,
        ) as to_thread,
    ):
        to_thread.return_value = engine.guard.return_value
        decision = await _guarded_tool_check_permissions(
            tool,
            {"command": "echo ok"},
        )

    to_thread.assert_awaited()
    assert to_thread.await_args.args[0] is engine.guard
    assert decision.behavior.value == "allow"


@pytest.mark.asyncio
async def test_fallback_jev_skips_registered_target_free_read():
    """The fallback uses a Python name but the read declaration uses policy."""
    from qwenpaw.agents.tools.get_current_time import get_current_time
    from qwenpaw.runtime.tool_guard import GuardedFunctionTool

    engine = MagicMock()
    engine.enabled = True
    engine.is_denied.return_value = False
    engine.is_guarded.return_value = False
    engine.guard.return_value = ToolGuardResult(
        tool_name="get_current_time",
        params={},
    )
    tool = GuardedFunctionTool(
        get_current_time,
        agent_id="test-agent",
        request_context={"approval_level": "JEV"},
    )

    with (
        patch(
            "qwenpaw.security.tool_guard.engine.get_guard_engine",
            return_value=engine,
        ),
        patch(
            "qwenpaw.runtime.tool_guard._ask_user_approval",
            new_callable=AsyncMock,
        ) as ask,
    ):
        decision = await tool.check_permissions({})

    assert decision.behavior.value == "allow"
    assert "verified read-only" in decision.message
    engine.guard.assert_called_once_with(
        "get_current_time",
        {},
        only_always_run=True,
    )
    ask.assert_not_awaited()


@pytest.mark.asyncio
async def test_fallback_jev_does_not_trust_unregistered_same_name():
    """A same-name callable must still go through approval."""
    from qwenpaw.runtime.tool_guard import _guarded_tool_check_permissions

    async def get_current_time():
        return None

    engine = MagicMock()
    engine.enabled = True
    engine.is_denied.return_value = False
    engine.is_guarded.return_value = False
    engine.guard.return_value = ToolGuardResult(
        tool_name="get_current_time",
        params={},
    )
    tool = SimpleNamespace(
        name="get_current_time",
        _qp_agent_id="test-agent",
        _qp_tool_func=get_current_time,
        _qp_request_context={},
        _resolve_execution_level=lambda: "jev",
    )
    approval = object()

    with (
        patch(
            "qwenpaw.security.tool_guard.engine.get_guard_engine",
            return_value=engine,
        ),
        patch(
            "qwenpaw.runtime.tool_guard._ask_user_approval",
            new_callable=AsyncMock,
            return_value=approval,
        ) as ask,
    ):
        decision = await _guarded_tool_check_permissions(tool, {})

    assert decision is approval
    assert ask.await_count == 1
    assert (
        "target is too broad"
        in ask.await_args.kwargs["guard_result"].findings[0].description
    )
