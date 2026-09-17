# -*- coding: utf-8 -*-
"""Tests for root-session approval fallback to spawned subagents."""

from __future__ import annotations

from types import SimpleNamespace

from qwenpaw.app.approvals.service import ApprovalService
from qwenpaw.runtime.commands.control.approval_handler import (
    ApprovalCommandHandler,
)
from qwenpaw.runtime.commands.control.base import ControlContext
from qwenpaw.security.tool_guard.models import (
    GuardFinding,
    GuardSeverity,
    GuardThreatCategory,
    ToolGuardResult,
)


def _result() -> ToolGuardResult:
    return ToolGuardResult(
        tool_name="Bash",
        params={},
        findings=[
            GuardFinding(
                id="f1",
                rule_id="r1",
                category=GuardThreatCategory.CODE_EXECUTION,
                severity=GuardSeverity.HIGH,
                title="risk",
                description="risk",
                tool_name="Bash",
            ),
        ],
    )


def _context() -> ControlContext:
    return ControlContext(
        workspace=SimpleNamespace(),
        payload=None,
        channel=None,
        session_id="root-session",
        user_id="u1",
        agent_id="agent-a",
        args={},
    )


async def test_approve_without_id_only_falls_back_to_spawned_child(
    monkeypatch,
):
    """Root approval skips unmarked children and resolves spawned children."""
    svc = ApprovalService()
    unmarked = await svc.create_pending(
        session_id="other-child-session",
        root_session_id="root-session",
        owner_agent_id="agent-a",
        user_id="u1",
        channel="console",
        agent_id="agent-a",
        tool_name="Bash",
        result=_result(),
    )
    pending = await svc.create_pending(
        session_id="child-session",
        root_session_id="root-session",
        owner_agent_id="agent-a",
        user_id="u1",
        channel="console",
        agent_id="agent-a",
        tool_name="Bash",
        result=_result(),
        extra={"_spawn_subagent": True},
    )
    monkeypatch.setattr(
        "qwenpaw.runtime.commands.control.approval_handler."
        "get_approval_service",
        lambda: svc,
    )

    response = await ApprovalCommandHandler().handle(_context())

    assert "工具已批准" in response
    assert await svc.get_request(pending.request_id) is None
    assert await svc.get_request(unmarked.request_id) is unmarked
