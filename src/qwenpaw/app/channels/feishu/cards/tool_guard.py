# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Feishu tool-guard approval card (self-contained).

Builders + callback parser + outbound ``render`` + inbound ``handle``
all live here; the dispatcher reads the module-level metadata
(``NAME`` / ``MESSAGE_TYPE`` / ``ACTION_TYPE``) plus ``render`` /
``handle`` to wire it in.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

from . import context

try:
    from lark_oapi.event.callback.model.p2_card_action_trigger import (
        P2CardActionTriggerResponse,
    )
except ImportError:  # pragma: no cover - optional dependency
    P2CardActionTriggerResponse = None  # type: ignore[assignment]

if TYPE_CHECKING:  # pragma: no cover
    from ..channel import FeishuChannel

logger = logging.getLogger(__name__)


# =====================================================================
# Module-level metadata (read by the dispatcher when registering)
# =====================================================================

NAME = "tool_guard_approval"

# Outbound metadata.message_type that triggers this card kind.
MESSAGE_TYPE = "tool_guard_approval"

# Marker in ``CallBackAction.value`` that identifies tool-guard buttons.
ACTION_TYPE = "tool_guard_approval"


# =====================================================================
# Constants
# =====================================================================

_FEISHU_CALLBACK_CONFIG_DOC_URL = (
    "https://qwenpaw.agentscope.io/docs/channels#feishu-callback-config"
)

_SEVERITY_TEMPLATE = {
    "critical": "red",
    "high": "red",
    "medium": "orange",
    "low": "yellow",
}

APPROVE_KEY = "approve"
DENY_KEY = "deny"


# =====================================================================
# Helpers
# =====================================================================


def _truncate(text: str, limit: int) -> str:
    if not text:
        return ""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _severity_template(severity: str) -> str:
    return _SEVERITY_TEMPLATE.get((severity or "").lower(), "orange")


# =====================================================================
# Builders
# =====================================================================


def build_approval_card(
    *,
    request_id: str,
    tool_name: str,
    severity: str,
    body_text: str,
    session_ctx: Optional[Dict[str, Any]] = None,
) -> str:
    """Build the full tool-guard approval card JSON string.

    Used in non-streaming mode where the card contains both the
    approval body and interactive buttons.
    """
    text = body_text or ""
    markdown_content = _truncate(text, 1800)
    body_snapshot = _truncate(text, 1500)
    ctx_snapshot = dict(session_ctx or {})
    approve_value = {
        "type": ACTION_TYPE,
        "action": APPROVE_KEY,
        "request_id": request_id,
        "tool_name": tool_name,
        "severity": severity or "medium",
        "body": body_snapshot,
        "session_ctx": ctx_snapshot,
    }
    deny_value = {**approve_value, "action": DENY_KEY}

    card: Dict[str, Any] = {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": _severity_template(severity),
            "title": {
                "tag": "plain_text",
                "content": "🛡️ Tool Approval Required",
            },
        },
        "elements": [
            {"tag": "markdown", "content": markdown_content},
            {"tag": "hr"},
            {
                "tag": "markdown",
                "content": (
                    "ⓘ <font color='orange'>**"
                    "[Buttons not working?  Click here]"
                    f"({_FEISHU_CALLBACK_CONFIG_DOC_URL})"
                    "**</font>"
                ),
            },
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {
                            "tag": "plain_text",
                            "content": "✅ Approve",
                        },
                        "type": "primary",
                        "value": approve_value,
                    },
                    {
                        "tag": "button",
                        "text": {
                            "tag": "plain_text",
                            "content": "❌ Deny",
                        },
                        "type": "danger",
                        "value": deny_value,
                    },
                ],
            },
        ],
    }
    return json.dumps(card, ensure_ascii=False)


def build_compact_card(
    *,
    request_id: str,
    tool_name: str,
    severity: str,
    body_text: str,
    session_ctx: Optional[Dict[str, Any]] = None,
) -> str:
    """Build a compact card with only header and buttons.

    Used in streaming mode where the full approval body has already been
    rendered in the streaming card.  The ``body`` field in button value
    is intentionally left empty so that the resolved card will NOT
    display the original tool_guard details (they were sent separately
    in the stream).
    """
    del body_text  # intentionally unused; kept for signature parity
    ctx_snapshot = dict(session_ctx or {})
    approve_value = {
        "type": ACTION_TYPE,
        "action": APPROVE_KEY,
        "request_id": request_id,
        "tool_name": tool_name,
        "severity": severity or "medium",
        "body": "",
        "session_ctx": ctx_snapshot,
    }
    deny_value = {**approve_value, "action": DENY_KEY}

    card: Dict[str, Any] = {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": _severity_template(severity),
            "title": {
                "tag": "plain_text",
                "content": "🛡️ Tool Approval Required",
            },
        },
        "elements": [
            {
                "tag": "markdown",
                "content": f"**Tool**: `{tool_name}`",
            },
            {
                "tag": "markdown",
                "content": (
                    "ⓘ <font color='orange'>**"
                    "[Buttons not working?  Click here]"
                    f"({_FEISHU_CALLBACK_CONFIG_DOC_URL})"
                    "**</font>"
                ),
            },
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {
                            "tag": "plain_text",
                            "content": "✅ Approve",
                        },
                        "type": "primary",
                        "value": approve_value,
                    },
                    {
                        "tag": "button",
                        "text": {
                            "tag": "plain_text",
                            "content": "❌ Deny",
                        },
                        "type": "danger",
                        "value": deny_value,
                    },
                ],
            },
        ],
    }
    return json.dumps(card, ensure_ascii=False)


