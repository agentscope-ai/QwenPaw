# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Shared helpers used by Telegram card kinds.

Covers extracting metadata / body text from runtime Msg objects and
building stateless routing context for button callbacks.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# Event / message extraction
# ---------------------------------------------------------------------


def extract_meta(event: Any) -> Optional[Dict[str, Any]]:
    """Return the original ``Msg.metadata`` dict, unwrapping the
    ``metadata.metadata`` nesting the runtime introduces."""
    metadata = getattr(event, "metadata", None) or {}
    if not isinstance(metadata, dict):
        return None
    inner = metadata.get("metadata")
    meta = inner if isinstance(inner, dict) else metadata
    return meta if isinstance(meta, dict) else None


def extract_body_text(content: Any) -> str:
    """Flatten ``Message.content`` into a plain string."""
    if not content:
        return ""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for item in content:
        if hasattr(item, "text") and item.text:
            parts.append(item.text)
        elif isinstance(item, dict) and item.get("type") == "text":
            parts.append(item.get("text") or "")
    return "".join(parts)


# ---------------------------------------------------------------------
# Routing context
# ---------------------------------------------------------------------


def build_session_ctx(
    to_handle: str,
    send_meta: Dict[str, Any],
) -> Dict[str, Any]:
    """Routing info cached alongside callback_data so the inbound
    handler can recover the original session/sender/chat."""
    meta = send_meta or {}
    chat_id = str(meta.get("chat_id") or to_handle or "")
    sender_id = str(meta.get("sender_id") or meta.get("user_id") or "")
    session_id = str(meta.get("session_id") or "")
    is_group = bool(meta.get("is_group", False))
    message_thread_id = meta.get("message_thread_id")

    ctx: Dict[str, Any] = {
        "chat_id": chat_id,
        "sender_id": sender_id,
        "session_id": session_id,
        "is_group": is_group,
    }
    if message_thread_id is not None:
        ctx["message_thread_id"] = message_thread_id
    return ctx


__all__ = [
    "extract_meta",
    "extract_body_text",
    "build_session_ctx",
]
