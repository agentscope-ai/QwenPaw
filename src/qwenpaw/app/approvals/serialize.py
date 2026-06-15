# -*- coding: utf-8 -*-
"""Serialize pending approvals for Console / API consumers."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .service import PendingApproval


def pending_approval_to_console_dict(pending: "PendingApproval") -> dict[str, Any]:
    """Shape used by ``GET /console/push-messages`` pending_approvals entries."""
    file_baseline_write = pending.extra.get("file_baseline_write")
    tool_params = pending.extra.get("tool_call", {}).get("input", {})
    if not isinstance(tool_params, dict):
        tool_params = {}

    if isinstance(file_baseline_write, dict):
        tool_params = {
            **tool_params,
            "file_path": file_baseline_write.get("relative_path") or tool_params.get("file_path"),
            "operation": file_baseline_write.get("operation") or tool_params.get("operation"),
            "current_content": file_baseline_write.get("current_content"),
            "proposed_content": (
                file_baseline_write.get("proposed_content")
                or file_baseline_write.get("content_preview")
            ),
            "old_sha256": file_baseline_write.get("old_sha256"),
            "new_sha256": file_baseline_write.get("new_sha256"),
        }

    payload: dict[str, Any] = {
        "request_id": pending.request_id,
        "session_id": pending.session_id,
        "root_session_id": pending.root_session_id,
        "owner_agent_id": pending.owner_agent_id,
        "agent_id": pending.agent_id,
        "tool_name": pending.tool_name,
        "severity": pending.severity,
        "findings_count": pending.findings_count,
        "findings_summary": pending.result_summary,
        "tool_params": tool_params,
        "created_at": pending.created_at,
        "timeout_seconds": pending.timeout_seconds,
    }
    if isinstance(file_baseline_write, dict):
        payload["approval_kind"] = "file_baseline_write"
        payload["file_baseline_write"] = file_baseline_write
    return payload
