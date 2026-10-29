# -*- coding: utf-8 -*-
"""Pure approval builders and instance-bounded confirmed card state."""

from __future__ import annotations
from dataclasses import dataclass
import re
from typing import Optional, Dict
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

APPROVE_PREFIX = "tga:"
DENY_PREFIX = "tgd:"
_CACHE_MAX_SIZE = 500
_PROCESSED_MAX_SIZE = 500
_MDV2_ESCAPE_RE = re.compile(r"([_*\[\]()~`>#+\-=|{}.!\\])")
NAME = "tool_guard_approval"
MESSAGE_TYPE = "tool_guard_approval"
CALLBACK_DATA_PREFIX = "tg"


@dataclass(frozen=True)
class ApprovalCardBinding:
    request_id: str
    tool_name: str
    body_text: str
    chat_id: str
    message_id: int
    message_thread_id: int | None
    session_id: str
    root_session_id: str
    user_id: str
    source_response_handle: str
    source_delivery_id: str
    instance_id: str
    generation: int


class CardCache:
    def __init__(self):
        self._request_context_cache = {}
        self._processed_requests = {}

    def _cache_request_context(
        self,
        request_id,
        tool_name,
        severity,
        body_text,
        session_ctx,
    ):
        self._request_context_cache[request_id] = {
            "tool_name": tool_name,
            "severity": severity,
            "body_text": body_text,
            "session_ctx": session_ctx,
        }
        if len(self._request_context_cache) > _CACHE_MAX_SIZE:
            keys = list(self._request_context_cache)
            for key in keys[: len(keys) // 2]:
                self._request_context_cache.pop(key, None)

    def _get_request_context(self, request_id):
        return self._request_context_cache.get(request_id)

    def _mark_processed(self, request_id, action):
        if request_id in self._processed_requests:
            return True
        self._processed_requests[request_id] = action
        if len(self._processed_requests) > _PROCESSED_MAX_SIZE:
            keys = list(self._processed_requests)
            for key in keys[: len(keys) // 2]:
                self._processed_requests.pop(key, None)
        return False


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


def _escape_mdv2(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    return _MDV2_ESCAPE_RE.sub(r"\\\1", text)


def _parse_callback_data(
    callback_data: str,
) -> Optional[Dict[str, str]]:
    """Parse callback_data like 'tga:{request_id}' or 'tgd:{request_id}'."""
    if callback_data.startswith(APPROVE_PREFIX):
        start = len(APPROVE_PREFIX)
        return {
            "action": "approve",
            "request_id": callback_data[start:],
        }
    if callback_data.startswith(DENY_PREFIX):
        start = len(DENY_PREFIX)
        return {
            "action": "deny",
            "request_id": callback_data[start:],
        }
    return None
