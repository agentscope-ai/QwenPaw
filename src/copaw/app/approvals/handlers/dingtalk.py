# -*- coding: utf-8 -*-
"""DingTalk approval handler."""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..base import ApprovalHandler

if TYPE_CHECKING:
    from ..service import PendingApproval
    from ....security.tool_guard.models import ToolGuardResult


class DingTalkApprovalHandler(ApprovalHandler):
    """Approval handler for the *dingtalk* channel.

    Uses the same HTTP-based approve/deny endpoints as the console
    handler.  When the user taps a link inside the DingTalk chat
    bubble, it opens the in-app browser which hits the HTTP endpoint
    and resolves the async future.

    The message format uses DingTalk-compatible Markdown (no HTML
    tags, simplified link syntax).
    """

    @property
    def channel_name(self) -> str:
        return "dingtalk"

    @property
    def needs_proactive_send(self) -> bool:  # noqa: D102
        return True

    def build_action_url(
        self,
        base_url: str,
        request_id: str,
        action: str,
    ) -> str:
        return f"{base_url}/api/approvals/{request_id}/{action}"

    def format_approval_message(
        self,
        tool_name: str,
        guard_result: "ToolGuardResult",
        pending: "PendingApproval",
        findings_text: str,
    ) -> str:
        # DingTalk Markdown supports a subset of standard Markdown.
        # Links are rendered as clickable text that opens in DingTalk's
        # built-in browser.
        return (
            f"**⚠️ 敏感工具需要审批**\n\n"
            f"> 工具: {tool_name}\n\n"
            f"> 最高风险等级: {guard_result.max_severity.value}\n\n"
            f"> 命中规则数: {guard_result.findings_count}\n\n"
            f"{findings_text}\n\n"
            f"[✅ 允许执行]({pending.approve_url})\n\n"
            f"[❌ 拒绝执行]({pending.deny_url})"
        )
