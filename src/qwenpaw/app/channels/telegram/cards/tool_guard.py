# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Telegram tool-guard approval card (inline keyboard buttons).

Uses Telegram's InlineKeyboardMarkup to send approve/deny buttons.
Inbound button clicks arrive as CallbackQuery updates.

Non-streaming: body text + inline keyboard in one message; after
approval the message is edited to show the resolved status.

Streaming: body text was already streamed; a compact card (tool name
+ buttons) is sent separately; edited on approval.

Telegram Bot API refs:
  https://core.telegram.org/bots/api#inlinekeyboardbutton
  https://core.telegram.org/bots/api#callbackquery
  https://core.telegram.org/bots/api#editmessagetext
"""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any, Dict, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import BadRequest

from . import context

if TYPE_CHECKING:
    from ..channel import TelegramChannel

logger = logging.getLogger(__name__)


# =====================================================================
# Module-level metadata (read by the dispatcher when registering)
# =====================================================================

NAME = "tool_guard_approval"

# Outbound metadata.message_type that triggers this card kind.
MESSAGE_TYPE = "tool_guard_approval"

# Prefix in callback_data to identify our button callbacks.
# Format: "tga:{request_id_short}" or "tgd:{request_id_short}"
CALLBACK_DATA_PREFIX = "tg"

# =====================================================================
# Constants
# =====================================================================

APPROVE_PREFIX = "tga:"
DENY_PREFIX = "tgd:"

# In-memory cache mapping request_id → full context.
# Telegram callback_data is limited to 64 bytes, so we store the full
# context here and only pass a short key in callback_data.
_request_context_cache: Dict[str, Dict[str, Any]] = {}
_CACHE_MAX_SIZE = 500

# Track processed request_ids to prevent duplicate button clicks.
_processed_requests: Dict[str, str] = {}
_PROCESSED_MAX_SIZE = 500


# =====================================================================
# Cache helpers
# =====================================================================


def _cache_request_context(
    request_id: str,
    tool_name: str,
    severity: str,
    body_text: str,
    session_ctx: Dict[str, Any],
) -> None:
    """Store full request context keyed by request_id."""
    _request_context_cache[request_id] = {
        "tool_name": tool_name,
        "severity": severity,
        "body_text": body_text,
        "session_ctx": session_ctx,
    }
    # Evict oldest entries when cache grows too large.
    if len(_request_context_cache) > _CACHE_MAX_SIZE:
        keys = list(_request_context_cache.keys())
        for key in keys[: len(keys) // 2]:
            _request_context_cache.pop(key, None)


def _get_request_context(request_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve cached request context."""
    return _request_context_cache.get(request_id)


def _mark_processed(request_id: str, action: str) -> bool:
    """Mark a request_id as processed. Returns True if already processed."""
    if request_id in _processed_requests:
        return True
    _processed_requests[request_id] = action
    if len(_processed_requests) > _PROCESSED_MAX_SIZE:
        keys = list(_processed_requests.keys())
        for key in keys[: len(keys) // 2]:
            _processed_requests.pop(key, None)
    return False


# =====================================================================
# Builders
# =====================================================================


def build_approval_keyboard(request_id: str) -> InlineKeyboardMarkup:
    """Build an InlineKeyboardMarkup with Approve/Deny buttons.

    callback_data format: "tga:{request_id}" / "tgd:{request_id}"
    Must stay within 64 bytes.
    """
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Approve",
                    callback_data=f"{APPROVE_PREFIX}{request_id}",
                ),
                InlineKeyboardButton(
                    "❌ Deny",
                    callback_data=f"{DENY_PREFIX}{request_id}",
                ),
            ],
        ],
    )


def build_approval_text(body_text: str) -> str:
    """Build the full approval message text (non-streaming mode).

    No title/header — just the raw tool_guard body text.  Buttons are
    attached via ``reply_markup`` (InlineKeyboardMarkup).
    """
    return body_text or "🛡️ Tool Approval Required"


def build_compact_text(tool_name: str, severity: str) -> str:
    """Build a compact card text (streaming mode — body already sent)."""
    return (
        f"🛡️ *Tool Approval Required*\n"
        f"*Tool*: `{_escape_mdv2(tool_name)}`"
        f"  \\|  *Severity*: {_escape_mdv2(severity)}"
    )


