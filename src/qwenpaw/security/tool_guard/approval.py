# -*- coding: utf-8 -*-
"""Approval helpers for tool-guard mediated tool execution."""
from __future__ import annotations

import json
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import ToolGuardResult


class ApprovalDecision(str, Enum):
    """Possible approval outcomes for a guarded tool call."""

    APPROVED = "approved"
    DENIED = "denied"
    TIMEOUT = "timeout"


class ApprovalScope(str, Enum):
    """How widely an approved call should be remembered.

    Orthogonal to :class:`ApprovalDecision` — only meaningful when the
    decision is ``APPROVED``.
    """

    EXACT = "exact"  # record the literal target only
    SIMILAR = "similar"  # record the generalized pattern


def build_approval_description(
    tool_name: str,
    *,
    requested_description: str | None = None,
    language: str | None = None,
    max_length: int = 240,
) -> str:
    """Return a concise, user-facing purpose for an approval request.

    Callers may provide the model's short purpose through request context.
    Older callers do not have that field, so the fallback stays generic and
    avoids exposing a raw command as the approval summary.
    """
    description = " ".join(str(requested_description or "").split())
    if description:
        if len(description) > max_length:
            description = description[: max_length - 3].rstrip() + "..."
        return description

    name = " ".join(str(tool_name or "tool").split()) or "tool"
    language_key = str(language or "en").lower().replace("_", "-")
    if language_key.startswith("zh"):
        return f"使用 {name} 完成当前任务。"
    if language_key.startswith("ja"):
        return f"現在のタスクを完了するために {name} を使用します。"
    if language_key.startswith("ru"):
        return f"Использовать {name} для выполнения текущей задачи."
    if language_key.startswith("pt"):
        return f"Usar {name} para concluir a tarefa atual."
    if language_key.startswith("id"):
        return f"Gunakan {name} untuk menyelesaikan tugas saat ini."
    if language_key.startswith("vi"):
        return f"Dùng {name} để hoàn thành tác vụ hiện tại."
    return f"Use {name} to complete the current task."


def format_findings_summary(
    result: "ToolGuardResult",
    *,
    max_items: int = 3,
) -> str:
    """Format findings into a concise markdown summary."""
    if not result.findings:
        return "No specific risk rules matched."

    lines = []
    for finding in result.findings[:max_items]:
        lines.append(
            f"- [{finding.severity.value}] {finding.description}",
        )
        # Don't add remediation here - it will be added separately at the end

    # Calculate remaining based on findings processed, not lines added
    processed_count = min(max_items, len(result.findings))
    remaining = result.findings_count - processed_count
    if remaining > 0:
        lines.append(f"- ... and {remaining} more finding(s) omitted")
    return "\n".join(lines)


_SEVERITY_EMOJI = {
    "CRITICAL": "\U0001f534",
    "HIGH": "\U0001f534",
    "MEDIUM": "\U0001f7e1",
    "LOW": "\U0001f7e2",
    "INFO": "\u2139\ufe0f",
}


def format_channel_approval_body(
    result: "ToolGuardResult",
    *,
    max_items: int = 3,
) -> str:
    """Format a rich markdown body for channel approval notifications."""
    sev = result.max_severity.value
    emoji = _SEVERITY_EMOJI.get(sev, "")

    lines = [
        "\U0001f6e1\ufe0f **Approval Required**",
        "",
        f"\u2022 **Tool**: `{result.tool_name}`",
        f"\u2022 **Severity**: {emoji} {sev}",
        f"\u2022 **Findings**: {result.findings_count}",
    ]

    if result.findings:
        lines.append("")
        lines.append("**Risk Details:**")
        for finding in result.findings[:max_items]:
            lines.append(
                f"- [{finding.severity.value}] {finding.description}",
            )
        remaining = result.findings_count - min(
            max_items,
            len(result.findings),
        )
        if remaining > 0:
            lines.append(f"- ... and {remaining} more")
    else:
        lines.append("")
        lines.append("No specific risk rules matched.")

    if result.params:
        params_str = json.dumps(result.params, ensure_ascii=False, indent=2)
        if len(params_str) > 500:
            params_str = params_str[:497] + "..."
        lines.append("")
        lines.append("**Parameters:**")
        lines.append(f"```json\n{params_str}\n```")

    lines.append("")
    lines.append("\U0001f4a1 **Actions**")
    lines.append("- Approve: `/approval approve`")
    lines.append("- Deny: `/approval deny`")
    lines.append("- Cancel: `/approval cancel`")
    lines.append("- List: `/approval list`")

    return "\n".join(lines)
