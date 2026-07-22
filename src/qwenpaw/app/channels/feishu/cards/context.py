# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Shared helpers used by individual Feishu card kinds.

Covers extracting metadata / body text from runtime ``Msg`` objects and
building stateless routing context for card action callbacks.
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
    """Flatten ``Message.content`` (str / list of TextContent / list of
    ``{"type": "text", "text": ...}`` dicts) into a plain string."""
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
    receive_id: str,
    receive_id_type: str,
) -> Dict[str, Any]:
    """Routing info embedded in button ``value`` so the inbound handler
    can recover the original session/sender/chat for re-injection."""
    session_id = ""
    handle = (to_handle or "").strip()
    if handle.startswith("feishu:sw:"):
        session_id = handle[len("feishu:sw:") :]
    return {
        "session_id": session_id,
        "sender_id": str(send_meta.get("feishu_sender_id") or ""),
        "receive_id": receive_id,
        "receive_id_type": receive_id_type,
        "chat_id": str(send_meta.get("feishu_chat_id") or ""),
        "chat_type": str(send_meta.get("feishu_chat_type") or "p2p"),
        "is_group": bool(send_meta.get("is_group")),
    }


__all__ = [
    "extract_meta",
    "extract_body_text",
    "build_session_ctx",
]
