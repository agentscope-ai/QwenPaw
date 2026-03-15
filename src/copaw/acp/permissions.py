# -*- coding: utf-8 -*-
"""ACP permission handling built on top of the existing approval service."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from ..app.approvals import get_approval_service
from ..security.tool_guard.approval import ApprovalDecision
from ..security.tool_guard.models import (
    GuardFinding,
    GuardSeverity,
    GuardThreatCategory,
    ToolGuardResult,
)

logger = logging.getLogger(__name__)

AUTO_ALLOW_KINDS = {
    "read",
    "search",
    "find",
    "list",
    "glob",
    "grep",
}
ALLOW_OPTION_HINTS = ("allow", "approve", "accept")
REJECT_OPTION_HINTS = ("reject", "deny", "cancel")


@dataclass
class ACPPermissionDecision:
    """Resolved permission result to be returned to the harness."""

    approved: bool
    result: dict[str, Any]
    pending_request_id: str | None = None
    summary: str = ""


class ACPPermissionAdapter:
    """Translate ACP permission requests into CoPaw approval decisions."""

    def __init__(self, cwd: str):
        self.cwd = cwd

    async def resolve_permission(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        harness: str,
        request_payload: dict[str, Any],
    ) -> ACPPermissionDecision:
        """Resolve one ACP permission request."""
        tool_call = self._extract_tool_call(request_payload)
        tool_name = str(tool_call.get("name") or request_payload.get("title") or "external-agent")
        tool_kind = str(tool_call.get("kind") or request_payload.get("kind") or "").lower()
        options = request_payload.get("options") or tool_call.get("options") or []
        summary = self._build_summary(tool_call=tool_call, tool_name=tool_name, tool_kind=tool_kind)

        allow_option = self._pick_option(
            options,
            ALLOW_OPTION_HINTS,
            fallback_to_first=True,
        )
        reject_option = self._pick_option(
            options,
            REJECT_OPTION_HINTS,
            fallback_to_first=False,
        )

        if self._should_auto_approve(tool_kind, tool_call):
            logger.info("Auto-approving ACP permission: %s (%s)", tool_name, tool_kind)
            return ACPPermissionDecision(
                approved=True,
                result=self._selected_result(allow_option),
                summary=summary,
            )

        pending = await get_approval_service().create_pending(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            tool_name=tool_name,
            result=self._build_tool_guard_result(
                tool_name=tool_name,
                tool_kind=tool_kind or "unknown",
                summary=summary,
                tool_call=tool_call,
            ),
            extra={
                "tool_call": tool_call,
                "harness": harness,
                "approval_message": summary,
                "allow_option": allow_option,
                "reject_option": reject_option,
            },
        )

        decision = await asyncio.shield(pending.future)
        approved = decision == ApprovalDecision.APPROVED
        if decision == ApprovalDecision.TIMEOUT:
            approved = False

        return ACPPermissionDecision(
            approved=approved,
            result=self._selected_result(allow_option if approved else reject_option),
            pending_request_id=pending.request_id,
            summary=summary,
        )

    def _extract_tool_call(self, payload: dict[str, Any]) -> dict[str, Any]:
        if isinstance(payload.get("toolCall"), dict):
            return payload["toolCall"]
        if isinstance(payload.get("tool_call"), dict):
            return payload["tool_call"]
        if isinstance(payload.get("content"), dict):
            return payload["content"]
        return payload

    def _should_auto_approve(self, tool_kind: str, tool_call: dict[str, Any]) -> bool:
        if tool_kind in AUTO_ALLOW_KINDS:
            target = str(
                tool_call.get("path")
                or tool_call.get("target")
                or tool_call.get("command")
                or "",
            )
            return not target.startswith("/") or target.startswith(self.cwd)
        return False

    def _pick_option(
        self,
        options: list[dict[str, Any]],
        hints: tuple[str, ...],
        *,
        fallback_to_first: bool,
    ) -> dict[str, Any] | None:
        for option in options:
            if not isinstance(option, dict):
                continue
            values = " ".join(
                str(option.get(key) or "")
                for key in ("kind", "title", "id")
            ).lower()
            if any(hint in values for hint in hints):
                return option
        return options[0] if fallback_to_first and options else None

    def _selected_result(self, option: dict[str, Any] | None) -> dict[str, Any]:
        if option is None:
            return {"outcome": {"outcome": "cancelled"}}

        option_id = option.get("id") or option.get("kind") or "selected"
        return {
            "outcome": {
                "outcome": "selected",
                "optionId": option_id,
            },
        }

    def _build_summary(
        self,
        *,
        tool_call: dict[str, Any],
        tool_name: str,
        tool_kind: str,
    ) -> str:
        target = (
            tool_call.get("path")
            or tool_call.get("target")
            or tool_call.get("command")
            or tool_call.get("description")
            or tool_call.get("input")
            or ""
        )
        target_text = str(target).strip()
        if len(target_text) > 240:
            target_text = target_text[:240] + "..."

        lines = [
            f"等待外部 Agent 权限确认 / Waiting for external agent approval",
            "",
            f"- Harness: `{tool_call.get('harness') or 'external-agent'}`",
            f"- Tool: `{tool_name}`",
            f"- Kind: `{tool_kind or 'unknown'}`",
        ]
        if target_text:
            lines.append(f"- Target: `{target_text}`")
        lines.extend(
            [
                "",
                "可以在聊天里输入 `/approve` 批准，或发送任意消息拒绝。",
                "You can type `/approve` to allow it, or send any other message to deny it.",
            ],
        )
        return "\n".join(lines)

    def _build_tool_guard_result(
        self,
        *,
        tool_name: str,
        tool_kind: str,
        summary: str,
        tool_call: dict[str, Any],
    ) -> ToolGuardResult:
        finding = GuardFinding(
            id="acp_permission",
            rule_id="acp_permission_request",
            category=GuardThreatCategory.CODE_EXECUTION,
            severity=GuardSeverity.HIGH,
            title="External agent requested approval",
            description=summary,
            tool_name=tool_name,
            param_name="tool_call",
            matched_value=str(tool_call)[:200],
            guardian="acp_permission_adapter",
        )
        return ToolGuardResult(
            tool_name=tool_name,
            params={"tool_kind": tool_kind, "tool_call": tool_call},
            findings=[finding],
            guardians_used=["acp_permission_adapter"],
        )