def build_resolved_text(
    tool_name: str,
    action: str,
    operator_display: str = "",
    body_text: str = "",
) -> str:
    """Build the text shown after a button click.

    When body_text is present (non-streaming), the body is kept as
    plain text and the status line is appended without formatting
    (parse_mode=None).  When body is empty (compact/streaming),
    MarkdownV2 formatting is used.
    """
    status_map = {
        "approve": ("✅", "Approved"),
        "deny": ("🚫", "Denied"),
    }
    icon, word = status_map.get(action, ("⌛", "Expired"))

    if body_text:
        # Plain text — no markdown, no escape needed.
        by_text = f" by {operator_display}" if operator_display else ""
        status_line = f"{icon} {word}{by_text}  |  Tool: {tool_name}"
        return f"{body_text}\n\n{status_line}"

    # Compact (streaming) — MarkdownV2.
    by = _escape_mdv2(operator_display)
    by_text = f" by *{by}*" if operator_display else ""
    return (
        f"{icon} *{word}*{by_text}" f"  \\|  Tool: `{_escape_mdv2(tool_name)}`"
    )


# MarkdownV2 special characters that must be escaped.
_MDV2_ESCAPE_RE = re.compile(r"([_*\[\]()~`>#+\-=|{}.!\\])")


def _escape_mdv2(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    return _MDV2_ESCAPE_RE.sub(r"\\\1", text)


# =====================================================================
# Outbound: render
# =====================================================================


async def render(
    channel: "TelegramChannel",
    to_handle: str,
    event: Any,
    send_meta: Dict[str, Any],
    meta: Dict[str, Any],
    *,
    compact: bool = False,
) -> bool:
    """Render a tool-guard event as an inline keyboard message.

    Non-streaming (compact=False): full body text + buttons in one message.
    Streaming (compact=True): compact text (tool name only) + buttons.
    """
    request_id = str(meta.get("approval_request_id") or "")
    if not request_id or not channel.enabled or not channel._application:
        return False

    bot = channel._application.bot
    if not bot:
        return False

    tool_name = str(meta.get("tool_name") or "tool")
    severity = str(meta.get("severity") or "medium")
    chat_id = str(send_meta.get("chat_id") or to_handle)
    message_thread_id = send_meta.get("message_thread_id")

    if not chat_id:
        logger.warning("telegram approval card: no chat_id")
        return False

    body_text = context.extract_body_text(getattr(event, "content", None))
    session_ctx = context.build_session_ctx(to_handle, send_meta)

    # Cache full context for the callback handler.
    # In compact mode (streaming), don't cache body_text — it was already
    # sent in the streamed message above, so the resolved card should
    # stay compact and not repeat the body.
    _cache_request_context(
        request_id,
        tool_name,
        severity,
        "" if compact else body_text,
        session_ctx,
    )

    keyboard = build_approval_keyboard(request_id)

    if compact:
        text = build_compact_text(tool_name, severity)
        parse_mode = ParseMode.MARKDOWN_V2
    else:
        text = build_approval_text(body_text)
        parse_mode = None  # raw body text, no formatting

    try:
        kwargs: Dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "reply_markup": keyboard,
        }
        if parse_mode:
            kwargs["parse_mode"] = parse_mode
        if message_thread_id is not None:
            kwargs["message_thread_id"] = message_thread_id

        await bot.send_message(**kwargs)
        logger.info(
            "telegram approval card sent: request_id=%s tool=%s compact=%s",
            request_id[:8],
            tool_name,
            compact,
        )
        return True
    except BadRequest:
        logger.exception(
            "telegram approval card send failed (BadRequest): request_id=%s",
            request_id[:8],
        )
        return False
    except Exception:
        logger.exception(
            "telegram approval card send failed: request_id=%s",
            request_id[:8],
        )
        return False


# =====================================================================
# Inbound: handle
# =====================================================================


