# -*- coding: utf-8 -*-
"""Tests for the /approval control command handler.

Covers _severity_emoji, handle() action dispatch, and the
approve/deny/list/cancel branches (empty queue, not-found, permission
guard, success, cross-session hint), which the first approval backfill
pass left uncovered.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.runtime.commands.control import approval_handler as ah
from qwenpaw.runtime.commands.control.base import ControlContext
from qwenpaw.security.tool_guard.approval import (
    ApprovalDecision,
    ApprovalScope,
)


def _context(args=None):
    return ControlContext(
        workspace=SimpleNamespace(),
        payload=None,
        channel=None,
        session_id="sess-1",
        user_id="u1",
        agent_id="agent-a",
        args=args or {},
    )


def _pending(
    request_id="req-0001",
    session_id="sess-1",
    root_session_id="sess-1",
    agent_id="agent-a",
    severity="medium",
    tool_name="Bash",
    findings_count=1,
):
    return SimpleNamespace(
        request_id=request_id,
        session_id=session_id,
        root_session_id=root_session_id,
        agent_id=agent_id,
        tool_name=tool_name,
        severity=severity,
        findings_count=findings_count,
        created_at=time.time() - 5,
    )


@pytest.fixture
def handler():
    return ah.ApprovalCommandHandler()


@pytest.fixture
def mock_service(monkeypatch):
    svc = SimpleNamespace(
        get_pending_by_session=AsyncMock(return_value=None),
        get_request=AsyncMock(return_value=None),
        resolve_request=AsyncMock(return_value=None),
        get_all_pending_by_agent=AsyncMock(return_value=[]),
        get_pending_by_root_session=AsyncMock(return_value=[]),
        get_pending_by_root_session_children=AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(ah, "get_approval_service", lambda: svc)
    return svc


# ---------------------------------------------------------------------------
# _severity_emoji
# ---------------------------------------------------------------------------


class TestSeverityEmoji:
    def test_critical_high_red(self):
        assert ah.ApprovalCommandHandler._severity_emoji("critical") == "🔴"
        assert ah.ApprovalCommandHandler._severity_emoji("HIGH") == "🔴"

    def test_medium_yellow(self):
        assert ah.ApprovalCommandHandler._severity_emoji("medium") == "🟡"

    def test_low_info_green(self):
        assert ah.ApprovalCommandHandler._severity_emoji("low") == "🟢"
        assert ah.ApprovalCommandHandler._severity_emoji("info") == "🟢"


# ---------------------------------------------------------------------------
# handle() dispatch
# ---------------------------------------------------------------------------


class TestHandleDispatch:
    async def test_unknown_action_returns_usage(self, handler, mock_service):
        ctx = _context({"action": "bogus"})
        result = await handler.handle(ctx)
        assert "/approval" in result

    async def test_default_action_is_approve(self, handler, mock_service):
        ctx = _context({})
        result = await handler.handle(ctx)
        # no pending -> approve reports empty queue
        assert "无待审批工具" in result

    async def test_list_action_dispatches(self, handler, mock_service):
        ctx = _context({"action": "list"})
        result = await handler.handle(ctx)
        assert "无待审批工具" in result


# ---------------------------------------------------------------------------
# _handle_approve
# ---------------------------------------------------------------------------


class TestHandleApprove:
    async def test_no_pending_returns_empty_message(
        self,
        handler,
        mock_service,
    ):
        ctx = _context({"action": "approve"})
        result = await handler._handle_approve(ctx)
        assert "无待审批工具" in result

    async def test_not_found_returns_error(self, handler, mock_service):
        ctx = _context({"action": "approve", "request_id": "gone"})
        result = await handler._handle_approve(ctx)
        assert "审批请求不存在" in result

    async def test_permission_guard_blocks_other_agent(
        self,
        handler,
        mock_service,
    ):
        pending = _pending(agent_id="agent-other")
        mock_service.get_request.return_value = pending
        ctx = _context({"action": "approve", "request_id": "req-0001"})
        result = await handler._handle_approve(ctx)
        assert "权限不足" in result
        mock_service.resolve_request.assert_not_awaited()

    async def test_success_approves(self, handler, mock_service):
        pending = _pending()
        mock_service.get_request.return_value = pending
        mock_service.resolve_request.return_value = pending
        ctx = _context({"action": "approve", "request_id": "req-0001"})
        result = await handler._handle_approve(ctx)
        assert "工具已批准" in result
        assert "Bash" in result
        mock_service.resolve_request.assert_awaited_once()
        call_kwargs = mock_service.resolve_request.await_args
        assert call_kwargs.args[1] == ApprovalDecision.APPROVED

    async def test_queue_head_used_when_no_id(self, handler, mock_service):
        head = _pending(request_id="head-id")
        mock_service.get_pending_by_session.return_value = head
        mock_service.get_request.return_value = head
        mock_service.resolve_request.return_value = head
        ctx = _context({"action": "approve"})
        result = await handler._handle_approve(ctx)
        assert "工具已批准" in result

    async def test_cross_session_hint_shown(self, handler, mock_service):
        pending = _pending(session_id="other-sess")
        mock_service.get_request.return_value = pending
        mock_service.resolve_request.return_value = pending
        ctx = _context({"action": "approve", "request_id": "req-0001"})
        result = await handler._handle_approve(ctx)
        assert "跨Session操作" in result

    async def test_pattern_scope_similar(self, handler, mock_service):
        pending = _pending()
        mock_service.get_request.return_value = pending
        mock_service.resolve_request.return_value = pending
        ctx = _context(
            {"action": "approve", "request_id": "r", "pattern": True},
        )
        await handler._handle_approve(ctx)
        call_kwargs = mock_service.resolve_request.await_args.kwargs
        assert call_kwargs.get("scope") == ApprovalScope.SIMILAR

    async def test_exact_scope_exact(self, handler, mock_service):
        pending = _pending()
        mock_service.get_request.return_value = pending
        mock_service.resolve_request.return_value = pending
        ctx = _context({"action": "approve", "request_id": "r", "exact": True})
        await handler._handle_approve(ctx)
        call_kwargs = mock_service.resolve_request.await_args.kwargs
        assert call_kwargs.get("scope") == ApprovalScope.EXACT


# ---------------------------------------------------------------------------
# _handle_deny
# ---------------------------------------------------------------------------


class TestHandleDeny:
    async def test_no_pending_returns_empty_message(
        self,
        handler,
        mock_service,
    ):
        ctx = _context({"action": "deny"})
        result = await handler._handle_deny(ctx)
        assert "无待审批工具" in result

    async def test_success_denies_with_default_reason(
        self,
        handler,
        mock_service,
    ):
        pending = _pending()
        mock_service.get_request.return_value = pending
        mock_service.resolve_request.return_value = pending
        ctx = _context({"action": "deny", "request_id": "r"})
        result = await handler._handle_deny(ctx)
        assert "工具已拒绝" in result
        assert "用户拒绝" in result
        assert mock_service.resolve_request.await_args.args[1] == (
            ApprovalDecision.DENIED
        )

    async def test_custom_reason_shown(self, handler, mock_service):
        pending = _pending()
        mock_service.get_request.return_value = pending
        mock_service.resolve_request.return_value = pending
        ctx = _context({"action": "deny", "request_id": "r", "reason": "太危险"})
        result = await handler._handle_deny(ctx)
        assert "太危险" in result

    async def test_permission_guard_blocks_other_agent(
        self,
        handler,
        mock_service,
    ):
        pending = _pending(agent_id="agent-other")
        mock_service.get_request.return_value = pending
        ctx = _context({"action": "deny", "request_id": "r"})
        result = await handler._handle_deny(ctx)
        assert "权限不足" in result


# ---------------------------------------------------------------------------
# _handle_list
# ---------------------------------------------------------------------------


class TestHandleList:
    async def test_empty_list_message(self, handler, mock_service):
        ctx = _context({"action": "list"})
        result = await handler._handle_list(ctx)
        assert "无待审批工具" in result

    async def test_current_session_list(self, handler, mock_service):
        mock_service.get_pending_by_root_session.return_value = [
            _pending(severity="high", tool_name="Bash"),
        ]
        ctx = _context({"action": "list"})
        result = await handler._handle_list(ctx)
        assert "当前会话" in result
        assert "Bash" in result
        assert "HIGH" in result
        assert "🔴" in result

    async def test_all_sessions_list(self, handler, mock_service):
        mock_service.get_all_pending_by_agent.return_value = [
            _pending(session_id="other"),
        ]
        ctx = _context({"action": "list", "all": True})
        result = await handler._handle_list(ctx)
        assert "所有会话" in result
        assert "Bash" in result

    async def test_subsession_annotated(self, handler, mock_service):
        mock_service.get_pending_by_root_session.return_value = [
            _pending(session_id="child-sess"),  # != context session
        ]
        ctx = _context({"action": "list"})
        result = await handler._handle_list(ctx)
        assert "子Session" in result or "Session" in result


# ---------------------------------------------------------------------------
# _handle_cancel
# ---------------------------------------------------------------------------


class TestHandleCancel:
    async def test_missing_id_returns_usage(self, handler, mock_service):
        ctx = _context({"action": "cancel"})
        result = await handler._handle_cancel(ctx)
        assert "缺少参数" in result

    async def test_not_found_returns_error(self, handler, mock_service):
        ctx = _context({"action": "cancel", "request_id": "gone"})
        result = await handler._handle_cancel(ctx)
        assert "审批请求不存在" in result

    async def test_success_cancels(self, handler, mock_service):
        pending = _pending()
        mock_service.resolve_request.return_value = pending
        ctx = _context({"action": "cancel", "request_id": "req-0001"})
        result = await handler._handle_cancel(ctx)
        assert "审批请求已取消" in result
        assert "Bash" in result
        assert mock_service.resolve_request.await_args.args[1] == (
            ApprovalDecision.DENIED
        )


# ---------------------------------------------------------------------------
# ApproveCommandHandler / DenyCommandHandler shorthand
# ---------------------------------------------------------------------------


class TestShorthandHandlers:
    async def test_approve_short_delegates(self, monkeypatch):
        short = ah.ApproveCommandHandler()
        ctx = _context({"_raw_args": "req-42 --exact"})
        captured = {}

        async def fake_approve(context):
            captured["args"] = context.args
            return "ok"

        monkeypatch.setattr(
            short._approval_handler,
            "_handle_approve",
            fake_approve,
        )
        result = await short.handle(ctx)
        assert result == "ok"
        assert captured["args"]["action"] == "approve"
        assert captured["args"]["request_id"] == "req-42"
        assert captured["args"]["exact"] is True

    async def test_approve_short_pattern_flag(self, monkeypatch):
        short = ah.ApproveCommandHandler()
        ctx = _context({"_raw_args": "--pattern"})
        captured = {}

        async def fake_approve(context):
            captured["args"] = context.args
            return "ok"

        monkeypatch.setattr(
            short._approval_handler,
            "_handle_approve",
            fake_approve,
        )
        await short.handle(ctx)
        assert captured["args"]["pattern"] is True
        assert "request_id" not in captured["args"]

    async def test_deny_short_delegates(self, monkeypatch):
        short = ah.DenyCommandHandler()
        ctx = _context({"_raw_args": "req-7 some reason"})
        captured = {}

        async def fake_deny(context):
            captured["args"] = context.args
            return "denied"

        monkeypatch.setattr(
            short._approval_handler,
            "_handle_deny",
            fake_deny,
        )
        result = await short.handle(ctx)
        assert result == "denied"
        assert captured["args"]["action"] == "deny"
        assert captured["args"]["request_id"] == "req-7"
