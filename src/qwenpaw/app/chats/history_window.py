# -*- coding: utf-8 -*-
"""Windowing helpers for paginated chat history loading.

``GET /api/chats/{chat_id}`` used to convert the whole AgentScope ``Msg``
history and then return it. For long-running chats (real-world workspaces
reach 1 MB+ of JSON and thousands of messages) converting every ``Msg`` on
open still burns CPU and RAM even when the HTTP body is a small window
(see issues #3915 and #6635). The helpers here slice the **source** ``Msg``
list first so ``agentscope_msg_to_message`` only runs on the page that will
be sent:

- ``limit=0`` (default) keeps the original behaviour (full history).
- ``before`` is a cursor value taken from the persistent AgentScope
  ``Msg.id``. After conversion that same id is exposed as
  ``metadata.original_id``. ``Message.id`` cannot be used as a cursor
  because ``agentscope_msg_to_message`` regenerates it on every request.
- One ``Msg`` can expand into several ``Message`` objects; cutting at the
  ``Msg`` layer keeps those groups intact.
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

__all__ = [
    "apply_history_window",
    "history_cursor_id",
    "message_original_id",
]


def message_original_id(message: Any) -> Optional[str]:
    """Return ``metadata.original_id`` of a chat message, if present."""
    metadata = getattr(message, "metadata", None) or {}
    if isinstance(metadata, dict):
        value = metadata.get("original_id")
        if isinstance(value, str):
            return value
    return None


def history_cursor_id(item: Any) -> Optional[str]:
    """Return the pagination cursor for a source ``Msg`` or converted message.

    Converted ``Message`` objects carry a fresh uuid4 ``id`` on every
    request; their stable cursor is ``metadata.original_id`` (copied from
    ``Msg.id``). AgentScope ``Msg`` objects are keyed by ``id`` directly.
    Prefer ``original_id`` when present so a converted list is not windowed
    by the regenerated uuid.
    """
    original_id = message_original_id(item)
    if original_id:
        return original_id
    msg_id = getattr(item, "id", None)
    if isinstance(msg_id, str) and msg_id:
        return msg_id
    return None


def apply_history_window(
    messages: List[Any],
    limit: int = 0,
    before: Optional[str] = None,
) -> Tuple[List[Any], int, bool]:
    """Slice a source history into a window of the most recent messages.

    Args:
        messages: Full ordered history (oldest first). Typically AgentScope
            ``Msg`` objects, keyed by ``Msg.id``. Converted ``Message``
            stubs (``metadata.original_id``) are also accepted so tests can
            exercise the same cut without running conversion.
        limit: Maximum number of **source** messages to return, counting
            from the most recent one. ``0`` (default) means no slicing.
        before: When set, only messages strictly older than the first
            message whose cursor equals this value are considered (a page
            of "load earlier" history). An unknown or stale cursor is
            ignored gracefully.

    Returns:
        ``(windowed_messages, total, has_more)`` where ``total`` is the
        source-message count before windowing and ``has_more`` reports
        whether older source messages exist beyond the returned window.
    """
    total = len(messages)

    if before is not None:
        cut = next(
            (
                index
                for index, message in enumerate(messages)
                if history_cursor_id(message) == before
            ),
            None,
        )
        if cut is not None:
            messages = messages[:cut]

    if 0 < limit < len(messages):
        return messages[-limit:], total, True

    return messages, total, False
