# -*- coding: utf-8 -*-
"""DingTalk content parsing and session helpers."""

from __future__ import annotations

import base64
import binascii
import re
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

from agentscope_runtime.engine.schemas.agent_schemas import (
    # AudioContent,
    FileContent,
    ImageContent,
    VideoContent,
)

from ..base import ContentType

from .constants import (
    DINGTALK_SESSION_ID_SUFFIX_LEN,
    DINGTALK_TYPE_MAPPING,
)


_DATA_URL_RE = re.compile(
    r"^data:(?P<mime>[^;]+);base64,(?P<b64>.*)$",
    re.I | re.S,
)


def dingtalk_content_from_type(mapped: str, url: str) -> Any:
    """Build runtime Content from DingTalk type and download URL."""
    if mapped == "image":
        return ImageContent(type=ContentType.IMAGE, image_url=url)
    if mapped == "video":
        return VideoContent(type=ContentType.VIDEO, video_url=url)
    if mapped == "audio":
        # Use subtype only: runtime prefixes with "audio/" -> "audio/amr".
        # TODO: change to audio block when as support amr
        return FileContent(
            type=ContentType.FILE,
            file_url=url,
            # data=url,
            # format="amr",
        )
    return FileContent(type=ContentType.FILE, file_url=url)


def parse_data_url(data_url: str) -> tuple[bytes, Optional[str]]:
    """Return (bytes, mime or None)."""
    m = _DATA_URL_RE.match(data_url.strip())
    if not m:
        return base64.b64decode(data_url, validate=False), None

    mime = (m.group("mime") or "").strip().lower()
    b64 = m.group("b64").strip()
    try:
        data = base64.b64decode(b64, validate=False)
    except (binascii.Error, ValueError):
        data = base64.b64decode(b64 + "==", validate=False)
    return data, mime or None


def sender_from_chatbot_message(incoming_message: Any) -> tuple[str, bool]:
    """Build sender as nickname#last4(sender_id).
    Return (sender, should_skip).
    """
    nickname = (
        getattr(incoming_message, "sender_nick", None)
        or getattr(incoming_message, "senderNick", None)
        or ""
    )
    nickname = nickname.strip() if isinstance(nickname, str) else ""
    sender_id = (
        getattr(incoming_message, "sender_id", None)
        or getattr(incoming_message, "senderId", None)
        or ""
    )
    sender_id = str(sender_id).strip() if sender_id else ""
    suffix = sender_id[-4:] if len(sender_id) >= 4 else (sender_id or "????")
    sender = f"{(nickname or 'unknown')}#{suffix}"
    skip = not suffix and not nickname
    return sender, skip


def conversation_id_from_chatbot_message(incoming_message: Any) -> str:
    """Extract conversation_id from DingTalk ChatbotMessage."""
    cid = getattr(incoming_message, "conversationId", None) or getattr(
        incoming_message,
        "conversation_id",
        None,
    )
    return str(cid).strip() if cid else ""


def short_session_id_from_conversation_id(conversation_id: str) -> str:
    """Use last N chars of conversation_id as session_id."""
    n = DINGTALK_SESSION_ID_SUFFIX_LEN
    return (
        conversation_id[-n:] if len(conversation_id) >= n else conversation_id
    )


def session_param_from_webhook_url(url: str) -> Optional[str]:
    """Extract session= param from sendBySession URL for debug logging."""
    if not url or "?" not in url:
        return None
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    vals = qs.get("session", [])
    return (
        vals[0][:24] + "..."
        if vals and len(vals[0]) > 24
        else (vals[0] if vals else None)
    )


def get_type_mapping() -> dict:
    """Return DingTalk type mapping (for handler use)."""
    return dict(DINGTALK_TYPE_MAPPING)
