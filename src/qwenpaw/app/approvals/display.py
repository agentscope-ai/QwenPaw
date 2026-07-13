# -*- coding: utf-8 -*-
"""Presentation helpers for approval records."""

from __future__ import annotations

from typing import Any


def approval_display_fields(pending: Any) -> dict[str, Any]:
    """Return UI-facing tool display metadata for one pending approval.

    ``is_generalized`` lets the console render the Approve Pattern /
    Approve Exact choice only when the generalized target actually
    differs from the literal one; ``exact_target`` / ``similar_target``
    are the two values the user is choosing between.
    """
    display = pending.extra.get("display", {})
    if not isinstance(display, dict):
        display = {}
    return {
        "tool_display_name": str(
            display.get("tool_name") or pending.tool_name,
        ),
        "tool_source": str(display.get("tool_source") or "No rule hit"),
        "exact_target": str(display.get("exact_target") or ""),
        "similar_target": str(display.get("similar_target") or ""),
        "is_generalized": bool(display.get("is_generalized")),
    }
