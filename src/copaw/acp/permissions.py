# -*- coding: utf-8 -*-
"""ACP permission handling built on top of the existing approval service."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from ..app.approvals import get_approval_service
from ..security.tool_guard.guardians.file_guardian import (
    load_sensitive_files_from_config,
)
from ..security.tool_guard.approval import ApprovalDecision
from ..security.tool_guard.models import (
    GuardFinding,
    GuardSeverity,
    GuardThreatCategory,
    ToolGuardResult,
)
from ..security.tool_guard.path_utils import (
    is_within_root,
    matches_sensitive_path,
    resolve_path,
)
from .i18n import build_i18n_metadata
from .policy import READ_ONLY_TOOL_KINDS, is_read_only_tool


@dataclass
class ACPApprovalSummary:
    """Structured approval summary for i18n rendering on frontend.

    Contains all data needed for the frontend to construct localized
    approval messages, avoiding hardcoded text in the backend.
    """

    harness: str
    tool_name: str
    tool_kind: str
    target: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "type": "acp_approval_summary",
            "harness": self.harness,
            "tool_name": self.tool_name,
            "tool_kind": self.tool_kind,
            "target": self.target,
        }


logger = logging.getLogger(__name__)

AUTO_ALLOW_KINDS = READ_ONLY_TOOL_KINDS
ALLOW_OPTION_HINTS = ("allow", "approve", "accept")
REJECT_OPTION_HINTS = ("reject", "deny", "cancel")


@dataclass
class ACPPermissionDecision:
    """Resolved permission result to be returned to the harness."""

    approved: bool
    result: dict[str, Any]
    pending_request_id: str | None = None
    summary: dict[str, Any] | str = ""


def build_prompt_approval_artifacts(
    *,
    harness: str,
    prompt_text: str,
    cwd: str,
) -> tuple[dict[str, Any], ToolGuardResult, str]:
    """Build approval metadata for a host-side ACP prompt preapproval.

    This is used when a harness cannot be trusted to request permission
    callbacks before performing dangerous actions. CoPaw pauses before the
    ACP turn starts and requires `/approve` to replay the original prompt.
    """
    adapter = ACPPermissionAdapter(cwd=cwd, require_approval=True)
    tool_name = f"ACP/{harness}"
    tool_kind = "external_prompt"
    tool_call = {
        "name": tool_name,
        "kind": tool_kind,
        "harness": harness,
        "description": prompt_text,
        "target": cwd,
        "input": {
            "prompt": prompt_text,
            "cwd": cwd,
        },
    }
    summary = adapter._build_summary(  # pylint: disable=protected-access
        tool_call=tool_call,
        tool_name=tool_name,
        tool_kind=tool_kind,
    )
    result = (
        adapter._build_tool_guard_result(  # pylint: disable=protected-access
            tool_name=tool_name,
            tool_kind=tool_kind,
            summary=summary,
            tool_call=tool_call,
        )
    )
    waiting_text = (
        "⏳ Waiting for approval / 等待审批\n\n"
        f"Harness: {harness}\n"
        f"Request: {prompt_text}\n"
        f"CWD: {cwd}\n\n"
        "Type `/approve` to approve, or send any other message to deny.\n"
        "输入 `/approve` 批准执行，或发送任意消息拒绝。"
    )
    return summary, result, waiting_text


class ACPPermissionAdapter:
    """Translate ACP permission requests into CoPaw approval decisions."""

    def __init__(self, cwd: str, *, require_approval: bool = False):
        self.cwd = cwd
        self.require_approval = require_approval

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
        tool_name = str(
            tool_call.get("name")
            or request_payload.get("title")
            or "external-agent",
        )
        tool_kind = str(
            tool_call.get("kind") or request_payload.get("kind") or "",
        ).lower()
        options = (
            request_payload.get("options") or tool_call.get("options") or []
        )
        summary = self._build_summary(
            tool_call=tool_call,
            tool_name=tool_name,
            tool_kind=tool_kind,
        )

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
            logger.info(
                "Auto-approving ACP permission: %s (%s)",
                tool_name,
                tool_kind,
            )
            return ACPPermissionDecision(
                approved=True,
                result=self._selected_result(allow_option),
                summary=summary,
            )

        if not self.require_approval:
            logger.info(
                "Allowing ACP permission without approval: %s (%s)",
                tool_name,
                tool_kind,
            )
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
            result=self._selected_result(
                allow_option if approved else reject_option,
            ),
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

    def _should_auto_approve(
        self,
        tool_kind: str,
        tool_call: dict[str, Any],
    ) -> bool:
        if not is_read_only_tool(tool_call.get("name"), tool_kind):
            return False

        target = self._extract_target_path(tool_call)
        if target is None:
            return False

        try:
            resolved_target = resolve_path(target, self.cwd)
        except Exception:  # pragma: no cover
            logger.warning(
                "Failed to resolve ACP permission target: %s",
                target,
                exc_info=True,
            )
            return False

        if not is_within_root(resolved_target, self.cwd):
            return False

        return not matches_sensitive_path(
            resolved_target,
            load_sensitive_files_from_config(),
            base_dir=self.cwd,
        )

    @staticmethod
    def _extract_target_path(tool_call: dict[str, Any]) -> str | None:
        """Extract a path-like target for ACP read/search style requests."""
        candidate_sources = [tool_call]
        nested_input = tool_call.get("input")
        if isinstance(nested_input, dict):
            candidate_sources.append(nested_input)

        for source in candidate_sources:
            for key in ("path", "target"):
                value = source.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return None

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
                str(option.get(key) or "") for key in ("kind", "title", "id")
            ).lower()
            if any(hint in values for hint in hints):
                return option
        return options[0] if fallback_to_first and options else None

    def _selected_result(
        self,
        option: dict[str, Any] | None,
    ) -> dict[str, Any]:
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
    ) -> dict[str, Any]:
        """Build structured summary for frontend i18n rendering.

        Returns a dictionary with all data needed for the frontend to
        construct localized approval messages, avoiding hardcoded text.
        """
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

        harness = tool_call.get("harness") or "external-agent"

        summary = ACPApprovalSummary(
            harness=str(harness),
            tool_name=tool_name,
            tool_kind=tool_kind or "unknown",
            target=target_text or None,
        )
        return summary.to_dict()

    def _build_tool_guard_result(
        self,
        *,
        tool_name: str,
        tool_kind: str,
        summary: dict[str, Any] | str,
        tool_call: dict[str, Any],
    ) -> ToolGuardResult:
        description = (
            summary
            if isinstance(summary, str)
            else str(summary.get("tool_name") or summary)
        )
        finding = GuardFinding(
            id="acp_permission",
            rule_id="acp_permission_request",
            category=GuardThreatCategory.CODE_EXECUTION,
            severity=GuardSeverity.HIGH,
            title="acp.approval.requestTitle",
            description=description,
            tool_name=tool_name,
            param_name="tool_call",
            matched_value=str(tool_call)[:200],
            guardian="acp_permission_adapter",
            metadata=build_i18n_metadata("acp.approval.requestTitle"),
        )
        return ToolGuardResult(
            tool_name=tool_name,
            params={"tool_kind": tool_kind, "tool_call": tool_call},
            findings=[finding],
            guardians_used=["acp_permission_adapter"],
        )
