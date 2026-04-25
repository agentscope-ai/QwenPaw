# -*- coding: utf-8 -*-
# pylint:disable=protected-access
"""Handler for /approval command.

Manages tool guard approval requests through unified control commands.
"""

from __future__ import annotations

import logging
import time

from .base import BaseControlCommandHandler, ControlContext
from ...approvals import get_approval_service
from ....security.tool_guard.approval import ApprovalDecision

logger = logging.getLogger(__name__)


class ApprovalCommandHandler(BaseControlCommandHandler):
    """Handler for /approval command.

    Features:
    - Approve/deny pending tool executions
    - List all pending approvals
    - Cancel specific approval requests

    Usage:
        /approval approve [request_id]  # Approve specific or queue head
        /approval deny [request_id] [reason]  # Deny with optional reason
        /approval list                  # List all pending approvals
        /approval cancel <request_id>   # Cancel specific request
    """

    command_name = "/approval"

    async def handle(self, context: ControlContext) -> str:
        """Handle /approval command with various actions.

        Args:
            context: Control command context

        Returns:
            Response text (markdown formatted)
        """
        action = context.args.get("action", "approve")

        if action == "approve":
            return await self._handle_approve(context)
        elif action == "deny":
            return await self._handle_deny(context)
        elif action == "list":
            return await self._handle_list(context)
        elif action == "cancel":
            return await self._handle_cancel(context)
        else:
            return self._usage_hint()

    async def _handle_approve(self, context: ControlContext) -> str:
        """Approve a pending tool execution (supports cross-session)."""
        svc = get_approval_service()
        request_id = context.args.get("request_id")

        # If no request_id provided, get queue head (FIFO)
        if not request_id:
            pending = await svc.get_pending_by_session(context.session_id)
            if pending is None:
                return "❌ **无待审批工具**\n\n" "当前会话没有需要审批的工具调用。"
            request_id = pending.request_id

        # Get pending by request_id (supports cross-session)
        pending = await svc.get_request(request_id)
        if pending is None:
            return (
                f"❌ **审批请求不存在**\n\n"
                f"请求 ID: `{request_id[:16]}`\n\n"
                f"可能已被处理或已超时。"
            )

        # Permission check: can only approve own agent's requests
        if pending.agent_id != context.agent_id:
            return (
                f"❌ **权限不足**\n\n"
                f"无法审批其他Agent的工具请求。\n"
                f"- 请求所属Agent: `{pending.agent_id}`\n"
                f"- 当前Agent: `{context.agent_id}`"
            )

        # Resolve the Future to unblock waiting agent
        resolved = await svc.resolve_request(
            request_id,
            ApprovalDecision.APPROVED,
        )

        # Show cross-session hint if applicable
        cross_session_hint = ""
        if pending.session_id != context.session_id:
            if pending.root_session_id == pending.session_id:
                cross_session_hint = (
                    f"\n\n🔗 **跨Session操作**\n"
                    f"审批了其他会话的工具: `{pending.session_id[:8]}`"
                )
            else:
                cross_session_hint = (
                    f"\n\n🔗 **跨Session操作**\n"
                    f"审批了子Agent的工具 (Session: `{pending.session_id[:8]}`)"
                )

        return (
            f"✅ **工具已批准**\n\n"
            f"- 工具: `{resolved.tool_name}`\n"
            f"- 请求 ID: `{request_id[:16]}`\n"
            f"- 状态: 正在执行...{cross_session_hint}"
        )

    async def _handle_deny(self, context: ControlContext) -> str:
        """Deny a pending tool execution (supports cross-session)."""
        svc = get_approval_service()
        request_id = context.args.get("request_id")
        reason = context.args.get("reason", "用户拒绝")

        # If no request_id provided, get queue head
        if not request_id:
            pending = await svc.get_pending_by_session(context.session_id)
            if pending is None:
                return "❌ **无待审批工具**\n\n" "当前会话没有需要审批的工具调用。"
            request_id = pending.request_id

        # Get pending by request_id (supports cross-session)
        pending = await svc.get_request(request_id)
        if pending is None:
            return (
                f"❌ **审批请求不存在**\n\n"
                f"请求 ID: `{request_id[:16]}`\n\n"
                f"可能已被处理或已超时。"
            )

        # Permission check: can only deny own agent's requests
        if pending.agent_id != context.agent_id:
            return (
                f"❌ **权限不足**\n\n"
                f"无法拒绝其他Agent的工具请求。\n"
                f"- 请求所属Agent: `{pending.agent_id}`\n"
                f"- 当前Agent: `{context.agent_id}`"
            )

        # Resolve the Future to unblock waiting agent
        resolved = await svc.resolve_request(
            request_id,
            ApprovalDecision.DENIED,
        )

        # Show cross-session hint if applicable
        cross_session_hint = ""
        if pending.session_id != context.session_id:
            if pending.root_session_id == pending.session_id:
                cross_session_hint = (
                    f"\n\n🔗 **跨Session操作**\n"
                    f"拒绝了其他会话的工具: `{pending.session_id[:8]}`"
                )
            else:
                cross_session_hint = (
                    f"\n\n🔗 **跨Session操作**\n"
                    f"拒绝了子Agent的工具 (Session: `{pending.session_id[:8]}`)"
                )

        return (
            f"🚫 **工具已拒绝**\n\n"
            f"- 工具: `{resolved.tool_name}`\n"
            f"- 请求 ID: `{request_id[:16]}`\n"
            f"- 原因: {reason}{cross_session_hint}"
        )

    async def _handle_list(self, context: ControlContext) -> str:
        """List pending approvals.

        Supports:
            /approval list           # Current session (includes children)
            /approval list --all     # All sessions for this agent
            /approval list -a        # Same as --all (short form)
        """
        svc = get_approval_service()
        show_all = context.args.get("all", False)

        if show_all:
            # Query all pending approvals for this agent (all sessions)
            pending_list = await svc.get_all_pending_by_agent(
                context.agent_id,
            )
            header = "📋 **全局待审批工具列表** (所有会话)\n"
        else:
            # Default: query current root session (includes children)
            pending_list = await svc.get_pending_by_root_session(
                context.session_id,
            )
            header = "📋 **待审批工具列表** (当前会话)\n"

        if not pending_list:
            return "✅ **无待审批工具**\n\n当前无需要审批的工具调用。"

        lines = [header]
        for i, pending in enumerate(pending_list, 1):
            elapsed = int(time.time() - pending.created_at)
            severity_emoji = self._severity_emoji(pending.severity)

            # Show session info for cross-session cases
            session_info = ""
            if show_all or pending.session_id != context.session_id:
                is_sub = pending.root_session_id != pending.session_id
                if is_sub:
                    session_info = f" [子Session: `{pending.session_id[:8]}`]"
                else:
                    session_info = f" [Session: `{pending.session_id[:8]}`]"

            lines.append(
                f"{i}. `{pending.tool_name}` "
                f"{severity_emoji} `{pending.severity.upper()}` "
                f"- {elapsed}s 前{session_info}\n"
                f"   请求 ID: `{pending.request_id[:16]}`\n"
                f"   发现问题: {pending.findings_count} 个\n",
            )

        lines.append(
            "\n💡 **操作提示**\n"
            "- 批准: `/approval approve <request_id>` (支持跨session审批)\n"
            "- 拒绝: `/approval deny <request_id>`\n"
            "- 全局查看: `/approval list --all` 或 `/approval list -a`",
        )

        return "\n".join(lines)

    async def _handle_cancel(self, context: ControlContext) -> str:
        """Cancel a specific approval request."""
        request_id = context.args.get("request_id")

        if not request_id:
            return (
                "❌ **缺少参数**\n\n"
                "用法: `/approval cancel <request_id>`\n\n"
                "使用 `/approval list` 查看待审批列表及其 ID。"
            )

        svc = get_approval_service()
        resolved = await svc.resolve_request(
            request_id,
            ApprovalDecision.DENIED,
        )

        if resolved is None:
            return f"❌ **审批请求不存在**\n\n" f"请求 ID: `{request_id[:16]}`"

        return (
            f"✅ **审批请求已取消**\n\n"
            f"- 工具: `{resolved.tool_name}`\n"
            f"- 请求 ID: `{request_id[:16]}`"
        )

    @staticmethod
    def _severity_emoji(severity: str) -> str:
        """Get emoji for severity level."""
        severity_lower = severity.lower()
        if severity_lower in ("critical", "high"):
            return "🔴"
        elif severity_lower == "medium":
            return "🟡"
        else:  # low, info
            return "🟢"

    @staticmethod
    def _usage_hint() -> str:
        """Return usage hint for /approval command."""
        return (
            "**使用说明: /approval**\n\n"
            "管理工具审批请求\n\n"
            "**子命令**:\n"
            "- `approve [request_id]` - 批准工具执行\n"
            "- `deny [request_id] [reason]` - 拒绝工具执行\n"
            "- `list` - 列出所有待审批工具\n"
            "- `cancel <request_id>` - 取消指定审批\n\n"
            "**示例**:\n"
            "```\n"
            "/approval approve          # 批准队首工具\n"
            "/approval deny             # 拒绝队首工具\n"
            "/approval list             # 查看待审批列表\n"
            "/approval approve abc123   # 批准指定工具\n"
            "```"
        )


