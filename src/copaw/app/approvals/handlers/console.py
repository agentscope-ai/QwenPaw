# -*- coding: utf-8 -*-
"""Console (web frontend) approval handler."""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..base import ApprovalHandler

if TYPE_CHECKING:
    from ..service import PendingApproval
    from ....security.tool_guard.models import ToolGuardResult


class ConsoleApprovalHandler(ApprovalHandler):
    """Approval handler for the *console* (web frontend) channel.

    Generates HTTP GET links that render a styled HTML response page
    when the user clicks *Allow* or *Deny* in the chat UI.
    """

    @property
    def channel_name(self) -> str:
        return "console"

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
        return (
            f"⚠️ Sensitive tool requires approval\n\n"
            f"- Tool: `{tool_name}`\n"
            f"- Max severity: `{guard_result.max_severity.value}`\n"
            f"- Findings: `{guard_result.findings_count}`\n\n"
            f"{findings_text}\n\n"
            f"[✅ Allow]({pending.approve_url})　"
            f"[❌ Deny]({pending.deny_url})"
        )