async def handle(
    channel: "TelegramChannel",
    query: Any,
) -> None:
    """Process a tool-guard CallbackQuery button click.

    1. Parse callback_data to determine action and request_id.
    2. Check for duplicate clicks.
    3. Answer the callback query (toast).
    4. Edit the original message to show resolved status.
    5. Inject /approval command into the message queue.
    """
    callback_data = str(getattr(query, "data", "") or "")
    parsed = _parse_callback_data(callback_data)
    if not parsed:
        return

    action = parsed["action"]
    request_id = parsed["request_id"]

    # Resolve operator display from the callback query sender.
    from_user = getattr(query, "from_user", None)
    operator_display = ""
    if from_user:
        username = getattr(from_user, "username", None)
        first_name = getattr(from_user, "first_name", None)
        if username:
            operator_display = f"@{username}"
        elif first_name:
            operator_display = first_name
        else:
            operator_display = str(getattr(from_user, "id", ""))

    user_id = str(getattr(from_user, "id", "")) if from_user else ""

    # 1. Deduplication
    if _mark_processed(request_id, action):
        logger.info(
            "telegram card event: duplicate click ignored request_id=%s",
            request_id[:8],
        )
        try:
            await query.answer(
                text="Already processed.",
                show_alert=False,
            )
        except Exception:
            pass
        return

    logger.info(
        "telegram card event: action=%s request_id=%s operator=%s",
        action,
        request_id[:8],
        operator_display,
    )

    # 2. Retrieve cached context
    cached = _get_request_context(request_id)
    tool_name = cached.get("tool_name", "tool") if cached else "tool"
    body_text = cached.get("body_text", "") if cached else ""
    session_ctx = cached.get("session_ctx", {}) if cached else {}

    # 3. Answer the callback query (toast)
    toast_text = (
        f"✅ Approved: {tool_name}"
        if action == "approve"
        else f"🚫 Denied: {tool_name}"
    )
    try:
        await query.answer(text=toast_text, show_alert=False)
    except Exception:
        logger.debug("telegram: answer_callback_query failed")

    # 4. Edit the original message to show resolved status
    await _update_message_resolved(
        query,
        tool_name=tool_name,
        action=action,
        operator_display=operator_display,
        body_text=body_text,
    )

    # 5. Inject /approval command into the message queue
    _enqueue_approval_command(
        channel,
        action=action,
        request_id=request_id,
        session_ctx=session_ctx,
        user_id=user_id,
    )


# =====================================================================
# Internals
# =====================================================================


def _parse_callback_data(
    callback_data: str,
) -> Optional[Dict[str, str]]:
    """Parse callback_data like 'tga:{request_id}' or 'tgd:{request_id}'."""
    if callback_data.startswith(APPROVE_PREFIX):
        return {
            "action": "approve",
            "request_id": callback_data[len(APPROVE_PREFIX) :],
        }
    if callback_data.startswith(DENY_PREFIX):
        return {
            "action": "deny",
            "request_id": callback_data[len(DENY_PREFIX) :],
        }
    return None


async def _update_message_resolved(
    query: Any,
    *,
    tool_name: str,
    action: str,
    operator_display: str,
    body_text: str,
) -> None:
    """Edit the original approval message to show resolved status."""
    resolved_text = build_resolved_text(
        tool_name=tool_name,
        action=action,
        operator_display=operator_display,
        body_text=body_text,
    )
    # Use MarkdownV2 only for compact (no body) cards; plain text when
    # body is present to avoid parse errors from raw body content.
    edit_kwargs: Dict[str, Any] = {
        "text": resolved_text,
        "reply_markup": None,
    }
    if not body_text:
        edit_kwargs["parse_mode"] = ParseMode.MARKDOWN_V2
    try:
        await query.edit_message_text(**edit_kwargs)
        logger.info(
            "telegram approval card updated: action=%s operator=%s",
            action,
            operator_display,
        )
    except BadRequest as exc:
        if "not modified" not in str(exc).lower():
            logger.warning(
                "telegram approval card update failed: %s",
                exc,
            )
    except Exception:
        logger.exception("telegram approval card update failed")


def _enqueue_approval_command(
    channel: "TelegramChannel",
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
            "telegram card action: channel enqueue not set, dropping %s %s",
            action,
            request_id[:8],
        )
        return

    sender_id = str(session_ctx.get("sender_id") or user_id or "")
    session_id = str(session_ctx.get("session_id") or "")
    chat_id = str(session_ctx.get("chat_id") or "")
    is_group = bool(session_ctx.get("is_group", False))

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
            "chat_id": chat_id,
            "user_id": sender_id,
            "is_group": is_group,
            "from_card_action": True,
        },
    }

    message_thread_id = session_ctx.get("message_thread_id")
    if message_thread_id is not None:
        meta_dict = payload["meta"]
        assert isinstance(meta_dict, dict)
        meta_dict["message_thread_id"] = message_thread_id

    try:
        enqueue(payload)
        logger.info(
            "telegram card action enqueued: cmd=%s request=%s session=%s",
            command_text,
            request_id[:8],
            session_id[:12],
        )
    except Exception:
        logger.exception(
            "telegram card action: enqueue failed: %s %s",
            action,
            request_id[:8],
        )