class ApproveCommandHandler(BaseControlCommandHandler):
    """Handler for /approve shorthand command.

    Provides convenient shortcut: /approve [request_id]
    Equivalent to: /approval approve [request_id]
    """

    command_name = "/approve"

    def __init__(self):
        """Initialize with shared approval handler."""
        self._approval_handler = ApprovalCommandHandler()

    async def handle(self, context: ControlContext) -> str:
        """Handle /approve command by delegating to approval handler.

        Args:
            context: Control command context

        Returns:
            Response text from approval handler
        """
        # Transform args: set action to approve
        context.args = {
            **context.args,
            "action": "approve",
        }

        # Delegate to approval handler
        return await self._approval_handler._handle_approve(context)


class DenyCommandHandler(BaseControlCommandHandler):
    """Handler for /deny shorthand command.

    Provides convenient shortcut: /deny [request_id] [reason]
    Equivalent to: /approval deny [request_id] [reason]
    """

    command_name = "/deny"

    def __init__(self):
        """Initialize with shared approval handler."""
        self._approval_handler = ApprovalCommandHandler()

    async def handle(self, context: ControlContext) -> str:
        """Handle /deny command by delegating to approval handler.

        Args:
            context: Control command context

        Returns:
            Response text from approval handler
        """
        # Parse args for /deny command
        # Format: /deny [request_id] [reason...]
        raw_args = context.args.get("_raw_args", "").strip()
        parts = raw_args.split(maxsplit=1)

        new_args = {"action": "deny"}

        if parts:
            # First part is request_id (optional)
            new_args["request_id"] = parts[0]

        if len(parts) > 1:
            # Remaining parts are reason
            new_args["reason"] = parts[1]

        context.args = new_args

        # Delegate to approval handler
        return await self._approval_handler._handle_deny(context)
