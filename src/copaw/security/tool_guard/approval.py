# -*- coding: utf-8 -*-
"""Approval helpers for tool-guard mediated tool execution."""
from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import ToolGuardResult


class ApprovalDecision(str, Enum):
    """Possible approval outcomes for a guarded tool call."""

    APPROVED = "approved"
    DENIED = "denied"
    TIMEOUT = "timeout"


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
    remaining = result.findings_count - len(lines)
    if remaining > 0:
        lines.append(f"- ... and {remaining} more finding(s) omitted")
    return "\n".join(lines)