def build_resolved_card(
    *,
    tool_name: str,
    action: str,
    operator_display: str = "",
    body_text: str = "",
) -> str:
    """Card that replaces the original one after a button click.

    When ``body_text`` is empty (streaming/compact mode), only the
    status line is shown — matching the WeCom resolved card style
    (tool name + who approved).
    """
    by_text = f" by `{operator_display}`" if operator_display else ""
    if action == APPROVE_KEY:
        title = "✅ Approved"
        template = "green"
        status_line = f"Tool `{tool_name}` approved{by_text}."
    elif action == DENY_KEY:
        title = "🚫 Denied"
        template = "red"
        status_line = f"Tool `{tool_name}` denied{by_text}."
    else:
        title = "⌛ Expired"
        template = "grey"
        status_line = f"Approval for `{tool_name}` has expired."

    elements: list = []
    if body_text:
        elements.append(
            {"tag": "markdown", "content": _truncate(body_text, 1800)},
        )
        elements.append({"tag": "hr"})
    elements.append({"tag": "markdown", "content": status_line})

    card: Dict[str, Any] = {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": template,
            "title": {"tag": "plain_text", "content": title},
        },
        "elements": elements,
    }
    return json.dumps(card, ensure_ascii=False)


def build_toast(action: str, tool_name: str) -> Dict[str, Any]:
    """Build a toast payload for the card.action.trigger response."""
    if action == APPROVE_KEY:
        return {"type": "success", "content": f"Approved tool {tool_name}"}
    if action == DENY_KEY:
        return {"type": "info", "content": f"Denied tool {tool_name}"}
    return {"type": "warning", "content": "Approval request has expired"}


# =====================================================================
# Parser
# =====================================================================


def parse_action_value(action_value: Any) -> Optional[Dict[str, Any]]:
    """Extract tool-guard fields from a card.action.trigger payload.

    Returns ``None`` if the value does not look like a tool-guard button.
    """
    if not isinstance(action_value, dict):
        return None
    if action_value.get("type") != ACTION_TYPE:
        return None
    action = str(action_value.get("action") or "").strip().lower()
    request_id = str(action_value.get("request_id") or "").strip()
    if not request_id or action not in (APPROVE_KEY, DENY_KEY):
        return None
    raw_ctx = action_value.get("session_ctx")
    session_ctx = raw_ctx if isinstance(raw_ctx, dict) else {}
    return {
        "action": action,
        "request_id": request_id,
        "tool_name": str(action_value.get("tool_name") or ""),
        "severity": str(action_value.get("severity") or "medium"),
        "body": str(action_value.get("body") or ""),
        "session_ctx": session_ctx,
    }


# =====================================================================
# Outbound: render
# =====================================================================


async def render(
    channel: "FeishuChannel",
    to_handle: str,
    event: Any,
    send_meta: Dict[str, Any],
    meta: Dict[str, Any],
    *,
    compact: bool = False,
) -> bool:
    """Send a tool-guard approval interactive card.

    When ``compact=True`` (streaming mode), send a minimal card with
    only the header and approve/deny buttons — the full approval
    body has already been rendered in the streaming card.
    """
    if not meta.get("approval_request_id"):
        return False
    if not channel.enabled:
        return False

    recv = await channel._get_receive_for_send(to_handle, send_meta)
    if not recv:
        logger.warning(
            "feishu approval card: no receive_id for to_handle=%s",
            (to_handle or "")[:50],
        )
        return False

    receive_id_type, receive_id = recv
    body_text = context.extract_body_text(getattr(event, "content", None))
    session_ctx = context.build_session_ctx(
        to_handle,
        send_meta,
        receive_id,
        receive_id_type,
    )

    builder = build_compact_card if compact else build_approval_card
    content = builder(
        request_id=str(meta.get("approval_request_id") or ""),
        tool_name=str(meta.get("tool_name") or "tool"),
        severity=str(meta.get("severity") or "medium"),
        body_text=body_text,
        session_ctx=session_ctx,
    )

    msg_id = await channel._send_message(
        receive_id_type,
        receive_id,
        "interactive",
        content,
    )
    if msg_id:
        send_meta["_last_sent_message_id"] = msg_id
        logger.info(
            "feishu approval card sent: request_id=%s msg_id=%s compact=%s",
            str(meta.get("approval_request_id") or "")[:8],
            msg_id[:24],
            compact,
        )
        return True
    logger.warning(
        "feishu approval card send failed: request_id=%s",
        str(meta.get("approval_request_id") or "")[:8],
    )
    return False


