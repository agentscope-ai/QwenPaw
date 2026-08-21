# -*- coding: utf-8 -*-
"""Ensure ToolGuard engine.guard is offloaded off the event loop."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from qwenpaw.config.context import current_terminal_manager
from qwenpaw.security.tool_guard.models import (
    GuardFinding,
    GuardSeverity,
    GuardThreatCategory,
    ToolGuardResult,
)


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
async def test_write_stdin_guards_accumulated_input_and_discards_on_denial():
    """Split terminal input must be reviewed as one pending line."""
    from qwenpaw.runtime.tool_guard import _guarded_tool_check_permissions

    finding = GuardFinding(
        id="split-input",
        rule_id="sensitive-path",
        category=GuardThreatCategory.SENSITIVE_FILE_ACCESS,
        severity=GuardSeverity.HIGH,
        title="Sensitive path",
        description="Accumulated terminal input targets a sensitive path.",
        tool_name="write_stdin",
    )
    guarded_result = ToolGuardResult(
        tool_name="write_stdin",
        params={"chars": "rm /tmp/sensitive.txt\n"},
        findings=[finding],
    )
    engine = MagicMock()
    engine.enabled = True
    engine.is_denied.return_value = False
    engine.is_guarded.return_value = True
    engine.guard.return_value = guarded_result
    engine.should_auto_deny_result.return_value = True

    manager = SimpleNamespace(
        preview_input=AsyncMock(return_value="rm /tmp/sensitive.txt\n"),
        discard_input=AsyncMock(),
    )
    tool = SimpleNamespace(
        name="write_stdin",
        _resolve_execution_level=lambda: "auto",
    )
    input_data = {
        "session_id": "term_test",
        "chars": "tive.txt\n",
    }
    token = current_terminal_manager.set(manager)
    try:
        with patch(
            "qwenpaw.security.tool_guard.engine.get_guard_engine",
            return_value=engine,
        ):
            decision = await _guarded_tool_check_permissions(tool, input_data)
    finally:
        current_terminal_manager.reset(token)

    guarded_params = engine.guard.call_args.args[1]
    assert guarded_params["chars"] == "rm /tmp/sensitive.txt\n"
    assert decision.behavior.value == "deny"
    manager.preview_input.assert_awaited_once_with(
        "term_test",
        "tive.txt\n",
    )
    manager.discard_input.assert_awaited_once_with("term_test")


@pytest.mark.asyncio
async def test_write_stdin_allow_authorizes_exact_guarded_snapshot():
    """An allowed fragment is bound to the exact input guardians saw."""
    from qwenpaw.runtime.tool_guard import _guarded_tool_check_permissions

    engine = MagicMock()
    engine.enabled = True
    engine.is_denied.return_value = False
    engine.is_guarded.return_value = True
    engine.guard.return_value = ToolGuardResult(
        tool_name="write_stdin",
        params={"chars": "echo safe\n"},
    )

    manager = SimpleNamespace(
        preview_input=AsyncMock(return_value="echo safe\n"),
        authorize_input=AsyncMock(),
        discard_input=AsyncMock(),
    )
    tool = SimpleNamespace(
        name="write_stdin",
        _resolve_execution_level=lambda: "auto",
    )
    input_data = {
        "session_id": "term_test",
        "chars": "safe\n",
    }
    token = current_terminal_manager.set(manager)
    try:
        with patch(
            "qwenpaw.security.tool_guard.engine.get_guard_engine",
            return_value=engine,
        ):
            decision = await _guarded_tool_check_permissions(tool, input_data)
    finally:
        current_terminal_manager.reset(token)

    assert decision.behavior.value == "allow"
    manager.authorize_input.assert_awaited_once_with(
        "term_test",
        "safe\n",
        "echo safe\n",
    )
    manager.discard_input.assert_not_awaited()


@pytest.mark.asyncio
async def test_raw_terminal_capability_requires_approval_in_auto_mode():
    """The real raw guardian must reach approval outside guarded tools."""
    from agentscope.permission import PermissionBehavior, PermissionDecision

    from qwenpaw.runtime.tool_guard import _guarded_tool_check_permissions
    from qwenpaw.security.tool_guard.guardians.terminal_guardian import (
        TerminalCapabilityGuardian,
    )

    guardian = TerminalCapabilityGuardian()
    engine = MagicMock()
    engine.enabled = True
    engine.is_denied.return_value = False
    engine.is_guarded.return_value = False
    engine.guard.side_effect = lambda tool_name, params, **_kwargs: (
        ToolGuardResult(
            tool_name=tool_name,
            params=params,
            findings=guardian.guard(tool_name, params),
        )
    )
    engine.should_auto_deny_result.return_value = False
    tool = SimpleNamespace(
        name="execute_shell_command",
        _resolve_execution_level=lambda: "auto",
        _qp_agent_id="agent-test",
        _qp_request_context={},
    )
    allowed = PermissionDecision(
        behavior=PermissionBehavior.ALLOW,
        message="approved",
    )

    with (
        patch(
            "qwenpaw.security.tool_guard.engine.get_guard_engine",
            return_value=engine,
        ),
        patch(
            "qwenpaw.runtime.tool_guard._ask_user_approval",
            new_callable=AsyncMock,
            return_value=allowed,
        ) as ask,
    ):
        decision = await _guarded_tool_check_permissions(
            tool,
            {"command": "less file", "input_mode": "raw"},
        )

    assert decision.behavior is PermissionBehavior.ALLOW
    ask.assert_awaited_once()
    assert engine.guard.call_args.kwargs["only_always_run"] is True
