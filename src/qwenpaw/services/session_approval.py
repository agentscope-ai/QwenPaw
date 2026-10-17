# -*- coding: utf-8 -*-
"""Per-chat approval level stored in chat metadata.

The console's per-chat "Tool Approval Mode" is persisted on the chat
(``meta["runtime_context"]["approval_level"]``) so the level follows the
chat across devices and browsers. Clients may still carry a level per
request (``request_context["approval_level"]``); that carry is the
fallback for chats without a persisted level.
"""

from __future__ import annotations

from typing import Any, Optional

# Key inside ``meta["runtime_context"]``.
META_KEY = "approval_level"


def session_approval_level_from_meta(
    meta: dict[str, Any] | None,
) -> Optional[str]:
    """Read the persisted per-chat approval level from chat meta.

    Returns the canonical uppercase level name (``"STRICT"``, ``"SMART"``,
    ``"AUTO"``, ``"OFF"``), or ``None`` when the chat has no persisted
    override — including a malformed stored value, which must not steer
    a turn to the wrong level.
    """
    if not meta:
        return None
    runtime = meta.get("runtime_context") or {}
    raw = runtime.get(META_KEY)
    if not isinstance(raw, str) or not raw.strip():
        return None

    from ..security.tool_guard.execution_level import ToolExecutionLevel

    # The enum's values are lowercase ("strict", ...); match on the value
    # and hand back the canonical uppercase name.
    try:
        return ToolExecutionLevel(raw.strip().lower()).name
    except ValueError:
        return None


def session_approval_level_in_meta(meta: dict[str, Any] | None) -> bool:
    """Whether the chat meta carries a valid persisted approval level."""
    return session_approval_level_from_meta(meta) is not None


__all__ = [
    "META_KEY",
    "session_approval_level_from_meta",
    "session_approval_level_in_meta",
]