# =====================================================================
# Inbound: handle
# =====================================================================


def handle(
    channel: "FeishuChannel",
    event: Any,
    action_value: Dict[str, Any],
) -> "P2CardActionTriggerResponse":
    """Process a tool-guard card button click (synchronous)."""
    parsed = parse_action_value(action_value)
    if not parsed:
        return P2CardActionTriggerResponse({})

    action = parsed["action"]
    operator = getattr(event, "operator", None) if event else None
    operator_open_id = (
        getattr(operator, "open_id", None) if operator else None
    ) or ""

    # Re-inject as /approval command.
    _enqueue_approval_command(
        channel,
        action=action,
        request_id=parsed["request_id"],
        session_ctx=parsed.get("session_ctx") or {},
        operator_open_id=operator_open_id,
    )

    tool_name = parsed.get("tool_name") or "tool"

    # Resolve operator display name.
    operator_display = operator_open_id[-6:] if operator_open_id else ""
    loop = channel._loop
    if operator_open_id and loop and loop.is_running():
        try:
            name = asyncio.run_coroutine_threadsafe(
                channel._get_user_name_by_open_id(operator_open_id),
                loop,
            ).result(timeout=2)
            if name:
                operator_display = name
        except Exception:
            pass

    resolved_card = build_resolved_card(
        tool_name=tool_name,
        action=action,
        operator_display=operator_display,
        body_text=parsed.get("body") or "",
    )
    toast = build_toast(action, tool_name)
    try:
        return P2CardActionTriggerResponse(
            {
                "toast": toast,
                "card": {
                    "type": "raw",
                    "data": json.loads(resolved_card),
                },
            },
        )
    except Exception:  # pragma: no cover
        logger.exception("feishu card action: build response failed")
        return P2CardActionTriggerResponse({"toast": toast})


# =====================================================================
# Internal helpers
# =====================================================================


def _enqueue_approval_command(
    channel: "FeishuChannel",
    *,
    action: str,
    request_id: str,
    session_ctx: Dict[str, Any],
    operator_open_id: str,
) -> None:
    """Inject ``/approval {action} {request_id}`` into the channel queue."""
    from agentscope_runtime.engine.schemas.agent_schemas import (
        ContentType,
        TextContent,
    )

    enqueue = getattr(channel, "_enqueue", None)
    if enqueue is None:
        logger.warning(
            "feishu card action: channel enqueue not set, drop %s %s",
            action,
            request_id[:8],
        )
        return

    sender_id = str(session_ctx.get("sender_id") or operator_open_id or "")
    session_id = str(session_ctx.get("session_id") or "")
    receive_id = str(session_ctx.get("receive_id") or "")
    receive_id_type = str(session_ctx.get("receive_id_type") or "open_id")
    chat_id = str(session_ctx.get("chat_id") or "")
    chat_type = str(session_ctx.get("chat_type") or "p2p")
    is_group = bool(session_ctx.get("is_group"))

    command_text = f"/approval {action} {request_id}".strip()
    content_parts = [
        TextContent(type=ContentType.TEXT, text=command_text),
    ]
    meta: Dict[str, Any] = {
        "feishu_sender_id": sender_id,
        "feishu_chat_id": chat_id,
        "feishu_chat_type": chat_type,
        "feishu_receive_id": receive_id,
        "feishu_receive_id_type": receive_id_type,
        "is_group": is_group,
        "from_card_action": True,
    }
    payload = {
        "channel_id": channel.channel,
        "sender_id": sender_id,
        "user_id": sender_id,
        "session_id": session_id,
        "content_parts": content_parts,
        "meta": meta,
    }
    try:
        enqueue(payload)
        logger.info(
            "feishu card action enqueued: cmd=%s request=%s session=%s",
            command_text,
            request_id[:8],
            session_id[:12],
        )
    except Exception:  # pragma: no cover
        logger.exception(
            "feishu card action: enqueue command failed: %s %s",
            action,
            request_id[:8],
        )
