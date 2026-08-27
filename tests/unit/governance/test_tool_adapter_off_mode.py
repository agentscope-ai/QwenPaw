# -*- coding: utf-8 -*-
"""Regression tests for OFF-mode governance evaluation."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from agentscope.permission import PermissionBehavior

from qwenpaw.governance import tool_adapter
from qwenpaw.governance.policy import (
    GovernanceAction,
    ToolCallSpec,
    _create_default_policy,
)


class _Governor:
    def __init__(self, workspace: str) -> None:
        self.policy = _create_default_policy(workspace, workspace)
        self.audit_calls: list[tuple[ToolCallSpec, object]] = []
        self.assert_calls: list[ToolCallSpec] = []

    def assert_policy(self, spec: ToolCallSpec):
        self.assert_calls.append(spec)
        return self.policy.evaluate(spec)

    def audit(self, spec: ToolCallSpec, decision: object) -> None:
        self.audit_calls.append((spec, decision))


def _tool(governor: _Governor, target: str, level: str = "off"):
    spec = ToolCallSpec("Read", target, "agent", "session")
    return SimpleNamespace(
        name="read_file",
        _qp_governor=governor,
        _qp_request_context={
            "approval_level": level,
            "agent_id": "agent",
            "session_id": "session",
        },
        _build_tc_spec=lambda: spec,
    )


@pytest.mark.parametrize("level", ["strict", "smart", "auto", "off"])
def test_all_levels_evaluate_builtin_sensitive_rules(
    tmp_path,
    monkeypatch,
    level,
):
    """Builtin sensitive-resource ASK rules apply at every level."""
    governor = _Governor(str(tmp_path))
    tool = _tool(governor, "/home/user/.ssh/id_test", level)

    async def fake_ask(**_kwargs):
        return SimpleNamespace(
            behavior=PermissionBehavior.ASK,
            message="approval requested",
        )

    monkeypatch.setattr(tool_adapter, "_ask_user_approval", fake_ask)
    decision = asyncio.run(
        tool_adapter._policy_tool_check_permissions(tool, {}),
    )

    assert decision.behavior == PermissionBehavior.ASK
    assert len(governor.assert_calls) == 1
    assert governor.audit_calls
    policy_decision = governor.audit_calls[0][1]
    assert policy_decision.action is GovernanceAction.ASK
    assert policy_decision.source == "builtin_rules"
    assert policy_decision.reason == "SSH credentials directory"


def test_off_still_auto_allows_clean_calls(tmp_path):
    """OFF remains pass-through for a call with no policy hit."""
    governor = _Governor(str(tmp_path))
    tool = _tool(governor, "/tmp/ordinary.txt")

    decision = asyncio.run(
        tool_adapter._policy_tool_check_permissions(tool, {}),
    )

    assert decision.behavior == PermissionBehavior.ALLOW
    assert len(governor.assert_calls) == 1
    assert governor.audit_calls
    assert governor.audit_calls[0][1].action is GovernanceAction.ALLOW
