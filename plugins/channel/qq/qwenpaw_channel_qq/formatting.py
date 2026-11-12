# -*- coding: utf-8 -*-
"""QQ route and formatting algorithms retained from the legacy channel."""

from __future__ import annotations
import json
import re
from typing import Any, Dict, Optional
from .errors import QQApiError

_URL_PATTERN = re.compile(r"https?://[^\s]+|www\.[^\s]+", re.IGNORECASE)

_BARE_DOMAIN_PATTERN = re.compile(
    r"https?://[^\s]+|www\.[^\s]+"
    r"|\b[\w][\w.-]*\."
    r"(?:com|cn|org|net|edu|gov|io|co|cc|tv|me|info|biz|app|dev|top|xyz"
    r"|site|vip|shop|tech|club|pro|live|mobi|asia|wiki)"
    r"(?:\.[a-z]{2,3})?\b(?:/[^\s]*)?",
    re.IGNORECASE,
)

_IMAGE_TAG_PATTERN = re.compile(r"\[Image: (https?://[^\]]+)\]", re.IGNORECASE)

_MEDIA_PATH_PREFIX = {
    "c2c": "/v2/users",
    "group": "/v2/groups",
}


def _sanitize_qq_text(text: str) -> tuple[str, bool]:
    """QQ API disallows URL links in plain messages.

    Return the sanitized text and whether any URL was removed.
    """
    if not text:
        return "", False
    sanitized, count = _URL_PATTERN.subn("[链接已省略]", text)
    return sanitized, count > 0


def _aggressive_sanitize_qq_text(text: str) -> tuple[str, bool]:
    """More aggressive URL stripping – also catches bare domain patterns.

    Used as a second-level fallback when QQ still rejects the message
    because of URL-like content that ``_sanitize_qq_text`` did not catch.
    """
    if not text:
        return "", False
    sanitized, count = _BARE_DOMAIN_PATTERN.subn("[链接已省略]", text)
    return sanitized, count > 0


def _is_url_content_error(exc: Exception) -> bool:
    """Return *True* if QQ rejected the message because it contains a URL."""
    if not isinstance(exc, QQApiError):
        return False
    try:
        payload_text = json.dumps(exc.data, ensure_ascii=False).lower()
    except Exception:
        payload_text = str(exc.data).lower()
    return (
        "304003" in payload_text
        or "40034028" in payload_text
        or "不允许包含url" in payload_text
    )


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _should_plaintext_fallback_from_markdown(exc: Exception) -> bool:
    """Only fallback for explicit markdown payload validation failures."""
    if not isinstance(exc, QQApiError):
        return False
    if exc.status < 400 or exc.status >= 500:
        return False
    try:
        payload_text = json.dumps(exc.data, ensure_ascii=False).lower()
    except Exception:
        payload_text = str(exc.data).lower()

    # Check for markdown-related error messages or codes
    return (
        "markdown" in payload_text
        or "msg_type" in payload_text
        or "msg type" in payload_text
        or "message type" in payload_text
        or "50056" in payload_text  # 不允许发送原生 markdown
        or "不允许发送原生 markdown" in payload_text
        or "40034012" in payload_text  # err_code for markdown not allowed
    )


def _media_path(
    message_type: str,
    openid: str,
    suffix: str,
) -> Optional[str]:
    """Build media API path or return None if unsupported."""
    prefix = _MEDIA_PATH_PREFIX.get(message_type)
    if not prefix:
        return None
    return f"{prefix}/{openid}/{suffix}"


def _resolve_send_path(
    message_type: str,
    sender_id: str,
    channel_id: Optional[str],
    group_openid: Optional[str],
    guild_id: Optional[str] = None,
) -> tuple[str, bool, str]:
    """Return (api_path, use_msg_seq, seq_key)."""
    if message_type == "dm":
        if not guild_id:
            raise ValueError("QQ guild DM route requires guild_id")
        return (
            f"/dms/{guild_id}/messages",
            False,
            "",
        )
    if message_type == "group":
        if not group_openid:
            raise ValueError("QQ group route requires group_openid")
        return (
            f"/v2/groups/{group_openid}/messages",
            True,
            "group",
        )
    if message_type == "guild":
        if not channel_id:
            raise ValueError("QQ guild route requires channel_id")
        return (
            f"/channels/{channel_id}/messages",
            False,
            "",
        )
    if message_type == "c2c":
        if not sender_id:
            raise ValueError("QQ C2C route requires user_openid")
        return (
            f"/v2/users/{sender_id}/messages",
            True,
            "c2c",
        )
    raise ValueError(f"Unsupported QQ message_type: {message_type}")


def resolve_session_id(
    sender_id: str,
    channel_meta: Optional[Dict[str, Any]] = None,
) -> str:
    """Return a session ID scoped to one QQ conversation."""
    meta = channel_meta or {}
    message_type = str(meta.get("message_type") or "c2c")
    if message_type == "group":
        group_openid = str(meta.get("group_openid") or "unknown")
        return f"qq:group:{group_openid}"
    if message_type == "guild":
        channel_id = str(meta.get("channel_id") or "unknown")
        return f"qq:guild:{channel_id}"
    if message_type == "dm":
        guild_id = str(meta.get("guild_id") or "unknown")
        return f"qq:dm:{guild_id}"
    return f"qq:c2c:{sender_id or 'unknown'}"


def _route_meta_from_handle(to_handle: str) -> Dict[str, str]:
    """Decode a QQ session ID or direct handle into routing metadata."""
    handle = (to_handle or "").strip()
    routes = (
        ("qq:c2c:", "c2c", "sender_id"),
        ("qq:group:", "group", "group_openid"),
        ("qq:guild:", "guild", "channel_id"),
        ("qq:dm:", "dm", "guild_id"),
        ("qq:", "c2c", "sender_id"),
        ("group:", "group", "group_openid"),
        ("channel:", "guild", "channel_id"),
    )
    for prefix, message_type, target_key in routes:
        if handle.startswith(prefix):
            target = handle.removeprefix(prefix)
            if target == "unknown":
                return {"message_type": message_type}
            return {
                "message_type": message_type,
                target_key: target,
            }
    return {}


def _find_quoted_element(
    d: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Find the quoted msg_elements entry by matching ref_msg_idx."""
    msg_elements = d.get("msg_elements")
    if not msg_elements or not isinstance(msg_elements, list):
        return None

    scene_ext = (d.get("message_scene") or {}).get("ext") or []

    ref_idx: str = ""
    own_idx: str = ""
    for entry in scene_ext:
        if isinstance(entry, str):
            if entry.startswith("ref_msg_idx="):
                ref_idx = entry[len("ref_msg_idx=") :]
            elif entry.startswith("msg_idx="):
                own_idx = entry[len("msg_idx=") :]

    if not ref_idx:
        return None

    for elem in msg_elements:
        if not isinstance(elem, dict):
            continue
        if elem.get("msg_idx") == ref_idx:
            return elem

    for elem in msg_elements:
        if not isinstance(elem, dict):
            continue
        elem_idx = elem.get("msg_idx", "")
        if elem_idx and elem_idx != own_idx:
            return elem

    return None
