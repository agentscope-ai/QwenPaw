# -*- coding: utf-8 -*-
"""Regression tests for managed-terminal input under sandbox governance."""

from __future__ import annotations

import pytest
from agentscope.message import ToolResultState
from agentscope.permission import PermissionBehavior

from qwenpaw.agents.tools.shell import write_stdin
from qwenpaw.config.context import current_terminal_manager
from qwenpaw.governance import PolicyGuardedTool
from qwenpaw.governance.policy import (
    GovernanceAction,
    GovernanceRule,
    ToolCallSpec,
    _create_default_policy,
)
from qwenpaw.governance.tool_registry import DEFAULT_REGISTRY
from qwenpaw.terminal.models import SessionResult


def _terminal_call(chars: str = "") -> ToolCallSpec:
    return ToolCallSpec(
        tool_name="TerminalInput",
        target="term_demo",
        agent_id="test-agent",
        session_id="test-session",
        raw_params={"session_id": "term_demo", "chars": chars},
    )


class TestTerminalInputPolicy:
    def test_registry_marks_terminal_input_as_inheriting_sandbox(self):
        assert DEFAULT_REGISTRY.get_type("TerminalInput") == "shell"
        assert DEFAULT_REGISTRY.inherits_sandbox("TerminalInput") is True
        assert DEFAULT_REGISTRY.inherits_sandbox("Bash") is False

    @pytest.mark.parametrize("level", ["smart", "auto", "off"])
    def test_clean_input_does_not_start_a_new_sandbox(self, level):
        policy = _create_default_policy("/tmp/test-workspace")
        policy.execution_level = level

        decision = policy.evaluate(_terminal_call())

        assert decision.action is GovernanceAction.ALLOW
        assert decision.source == "sandbox_inherited"
        assert decision.sandbox_config is None

    def test_strict_mode_still_requires_approval(self):
        policy = _create_default_policy("/tmp/test-workspace")
        policy.execution_level = "strict"

        decision = policy.evaluate(_terminal_call("echo hello\n"))

        assert decision.action is GovernanceAction.ASK

    def test_explicit_deny_rule_still_applies(self):
        policy = _create_default_policy("/tmp/test-workspace")
        policy.user_rules.insert(
            0,
            GovernanceRule(
                match="TerminalInput(term_*)",
                action=GovernanceAction.DENY,
                reason="test deny",
            ),
        )

        decision = policy.evaluate(_terminal_call("echo hello\n"))

        assert decision.action is GovernanceAction.DENY


class _Governor:
    def __init__(self, workspace_dir):
        self.workspace_dir = workspace_dir
        self.policy = _create_default_policy(str(workspace_dir))

    def assert_policy(self, tc_spec):  # noqa: ANN001, ANN201
        decision = self.policy.evaluate(tc_spec)
        if decision.action is GovernanceAction.SANDBOX_FALLBACK:
            # Simulate an enabled/supported Windows sandbox. Before the fix,
            # TerminalInput reached this branch and the adapter injected this
            # object into write_stdin as an unsupported keyword argument.
            decision.sandbox_config = object()
        return decision

    def audit(self, tc_spec, decision):  # noqa: ANN001, ANN201
        del tc_spec, decision


class _TerminalManager:
    def __init__(self):
        self.calls = []

    async def interact(self, session_id, chars, **kwargs):  # noqa: ANN001
        self.calls.append((session_id, chars, kwargs))
        return SessionResult(
            session_id=session_id,
            chunk_id=f"{session_id}:1",
            running=True,
            exit_code=None,
            output="ready",
            original_bytes=5,
            omitted_bytes=0,
            next_cursor=5,
            wall_time_ms=1,
            tty=True,
            output_bytes=5,
            output_drained=True,
        )


@pytest.mark.asyncio
async def test_guarded_write_stdin_works_when_sandbox_is_enabled(tmp_path):
    manager = _TerminalManager()
    manager_token = current_terminal_manager.set(manager)
    tool = PolicyGuardedTool(
        write_stdin,
        governor=_Governor(tmp_path),
        request_context={},
    )
    try:
        permission = await tool.check_permissions(
            {"session_id": "term_demo", "chars": "echo hello\n"},
        )
        result = await tool(
            session_id="term_demo",
            chars="echo hello\n",
            yield_time_ms=0,
        )
    finally:
        current_terminal_manager.reset(manager_token)

    assert permission.behavior is PermissionBehavior.ALLOW
    assert tool._qp_sandbox_mode is False
    assert result.state is ToolResultState.SUCCESS
    assert result.metadata["session_id"] == "term_demo"
    assert manager.calls[0][0:2] == ("term_demo", "echo hello\n")


@pytest.mark.asyncio
async def test_adapter_fails_closed_for_unsupported_sandbox_parameter():
    async def control_tool(session_id: str):
        return session_id

    tool = PolicyGuardedTool(control_tool, governor=None, request_context={})
    tool._qp_sandbox_mode = True
    tool._qp_sandbox_config = object()

    result = await tool(session_id="term_demo")

    assert result.state is ToolResultState.DENIED
    assert result.metadata["error_code"] == "sandbox_config_unsupported"
