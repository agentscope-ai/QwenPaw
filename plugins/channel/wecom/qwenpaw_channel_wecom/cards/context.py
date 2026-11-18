# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Pure WeCom card content and historical routing-context extraction helpers."""

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
) -> Dict[str, Any]:
    """Routing info encoded into the button ``key`` so the inbound
    handler can recover the original session/sender/chat."""
    session_id = ""
    handle = (to_handle or "").strip()
    if handle.startswith("wecom:"):
        session_id = handle

    return {
        "session_id": session_id,
        "sender_id": str(send_meta.get("wecom_sender_id") or ""),
        "chatid": str(send_meta.get("wecom_chatid") or ""),
        "chat_type": str(send_meta.get("wecom_chat_type") or "single"),
    }
