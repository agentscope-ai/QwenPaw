# -*- coding: utf-8 -*-
"""Windowing helpers for paginated chat history loading.

``GET /api/chats/{chat_id}`` used to return the whole message history in a
single response. For long-running chats (real-world workspaces reach 1 MB+
of JSON and thousands of messages) this makes the console slow to open and
can freeze the webview entirely (see issues #3915 and #6635). The helpers
here implement a small windowing layer so the endpoint can serve the most
recent messages first and older pages on demand:

- ``limit=0`` (default) keeps the original behaviour (full history).
- ``before`` is a cursor value taken from ``metadata.original_id`` — the
  persistent AgentScope ``Msg`` id. ``Message.id`` cannot be used as a
  cursor because ``agentscope_msg_to_message`` regenerates it on every
  request.
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

__all__ = ["apply_history_window", "message_original_id"]


def message_original_id(message: Any) -> Optional[str]:
    """Return ``metadata.original_id`` of a chat message, if present."""
    metadata = getattr(message, "metadata", None) or {}
    if isinstance(metadata, dict):
        value = metadata.get("original_id")
        if isinstance(value, str):
            return value
    return None


def apply_history_window(
    messages: List[Any],
    limit: int = 0,
    before: Optional[str] = None,
) -> Tuple[List[Any], int, bool]:
    """Slice a chat history into a window of the most recent messages.

    Args:
        messages: Full ordered history (oldest first), already converted to
            ``Message`` objects.
        limit: Maximum number of messages to return, counting from the most
            recent one. ``0`` (default) means no slicing.
        before: When set, only messages strictly older than the first
            message whose ``metadata.original_id`` equals this value are
            considered (a page of "load earlier" history). An unknown or
            stale cursor is ignored gracefully.

    Returns:
        ``(windowed_messages, total, has_more)`` where ``total`` is the
        message count before windowing and ``has_more`` reports whether
        older messages exist beyond the returned window.
    """
    total = len(messages)

    if before is not None:
        cut = next(
            (
                index
                for index, message in enumerate(messages)
                if message_original_id(message) == before
            ),
            None,
        )
        if cut is not None:
            messages = messages[:cut]

    if 0 < limit < len(messages):
        return messages[-limit:], total, True

    return messages, total, False
