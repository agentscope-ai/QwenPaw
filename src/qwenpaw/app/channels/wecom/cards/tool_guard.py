# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""WeCom tool-guard approval card (self-contained).

Builders + callback parser + outbound ``render`` + inbound ``handle``
all live here; the dispatcher reads the module-level metadata
(``NAME`` / ``MESSAGE_TYPE`` / ``TASK_ID_PREFIX``) plus ``render`` /
``handle`` to wire it in.

Refs: https://developer.work.weixin.qq.com/document/path/101032
      https://developer.work.weixin.qq.com/document/path/101027
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

from . import context

if TYPE_CHECKING:
    from ..channel import WecomChannel

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


# =====================================================================
# Outbound: render
# =====================================================================


async def render(
    channel: "WecomChannel",
    to_handle: str,
    event: Any,
    send_meta: Dict[str, Any],
    meta: Dict[str, Any],
) -> bool:
    """Render a tool-guard event as a button_interaction card.

    Streams the full guard details first (reusing the active processing
    stream when present, to avoid leaving an empty bubble), then posts
    the approval card.
    """
    request_id = str(meta.get("approval_request_id") or "")
    if not request_id:
        return False

    if not channel.enabled or not channel._client:
        return False

    frame = send_meta.get("wecom_frame")
    if not frame:
        logger.warning(
            "wecom approval card: no frame for to_handle=%s",
            (to_handle or "")[:40],
        )
        return False

    body_text = context.extract_body_text(getattr(event, "content", None))
    session_ctx = context.build_session_ctx(to_handle, send_meta)

    try:
        template_card = build_approval_card(
            request_id=request_id,
            tool_name=str(meta.get("tool_name") or "tool"),
            severity=str(meta.get("severity") or "medium"),
            session_ctx=session_ctx,
        )
    except ValueError as exc:
        # Skip the card and let default text rendering take over.
        logger.warning(
            "wecom approval card: %s; skipping card for request_id=%s",
            exc,
            request_id[:8],
        )
        return False

    # Stream the guard details first, then post the button card.
    # Skip if the caller already streamed the content (streaming path).
    if not send_meta.get("_skip_stream_detail"):
        await context.send_stream_detail(channel, frame, send_meta, body_text)
    try:
        await channel._client.reply_template_card(
            frame,
            template_card,
        )
        logger.info(
            "wecom approval card sent: request_id=%s tool=%s",
            request_id[:8],
            meta.get("tool_name", ""),
        )
        return True
    except Exception:
        logger.exception(
            "wecom approval card send failed: request_id=%s",
            request_id[:8],
        )
        return False


# =====================================================================
# Inbound: handle
# =====================================================================


async def handle(
    channel: "WecomChannel",
    frame: Any,
) -> None:
    """Process a tool-guard ``template_card_event`` callback."""
    body = frame.get("body") or {} if isinstance(frame, dict) else {}
    parsed = parse_card_event(body)
    if not parsed:
        return

    action = parsed["action"]
    request_id = parsed["request_id"]
    task_id = parsed["task_id"]
    tool_name = parsed.get("tool_name") or "tool"
    user_id = parsed.get("user_id") or ""

    logger.info(
        "wecom card event: action=%s request_id=%s user=%s",
        action,
        request_id[:8],
        user_id[:20],
    )

    # 1. Replace the card with a resolved-state card (must be <5s).
    await _update_card_resolved(
        channel,
        frame,
        task_id,
        tool_name,
        action,
        user_id,
    )

    # 2. Inject /approval command into the message queue.
    _enqueue_approval_command(
        channel,
        action=action,
        request_id=request_id,
        session_ctx=parsed.get("session_ctx") or {},
        user_id=user_id,
    )


async def _update_card_resolved(
    channel: "WecomChannel",
    frame: Any,
    task_id: str,
    tool_name: str,
    action: str,
    operator_display: str,
) -> None:
    """Replace the approval card with a resolved status card."""
    if not channel._client:
        return

    resolved_card = build_resolved_card(
        task_id=task_id,
        tool_name=tool_name,
        action=action,
        operator_display=operator_display,
    )

    try:
        await channel._client.update_template_card(
            frame,
            resolved_card,
        )
        logger.info(
            "wecom approval card updated: task_id=%s action=%s",
            task_id[:20],
            action,
        )
    except Exception:
        logger.exception(
            "wecom approval card update failed: task_id=%s",
            task_id[:20],
        )


def _enqueue_approval_command(
    channel: "WecomChannel",
    *,
    action: str,
    request_id: str,
    session_ctx: Dict[str, Any],
    user_id: str,
) -> None:
    """Inject ``/approval {action} {request_id}`` into the channel queue."""
    from agentscope_runtime.engine.schemas.agent_schemas import (
        ContentType,
        TextContent,
    )

    enqueue = getattr(channel, "_enqueue", None)
    if enqueue is None:
        logger.warning(
            "wecom card action: channel enqueue not set, dropping %s %s",
            action,
            request_id[:8],
        )
        return

    sender_id = str(session_ctx.get("sender_id") or user_id or "")
    session_id = str(session_ctx.get("session_id") or "")
    chatid = str(session_ctx.get("chatid") or "")
    chat_type = str(session_ctx.get("chat_type") or "single")
    is_group = chat_type == "group"

    command_text = f"/approval {action} {request_id}"
    payload = {
        "channel_id": channel.channel,
        "sender_id": sender_id,
        "user_id": sender_id,
        "session_id": session_id,
        "content_parts": [
            TextContent(type=ContentType.TEXT, text=command_text),
        ],
        "meta": {
            "wecom_sender_id": sender_id,
            "wecom_chatid": chatid,
            "wecom_chat_type": chat_type,
            "is_group": is_group,
            "from_card_action": True,
        },
    }
    try:
        enqueue(payload)
        logger.info(
            "wecom card action enqueued: cmd=%s request=%s session=%s",
            command_text,
            request_id[:8],
            session_id[:12],
        )
    except Exception:
        logger.exception(
            "wecom card action: enqueue failed: %s %s",
            action,
            request_id[:8],
        )
