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
