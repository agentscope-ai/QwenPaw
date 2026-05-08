# -*- coding: utf-8 -*-
"""WeCom interactive template-card builders and parsers.

Pure, side-effect-free helpers that build ``button_interaction``
template-card payloads for tool-guard approval and parse the
``template_card_event`` callback values.

WeCom template cards are **server-defined** (no pre-created template
required on any platform), making them analogous to Feishu interactive
cards.  The SDK methods ``reply_template_card`` / ``update_template_card``
accept the card dict directly.

Reference – card structure:
  https://developer.work.weixin.qq.com/document/path/101032
Reference – card event callback:
  https://developer.work.weixin.qq.com/document/path/101027

Kept separate from :mod:`card_handler` so templates are easy to
unit-test and reuse without pulling in channel-level dependencies.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional


# =====================================================================
# Constants
# =====================================================================

# Unique prefix embedded in ``task_id`` so we can tell tool-guard cards
# apart from any other template cards the channel might send.
# task_id only allows [0-9a-zA-Z_\-@], max 128 bytes.
TOOL_GUARD_TASK_ID_PREFIX = "tg_approval_"

# Button key values returned via ``event_key`` in the callback.
APPROVE_KEY = "approve"
DENY_KEY = "deny"

# task_id charset: only digits, letters, and "_-@"
_TASK_ID_SANITIZE_RE = re.compile(r"[^0-9a-zA-Z_\-@]")

_SEVERITY_COLORS = {
    "critical": 2,  # red
    "high": 2,
    "medium": 3,  # green (closest to "warning" in WeCom palette)
    "low": 0,  # grey (default)
}


def _truncate(text: str, limit: int) -> str:
    if not text:
        return ""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _sanitize_task_id(raw: str) -> str:
    """Ensure task_id only contains allowed chars and ≤128 bytes."""
    sanitized = _TASK_ID_SANITIZE_RE.sub("", raw)
    # Truncate to 128 bytes (ASCII-safe after sanitization).
    return sanitized[:128]


# =====================================================================
# Build approval card
# =====================================================================


def build_tool_guard_approval_card(
    *,
    request_id: str,
    tool_name: str,
    severity: str,
    body_text: str,
    session_ctx: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a ``button_interaction`` template card for tool-guard approval.

    The ``task_id`` encodes the ``request_id`` so the inbound callback
    handler can map it back.  Session context is encoded into button
    ``key`` values (max 1024 bytes each) so the handler can reconstruct
    routing info without server-side state.

    Returns the ``template_card`` dict ready for
    ``WSClient.reply_template_card(frame, template_card)``.
    """
    severity_lower = (severity or "medium").lower()
    sev_color = _SEVERITY_COLORS.get(severity_lower, 0)
    task_id = _sanitize_task_id(
        f"{TOOL_GUARD_TASK_ID_PREFIX}{request_id}",
    )

    # Encode session context into each button's key (max 1024 bytes).
    # The callback returns ``event_key`` which is the clicked button's
    # key, so we embed a compact JSON payload there.
    ctx_payload = json.dumps(
        {
            "a": APPROVE_KEY,
            "rid": request_id,
            "tool": tool_name,
            "sev": severity_lower,
            **(session_ctx or {}),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    approve_key = _truncate(ctx_payload, 1024)

    deny_ctx = json.dumps(
        {
            "a": DENY_KEY,
            "rid": request_id,
            "tool": tool_name,
            "sev": severity_lower,
            **(session_ctx or {}),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    deny_key = _truncate(deny_ctx, 1024)

    card: Dict[str, Any] = {
        "card_type": "button_interaction",
        "task_id": task_id,
        "main_title": {
            "title": "🛡️ Tool Approval Required",
            "desc": f"{tool_name} | {severity_lower}",
        },
        # button_list is a root-level field for button_interaction
        # cards.  Do NOT put it inside card_action (which is for
        # whole-card click-to-jump and requires a url when type=1).
        "button_list": [
            {
                "text": "Approve",
                "style": 1,
                "key": approve_key,
            },
            {
                "text": "Deny",
                "style": 2,
                "key": deny_key,
            },
        ],
    }
    return card


# =====================================================================
# Build resolved (updated) card
# =====================================================================


def build_tool_guard_resolved_card(
    *,
    task_id: str,
    tool_name: str,
    action: str,
    operator_display: str = "",
) -> Dict[str, Any]:
    """Build the replacement card shown after a button click.

    WeCom ``update_template_card`` replaces the entire card body, so we
    build a ``text_notice`` card that shows the final status.

    ``task_id`` **must** match the original card's ``task_id``.
    """
    by_text = f" by {operator_display}" if operator_display else ""
    if action == APPROVE_KEY:
        title = "✅ Approved"
        desc = f"Tool {tool_name} approved{by_text}."
    elif action == DENY_KEY:
        title = "🚫 Denied"
        desc = f"Tool {tool_name} denied{by_text}."
    else:
        title = "⌛ Expired"
        desc = f"Approval for {tool_name} has expired."

    return {
        "card_type": "text_notice",
        "task_id": task_id,
        "main_title": {
            "title": title,
            "desc": _truncate(desc, 30),
        },
        # text_notice requires card_action with type in [1,2].
        # Provide a no-op url so WeCom accepts it.
        "card_action": {
            "type": 1,
            "url": "https://qwenpaw.agentscope.io",
        },
    }


# =====================================================================
# Parse callback
# =====================================================================


def parse_tool_guard_card_event(
    event_body: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Extract tool-guard fields from a ``template_card_event`` callback.

    WeCom callback structure::

        body.event.template_card_event.{
            card_type, event_key, task_id, selected_items
        }

    ``event_key`` is the clicked button's ``key`` value (our JSON
    payload).  ``task_id`` carries the request_id.

    Returns ``None`` when the event does not belong to a tool-guard card.
    """
    event = event_body.get("event") or {}
    # The event body nests the actual data under ``template_card_event``.
    tce = event.get("template_card_event") or event
    task_id = str(tce.get("task_id") or "")
    if not task_id.startswith(TOOL_GUARD_TASK_ID_PREFIX):
        return None

    request_id_from_task = task_id[len(TOOL_GUARD_TASK_ID_PREFIX):]
    if not request_id_from_task:
        return None

    # event_key is the clicked button's key (our JSON payload).
    event_key = str(tce.get("event_key") or "")
    if not event_key:
        return None

    # Try to parse the JSON-encoded button key.
    ctx: Dict[str, Any] = {}
    try:
        ctx = json.loads(event_key)
    except (json.JSONDecodeError, TypeError):
        return None

    action = str(ctx.get("a") or "")
    if action not in (APPROVE_KEY, DENY_KEY):
        return None

    # user_id comes from the outer event frame.
    from_info = event_body.get("from") or {}
    user_id = str(
        from_info.get("userid")
        or event.get("userid")
        or tce.get("userid")
        or "",
    )

    return {
        "action": action,
        "request_id": ctx.get("rid") or request_id_from_task,
        "task_id": task_id,
        "tool_name": ctx.get("tool") or "",
        "severity": ctx.get("sev") or "medium",
        "session_ctx": {
            k: v for k, v in ctx.items()
            if k not in ("a", "rid", "tool", "sev")
        },
        "user_id": user_id,
    }
