# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Shared helpers used by QQ card kinds.

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
    """Routing info encoded into button action.data so the inbound
    handler can recover the original session/sender/chat."""
    meta = send_meta or {}
    message_type = str(meta.get("message_type") or "c2c")
    sender_id = str(meta.get("sender_id") or "")
    session_id = str(meta.get("session_id") or to_handle or "")
    group_openid = str(meta.get("group_openid") or "")
    channel_id = str(meta.get("channel_id") or "")
    guild_id = str(meta.get("guild_id") or "")
    message_id = str(meta.get("message_id") or "")

    return {
        "sid": session_id,
        "sender": sender_id,
        "mt": message_type,
        "goid": group_openid,
        "cid": channel_id,
        "gid": guild_id,
        "mid": message_id,
    }


__all__ = [
    "extract_meta",
    "extract_body_text",
    "build_session_ctx",
]
