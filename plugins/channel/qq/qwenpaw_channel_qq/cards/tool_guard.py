# -*- coding: utf-8 -*-
"""Legacy QQ keyboard wire builders with neutral click presentation."""

from __future__ import annotations
from dataclasses import dataclass
import json
from typing import Any, Dict, Optional

NAME = "tool_guard_approval"
MESSAGE_TYPE = "tool_guard_approval"
ACTION_DATA_PREFIX = "tg_"
APPROVE_KEY = "approve"
DENY_KEY = "deny"


def _build_action_data(
    action: str,
    request_id: str,
    tool_name: str,
    severity: str,
    session_ctx: Dict[str, Any],
) -> str:
    """Encode action + context into button action.data string."""
    payload = json.dumps(
        {
            "p": ACTION_DATA_PREFIX,
            "a": action,
            "rid": request_id,
            "tool": tool_name,
            "sev": severity,
            **session_ctx,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return payload


def build_approval_keyboard(
    *,
    request_id: str,
    tool_name: str,
    severity: str,
    session_ctx: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the keyboard JSON for approve/deny buttons."""
    severity_lower = (severity or "medium").lower()
    ctx = session_ctx or {}

    approve_data = _build_action_data(
        APPROVE_KEY,
        request_id,
        tool_name,
        severity_lower,
        ctx,
    )
    deny_data = _build_action_data(
        DENY_KEY,
        request_id,
        tool_name,
        severity_lower,
        ctx,
    )

    return {
        "content": {
            "rows": [
                {
                    "buttons": [
                        {
                            "id": f"approve_{request_id[:8]}",
                            "render_data": {
                                "label": "✅ Approve",
                                "visited_label": "Received",
                                "style": 1,
                            },
                            "action": {
                                "type": 1,
                                "permission": {"type": 2},
                                "data": approve_data,
                                "unsupport_tips": (
                                    "Please use /approval approve"
                                ),
                            },
                        },
                        {
                            "id": f"deny_{request_id[:8]}",
                            "render_data": {
                                "label": "🚫 Deny",
                                "visited_label": "Received",
                                "style": 0,
                            },
                            "action": {
                                "type": 1,
                                "permission": {"type": 2},
                                "data": deny_data,
                                "unsupport_tips": "Please use /approval deny",
                            },
                        },
                    ],
                },
            ],
        },
    }


def build_resolved_text(
    tool_name: str,
    action: str,
    operator_display: str = "",
) -> str:
    """Build the text message sent after a button click (shows who acted)."""
    by_text = f" by **{operator_display}**" if operator_display else ""
    if action == APPROVE_KEY:
        return f"✅ **Approved**{by_text}\nTool: `{tool_name}`"
    elif action == DENY_KEY:
        return f"🚫 **Denied**{by_text}\nTool: `{tool_name}`"
    return f"⌛ **Expired**\nApproval for `{tool_name}` has expired."


def parse_interaction_event(
    event_data: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Parse an INTERACTION_CREATE event for tool-guard button clicks.

    Returns None if the event is not a tool-guard button action.
    """
    data = event_data.get("data")
    resolved = data.get("resolved") if isinstance(data, dict) else None
    data_str = (
        str(resolved.get("button_data") or "")
        if isinstance(resolved, dict)
        else ""
    )
    if not data_str:
        # Try alternate path: d.data might be the button action data directly
        data_str = str(event_data.get("button_data") or "")

    if not data_str:
        return None

    try:
        ctx = json.loads(data_str)
    except (json.JSONDecodeError, TypeError):
        return None

    if not isinstance(ctx, dict):
        return None

    # Verify this is our tool-guard button
    if str(ctx.get("p") or "") != ACTION_DATA_PREFIX:
        return None

    action = str(ctx.get("a") or "")
    if action not in (APPROVE_KEY, DENY_KEY):
        return None

    return {
        "action": action,
        "request_id": str(ctx.get("rid") or ""),
        "tool_name": str(ctx.get("tool") or ""),
        "severity": str(ctx.get("sev") or "medium"),
        "session_ctx": {
            k: v
            for k, v in ctx.items()
            if k not in ("p", "a", "rid", "tool", "sev")
        },
    }


@dataclass(frozen=True)
class ApprovalCardBinding:
    nonce: str
    request_id: str
    tool_name: str
    message_id: str
    route: tuple[tuple[str, str], ...]
    source_response_handle: str
    source_delivery_id: str
    instance_id: str
    generation: int


class CardCache:
    """No global card state; known decisions and presentation are separate."""

    def __init__(self):
        self.bindings = {}
        self._processed_requests = {}

    def register(self, binding):
        self.bindings[binding.nonce] = binding
        self._bound(self.bindings)

    def _mark_processed(self, request_id, action):
        if request_id in self._processed_requests:
            return True
        self._processed_requests[request_id] = action
        self._bound(self._processed_requests)
        return False

    @staticmethod
    def _bound(cache):
        if len(cache) > 500:
            for key in list(cache)[: len(cache) // 2]:
                cache.pop(key, None)
