# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""QQ tool-guard approval card (keyboard buttons).

Uses QQ's markdown + keyboard mechanism to send approval buttons.
Inbound button clicks arrive as INTERACTION_CREATE WebSocket events.

QQ API refs:
  https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/trans/msg-btn.html
  https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/send-receive/send.html
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

from . import context

if TYPE_CHECKING:
    from ..channel import QQChannel

logger = logging.getLogger(__name__)


# =====================================================================
# Module-level metadata (read by the dispatcher when registering)
# =====================================================================

NAME = "tool_guard_approval"

# Outbound metadata.message_type that triggers this card kind.
MESSAGE_TYPE = "tool_guard_approval"

# Prefix in action.data to identify our button callbacks.
ACTION_DATA_PREFIX = "tg_"


# =====================================================================
# Constants
# =====================================================================

APPROVE_KEY = "approve"
DENY_KEY = "deny"


# =====================================================================
# Builders
# =====================================================================


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
                                "visited_label": "✅ Approved",
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
                                "visited_label": "🚫 Denied",
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


# =====================================================================
# Parser
# =====================================================================


def parse_interaction_event(
    event_data: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Parse an INTERACTION_CREATE event for tool-guard button clicks.

    Returns None if the event is not a tool-guard button action.
    """
    data_str = str(
        event_data.get("data", {}).get("resolved", {}).get("button_data")
        or "",
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


# =====================================================================
# Outbound: render
# =====================================================================


async def render(
    channel: "QQChannel",
    to_handle: str,
    event: Any,
    send_meta: Dict[str, Any],
    meta: Dict[str, Any],
) -> bool:
    """Render a tool-guard event as a markdown + keyboard message."""
    request_id = str(meta.get("approval_request_id") or "")
    if not request_id:
        return False

    if not channel.enabled:
        return False

    tool_name = str(meta.get("tool_name") or "tool")
    severity = str(meta.get("severity") or "medium")

    session_ctx = context.build_session_ctx(to_handle, send_meta)

    keyboard = build_approval_keyboard(
        request_id=request_id,
        tool_name=tool_name,
        severity=severity,
        session_ctx=session_ctx,
    )

    body_text = context.extract_body_text(getattr(event, "content", None))
    markdown_content = body_text or "🛡️ Tool Approval Required"

    # Resolve send path from meta
    message_type = str(send_meta.get("message_type") or "c2c")
    sender_id = str(send_meta.get("sender_id") or to_handle)
    msg_id = str(send_meta.get("message_id") or "")
    group_openid = str(send_meta.get("group_openid") or "")
    channel_id = str(send_meta.get("channel_id") or "")
    guild_id = str(send_meta.get("guild_id") or "")

    try:
        token = await channel._get_access_token_async()
    except Exception:
        logger.exception("qq approval card: get token failed")
        return False

    try:
        await _send_keyboard_message(
            channel,
            token=token,
            message_type=message_type,
            sender_id=sender_id,
            group_openid=group_openid,
            channel_id=channel_id,
            guild_id=guild_id,
            msg_id=msg_id,
            markdown_content=markdown_content,
            keyboard=keyboard,
        )
        logger.info(
            "qq approval card sent: request_id=%s tool=%s",
            request_id[:8],
            tool_name,
        )
        return True
    except Exception:
        logger.exception(
            "qq approval card send failed: request_id=%s",
            request_id[:8],
        )
        return False


async def _send_keyboard_message(
    channel: "QQChannel",
    *,
    token: str,
    message_type: str,
    sender_id: str,
    group_openid: str,
    channel_id: str,
    guild_id: str,
    msg_id: str,
    markdown_content: str,
    keyboard: Dict[str, Any],
) -> None:
    """Send a markdown message with keyboard buttons via QQ API."""
    from ..channel import _api_request_async, _get_next_msg_seq

    path, use_msg_seq, seq_key = channel._resolve_send_path(
        message_type,
        sender_id,
        channel_id,
        group_openid,
        guild_id=guild_id,
    )

    body: Dict[str, Any] = {
        "markdown": {"content": markdown_content},
        "keyboard": keyboard,
        "msg_type": 2,
    }
    if use_msg_seq:
        body["msg_seq"] = _get_next_msg_seq(msg_id or seq_key)
    if msg_id:
        body["msg_id"] = msg_id

    await _api_request_async(
        channel._http,
        token,
        "POST",
        path,
        body,
    )


# =====================================================================
# Inbound: handle
# =====================================================================


# Track processed request_ids to prevent duplicate button clicks.
_processed_requests: Dict[str, str] = {}
_PROCESSED_MAX_SIZE = 500


def _mark_processed(request_id: str, action: str) -> bool:
    """Mark a request_id as processed. Returns True if already processed."""
    if request_id in _processed_requests:
        return True
    _processed_requests[request_id] = action
    # Evict oldest entries when cache grows too large.
    if len(_processed_requests) > _PROCESSED_MAX_SIZE:
        keys = list(_processed_requests.keys())
        for key in keys[: len(keys) // 2]:
            _processed_requests.pop(key, None)
    return False


async def handle(
    channel: "QQChannel",
    event_data: Dict[str, Any],
) -> None:
    """Process a tool-guard INTERACTION_CREATE button callback.

    1. Check for duplicate clicks (ACK with code=3 if already handled).
    2. Acknowledge the interaction (required by QQ).
    3. Send a resolved status message showing who approved/denied.
    4. Inject /approval command into the message queue.
    """
    parsed = parse_interaction_event(event_data)
    if not parsed:
        return

    action = parsed["action"]
    request_id = parsed["request_id"]
    tool_name = parsed.get("tool_name") or "tool"
    session_ctx = parsed.get("session_ctx") or {}

    # Extract operator info from the interaction event.
    # group: group_member_openid, c2c: user_openid,
    # guild: data.resolved.user_id
    operator_member_openid = str(
        event_data.get("group_member_openid")
        or event_data.get("user_openid")
        or event_data.get("data", {}).get("resolved", {}).get("user_id")
        or "",
    )

    interaction_id = str(event_data.get("id") or "")

    # 1. Deduplication: if already processed, ACK with "duplicate" code.
    if _mark_processed(request_id, action):
        logger.info(
            "qq card event: duplicate click ignored request_id=%s",
            request_id[:8],
        )
        if interaction_id:
            await _ack_interaction(channel, interaction_id, code=3)
        return

    logger.info(
        "qq card event: action=%s request_id=%s operator=%s",
        action,
        request_id[:8],
        operator_member_openid[:20],
    )

    # 2. Acknowledge the interaction
    if interaction_id:
        await _ack_interaction(channel, interaction_id)

    # 3. Resolve operator display (openid last 6 chars; QQ API doesn't
    #    expose nicknames in group/c2c openid scenarios).
    operator_display = (
        operator_member_openid[-6:] if operator_member_openid else ""
    )

    # 4. Send resolved status message showing who approved/denied
    await _send_resolved_message(
        channel,
        session_ctx=session_ctx,
        tool_name=tool_name,
        action=action,
        operator_display=operator_display,
    )

    # 5. Inject /approval command into the message queue
    _enqueue_approval_command(
        channel,
        action=action,
        request_id=request_id,
        session_ctx=session_ctx,
        user_id=operator_member_openid,
    )


async def _ack_interaction(
    channel: "QQChannel",
    interaction_id: str,
    code: int = 0,
) -> None:
    """Acknowledge an interaction event (PUT /interactions/{id}).

    Codes: 0=success, 1=fail, 2=rate_limit, 3=duplicate, 4=no_perm.
    """
    from ..channel import _api_request_async

    try:
        token = await channel._get_access_token_async()
        await _api_request_async(
            channel._http,
            token,
            "PUT",
            f"/interactions/{interaction_id}",
            {"code": code},
        )
        logger.debug(
            "qq interaction ack: id=%s code=%d",
            interaction_id[:20],
            code,
        )
    except Exception:
        logger.exception(
            "qq interaction ack failed: id=%s",
            interaction_id[:20],
        )


async def _send_resolved_message(
    channel: "QQChannel",
    *,
    session_ctx: Dict[str, Any],
    tool_name: str,
    action: str,
    operator_display: str,
) -> None:
    """Send a follow-up message showing the approval result and who acted."""
    resolved_text = build_resolved_text(tool_name, action, operator_display)

    message_type = str(session_ctx.get("mt") or "c2c")
    sender_id = str(session_ctx.get("sender") or "")
    group_openid = str(session_ctx.get("goid") or "")
    channel_id = str(session_ctx.get("cid") or "")
    guild_id = str(session_ctx.get("gid") or "")
    msg_id = str(session_ctx.get("mid") or "")

    if not sender_id and not group_openid and not channel_id:
        logger.warning("qq resolved message: no target to send to")
        return

    try:
        await channel._send_text_with_fallback(
            message_type,
            sender_id,
            channel_id,
            group_openid,
            resolved_text,
            msg_id,
            await channel._get_access_token_async(),
            channel._markdown_enabled,
            guild_id=guild_id,
        )
        logger.info(
            "qq resolved message sent: action=%s operator=%s",
            action,
            operator_display,
        )
    except Exception:
        logger.exception("qq resolved message send failed")


def _enqueue_approval_command(
    channel: "QQChannel",
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
            "qq card action: channel enqueue not set, dropping %s %s",
            action,
            request_id[:8],
        )
        return

    sender_id = str(session_ctx.get("sender") or user_id or "")
    session_id = str(session_ctx.get("sid") or "")
    message_type = str(session_ctx.get("mt") or "c2c")
    group_openid = str(session_ctx.get("goid") or "")
    is_group = message_type == "group"

    command_text = f"/approval {action} {request_id}"
    payload = {
        "channel_id": "qq",
        "sender_id": sender_id,
        "user_id": sender_id,
        "session_id": session_id,
        "content_parts": [
            TextContent(type=ContentType.TEXT, text=command_text),
        ],
        "meta": {
            "message_type": message_type,
            "sender_id": sender_id,
            "group_openid": group_openid,
            "is_group": is_group,
            "from_card_action": True,
        },
    }
    try:
        enqueue(payload)
        logger.info(
            "qq card action enqueued: cmd=%s request=%s session=%s",
            command_text,
            request_id[:8],
            session_id[:12],
        )
    except Exception:
        logger.exception(
            "qq card action: enqueue failed: %s %s",
            action,
            request_id[:8],
        )
