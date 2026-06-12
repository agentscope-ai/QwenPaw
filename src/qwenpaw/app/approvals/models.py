# -*- coding: utf-8 -*-
"""Shared approval data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ApprovalRequestSummary:
    """Generic approval summary for non-ToolGuard approval sources."""

    source_type: str
    name: str
    severity: str = "medium"
    findings_count: int = 1
    result_summary: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
