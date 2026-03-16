# -*- coding: utf-8 -*-
"""DingTalk content parsing and session helpers."""

from __future__ import annotations

import base64
import binascii
import logging
import os
import re
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

from agentscope_runtime.engine.schemas.agent_schemas import (
    AudioContent,
    FileContent,
    ImageContent,
    VideoContent,
)

from ..base import ContentType
from ..utils import convert_audio_file_path, file_url_to_local_path

from .constants import (
    DINGTALK_SESSION_ID_SUFFIX_LEN,
    DINGTALK_TYPE_MAPPING,
)

logger = logging.getLogger(__name__)


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
        audio_content = _dingtalk_audio_content_from_local_path(url)
        if audio_content is not None:
            return audio_content
        # Fallback to file when conversion/runtime audio cannot be built.
        return FileContent(type=ContentType.FILE, file_url=url)
    return FileContent(type=ContentType.FILE, file_url=url)


def _normalize_local_path(path_or_url: str) -> Optional[str]:
    """Normalize a local filesystem path from plain path or file:// URL."""
    if not isinstance(path_or_url, str):
        return None
    raw = path_or_url.strip()
    if not raw:
        return None
    local_path = file_url_to_local_path(raw)
    if not local_path:
        return None
    return str(Path(local_path).expanduser())


def _audio_media_type_from_path(path: str) -> str:
    ext = (os.path.splitext(path)[1] or "").lower()
    return {
        ".mp3": "mp3",
        ".wav": "wav",
    }.get(ext, "mp3")


def _dingtalk_audio_content_from_local_path(path_or_url: str) -> Optional[Any]:
    """Build AudioContent from DingTalk audio by normalizing to mp3/wav."""
    local_path = _normalize_local_path(path_or_url)
    if not local_path or not os.path.isfile(local_path):
        return None

    ext = (os.path.splitext(local_path)[1] or "").lower()
    final_path = local_path
    if ext not in (".mp3", ".wav"):
        converted_path, error = convert_audio_file_path(
            file_path=local_path,
            output_format="mp3",
        )
        if error:
            logger.info(
                "dingtalk audio conversion fallback to file: %s",
                error,
            )
            return None
        if not converted_path or not os.path.isfile(converted_path):
            return None
        final_path = converted_path

    return AudioContent(
        type=ContentType.AUDIO,
        data=Path(final_path).resolve().as_uri(),
        format=_audio_media_type_from_path(final_path),
    )


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
    has_sender_id = bool(sender_id)
    has_nickname = bool(nickname)

    suffix = sender_id[-4:] if len(sender_id) >= 4 else sender_id
    sender = f"{(nickname or 'unknown')}#{(suffix or '????')}"

    skip = (not has_sender_id) and (not has_nickname)
    return sender, skip


def conversation_id_from_chatbot_message(incoming_message: Any) -> str:
    """Extract conversation_id from DingTalk ChatbotMessage."""
    cid = getattr(incoming_message, "conversationId", None) or getattr(
        incoming_message,
        "conversation_id",
        None,
    )
    return str(cid).strip() if cid else ""


def conversation_type_from_chatbot_message(incoming_message: Any) -> str:
    """Extract conversation_type from DingTalk ChatbotMessage.

    Returns:
        "dm" for direct message (conversationType=1)
        "group" for group chat (conversationType=2)
        "dm" as default if not specified
    """
    conv_type = getattr(incoming_message, "conversationType", None) or getattr(
        incoming_message,
        "conversation_type",
        None,
    )
    if conv_type:
        return "group" if str(conv_type) == "2" else "dm"
    return "dm"


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
