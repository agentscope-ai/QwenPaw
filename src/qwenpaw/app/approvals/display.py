# -*- coding: utf-8 -*-
"""Presentation helpers for approval records."""

from __future__ import annotations

from typing import Any


def approval_display_fields(pending: Any) -> dict[str, str]:
    """Return UI-facing tool display metadata for one pending approval."""
    display = pending.extra.get("display", {})
    if not isinstance(display, dict):
        display = {}
    return {
        "tool_display_name": str(
            display.get("tool_name") or pending.tool_name,
        ),
        "tool_source": str(display.get("tool_source") or "builtin"),
    }
