# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Native approval-card builders and button parser, independent of host execution."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# =====================================================================
# Module-level metadata (read by the dispatcher when registering)
# =====================================================================

NAME = "tool_guard_approval"

# Outbound metadata.message_type that triggers this card kind.
MESSAGE_TYPE = "tool_guard_approval"

# Unique prefix embedded in ``task_id`` so the dispatcher can route the
# inbound callback to this card kind.  ``request_id`` is a UUID4
# (hex + dashes), all of which are valid task_id chars per WeCom spec
# (``[0-9a-zA-Z_\-@]``, ≤128 bytes), so no sanitisation is needed.
TASK_ID_PREFIX = "tg_approval_"


# =====================================================================
# Constants (internal)
# =====================================================================

# Button key prefixes encoded into the JSON payload of each button.
APPROVE_KEY = "approve"
DENY_KEY = "deny"

# Placeholder url for the resolved card's required card_action.  WeCom
# rejects ``text_notice`` cards without a card_action of type 1 or 2.
_RESOLVED_CARD_URL = "https://qwenpaw.agentscope.io"


# =====================================================================
# Builders
# =====================================================================


def _truncate(text: str, limit: int) -> str:
    if not text:
        return ""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _build_button_key(
    action: str,
    request_id: str,
    tool_name: str,
    severity: str,
    session_ctx: Dict[str, Any],
) -> str:
    """Encode action + ctx into a button ``key`` (≤1024 bytes per WeCom);
    raises :class:`ValueError` when the payload would overflow.
    """
    payload = json.dumps(
        {
            "a": action,
            "rid": request_id,
            "tool": tool_name,
            "sev": severity,
            **session_ctx,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    encoded_len = len(payload.encode("utf-8"))
    if encoded_len > 1024:
        raise ValueError(
            f"button key payload too large: {encoded_len} bytes (limit 1024)",
        )
    return payload


def build_approval_card(
    *,
    request_id: str,
    tool_name: str,
    severity: str,
    session_ctx: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the ``button_interaction`` approval card."""
    severity_lower = (severity or "medium").lower()
    ctx = session_ctx or {}

    return {
        "card_type": "button_interaction",
        "task_id": f"{TASK_ID_PREFIX}{request_id}",
        "main_title": {
            "title": "🛡️ Tool Approval Required",
            "desc": f"{tool_name} | {severity_lower}",
        },
        # button_list MUST live at the root.  Do NOT wrap it in
        # card_action (that field is for whole-card click-to-jump and
        # requires a url when type=1).
        "button_list": [
            {
                "text": "Approve",
                "style": 1,
                "key": _build_button_key(
                    APPROVE_KEY,
                    request_id,
                    tool_name,
                    severity_lower,
                    ctx,
                ),
            },
            {
                "text": "Deny",
                "style": 2,
                "key": _build_button_key(
                    DENY_KEY,
                    request_id,
                    tool_name,
                    severity_lower,
                    ctx,
                ),
            },
        ],
    }


def build_resolved_card(
    *,
    task_id: str,
    tool_name: str,
    action: str,
    operator_display: str = "",
) -> Dict[str, Any]:
    """Build the ``text_notice`` card shown after a button click.

    WeCom requires ``card_action`` on ``text_notice`` cards, with
    ``type`` in {1, 2} (0 is rejected by the bot endpoint).  We provide
    a project URL so it stays meaningful when clicked.
    """
    by_text = f"by {operator_display}" if operator_display else ""
    if action == APPROVE_KEY:
        title = "✅ Approved"
        desc = f"{by_text}\n{tool_name}"
    elif action == DENY_KEY:
        title = "🚫 Denied"
        desc = f"{by_text}\n{tool_name}"
    else:
        title = "⌛ Expired"
        desc = f"Approval for {tool_name} has expired."

    return {
        "card_type": "text_notice",
        "task_id": task_id,
        "main_title": {
            "title": _truncate(title, 36),
            "desc": _truncate(desc, 44),
        },
        "card_action": {"type": 1, "url": _RESOLVED_CARD_URL},
    }


# =====================================================================
# Parser
# =====================================================================


def parse_card_event(
    event_body: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Extract tool-guard fields from a ``template_card_event`` callback.

    Returns ``None`` when ``event_key`` is malformed or the action is
    unknown.  Prefix routing is the dispatcher's job.
    """
    event = event_body.get("event") or {}
    tce = event.get("template_card_event") or event

    event_key = str(tce.get("event_key") or "")
    try:
        ctx = json.loads(event_key)
    except (json.JSONDecodeError, TypeError):
        return None

    if not isinstance(ctx, dict):
        return None
    action = str(ctx.get("a") or "")
    if action not in (APPROVE_KEY, DENY_KEY):
        return None

    from_info = event_body.get("from") or {}
    return {
        "action": action,
        "request_id": str(ctx.get("rid") or ""),
        "task_id": str(tce.get("task_id") or ""),
        "tool_name": str(ctx.get("tool") or ""),
        "severity": str(ctx.get("sev") or "medium"),
        "session_ctx": {
            k: v
            for k, v in ctx.items()
            if k not in ("a", "rid", "tool", "sev")
        },
        "user_id": str(from_info.get("userid") or ""),
    }
