# -*- coding: utf-8 -*-
"""Approval helpers for tool-guard mediated tool execution."""
from __future__ import annotations

import json
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...app.approvals.models import ApprovalRequestSummary
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


def format_approval_actions(request_id: str | None = None) -> list[str]:
    """Return the copy-paste commands that resolve one approval.

    A chat user may be looking at several pending requests at once, so the
    commands carry the short request id whenever one is known.  The handlers
    accept both forms (``/approval approve`` alone approves the queue head).
    """
    short = (request_id or "")[:16]
    suffix = f" {short}".rstrip()
    return [
        "\U0001f4a1 **Actions**",
        f"- Approve: `/approval approve{suffix}`",
        f"- Deny: `/approval deny{suffix}`",
        f"- Cancel: `/approval cancel{suffix}`",
        "- List: `/approval list`",
    ]


def format_summary_approval_body(
    summary: "ApprovalRequestSummary",
    *,
    request_id: str | None = None,
) -> str:
    """Format a channel approval body for non-ToolGuard approval sources.

    Driver-policy and plugin approvals used to push only their bare
    ``result_summary`` sentence ("Tool 'x' requires approval for call."),
    which told a chat user that something was waiting but not how to answer
    it.  This renders the same header/actions block the ToolGuard path uses.
    """
    sev = (summary.severity or "").upper()
    emoji = _SEVERITY_EMOJI.get(sev, "")

    lines = [
        "\U0001f6e1\ufe0f **Approval Required**",
        "",
        f"\u2022 **Tool**: `{summary.name}`",
        f"\u2022 **Severity**: {emoji} {sev}",
    ]
    if summary.result_summary:
        lines.append("")
        lines.append(summary.result_summary)
    lines.append("")
    lines.extend(format_approval_actions(request_id))
    return "\n".join(lines)


def format_channel_approval_body(
    result: "ToolGuardResult",
    *,
    max_items: int = 3,
    request_id: str | None = None,
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
    lines.extend(format_approval_actions(request_id))

    return "\n".join(lines)
