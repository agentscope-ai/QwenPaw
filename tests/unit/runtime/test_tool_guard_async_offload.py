# -*- coding: utf-8 -*-
"""Ensure ToolGuard engine.guard is offloaded off the event loop."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
async def test_off_mode_still_blocks_file_guard_findings():
    """OFF skips tool approval but cannot bypass file protection."""
    from qwenpaw.runtime.tool_guard import _guarded_tool_check_permissions

    finding = GuardFinding(
        id="file-guard-finding",
        rule_id="SENSITIVE_FILE_BLOCK",
        category=GuardThreatCategory.SENSITIVE_FILE_ACCESS,
        severity=GuardSeverity.HIGH,
        title="Protected file",
        description="Protected file access",
        tool_name="read_file",
        guardian="file_path_tool_guardian",
    )
    engine = MagicMock()
    engine.enabled = False
    engine.guard_file_access.return_value = ToolGuardResult(
        tool_name="read_file",
        params={"file_path": "/protected/key"},
        findings=[finding],
    )
    tool = SimpleNamespace(
        name="read_file",
        _resolve_execution_level=lambda: "off",
    )

    with patch(
        "qwenpaw.security.tool_guard.engine.get_guard_engine",
        return_value=engine,
    ):
        decision = await _guarded_tool_check_permissions(
            tool,
            {"file_path": "/protected/key"},
        )

    assert decision.behavior.value == "deny"
    assert "File Guard blocked" in decision.message
    engine.guard.assert_not_called()
