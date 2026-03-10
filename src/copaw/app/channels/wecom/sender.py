# -*- coding: utf-8 -*-
"""Send target helpers for the WeCom custom channel plugin."""

from __future__ import annotations

from typing import Optional

from .constants import (
    TO_HANDLE_KIND_CHAT,
    TO_HANDLE_KIND_USER,
    TO_HANDLE_KIND_WEBHOOK,
    TO_HANDLE_PREFIX,
    WECOM_CHAT_TYPE_GROUP,
    WECOM_CHAT_TYPE_SINGLE,
)
from .schema import WeComSendTarget


def parse_send_target(to_handle: str) -> WeComSendTarget:
    """Parse a CoPaw to_handle string into a typed target."""

    raw_handle = (to_handle or "").strip()
    parts = raw_handle.split(":", 2)
    if len(parts) != 3 or parts[0] != TO_HANDLE_PREFIX or not parts[2]:
        raise ValueError(f"invalid wecom handle: {to_handle!r}")

    target_type = parts[1]
    if target_type not in {
        TO_HANDLE_KIND_USER,
        TO_HANDLE_KIND_CHAT,
        TO_HANDLE_KIND_WEBHOOK,
    }:
        raise ValueError(f"unsupported wecom handle type: {target_type!r}")

    return WeComSendTarget(
        target_type=target_type,
        target_id=parts[2],
        raw_handle=raw_handle,
    )


def build_text_message(
    text: str,
    mentioned_list: Optional[list[str]] = None,
) -> dict:
    """Build a WeCom text payload."""

    payload = {
        "msgtype": "text",
        "text": {
            "content": text,
        },
    }
    if mentioned_list:
        payload["text"]["mentioned_list"] = list(mentioned_list)
    return payload


def build_markdown_message(content: str) -> dict:
    """Build a WeCom markdown payload."""

    return {
        "msgtype": "markdown",
        "markdown": {
            "content": content,
        },
    }


def build_image_message(media_id: str) -> dict:
    """Build a WeCom image payload."""

    return {
        "msgtype": "image",
        "image": {
            "media_id": media_id,
        },
    }


def build_file_message(media_id: str) -> dict:
    """Build a WeCom file payload."""

    return {
        "msgtype": "file",
        "file": {
            "media_id": media_id,
        },
    }


def build_respond_command(req_id: str, message_body: dict) -> dict:
    """Build an aibot_respond_msg command payload."""

    return {
        "cmd": "aibot_respond_msg",
        "headers": {"req_id": req_id},
        "body": dict(message_body),
    }


def build_welcome_command(req_id: str, message_body: dict) -> dict:
    """Build an aibot_respond_welcome_msg command payload."""

    return {
        "cmd": "aibot_respond_welcome_msg",
        "headers": {"req_id": req_id},
        "body": dict(message_body),
    }


def build_stream_reply_command(
    req_id: str,
    *,
    stream_id: str,
    content: str,
    finish: bool,
) -> dict:
    """Build a streaming reply command payload."""

    return build_respond_command(
        req_id,
        {
            "msgtype": "stream",
            "stream": {
                "id": stream_id,
                "finish": bool(finish),
                "content": content,
            },
        },
    )


def build_active_markdown_command(
    req_id: str,
    *,
    chat_id: str,
    chat_type: int,
    content: str,
) -> dict:
    """Build an aibot_send_msg command for markdown proactive push."""

    return {
        "cmd": "aibot_send_msg",
        "headers": {"req_id": req_id},
        "body": {
            "chatid": chat_id,
            "chat_type": chat_type,
            "msgtype": "markdown",
            "markdown": {
                "content": content,
            },
        },
    }


def build_active_template_card_command(
    req_id: str,
    *,
    chat_id: str,
    chat_type: int,
    template_card: dict,
) -> dict:
    """Build an aibot_send_msg command for template cards."""

    return {
        "cmd": "aibot_send_msg",
        "headers": {"req_id": req_id},
        "body": {
            "chatid": chat_id,
            "chat_type": chat_type,
            "msgtype": "template_card",
            "template_card": dict(template_card),
        },
    }


def coerce_to_active_markdown(text: str) -> dict:
    """Proactive push only supports markdown/template_card; wrap text as markdown."""

    return build_markdown_message(text)


def target_to_chat_type(target: WeComSendTarget) -> int:
    """Map a parsed to_handle target to the official chat_type integer."""

    if target.target_type == TO_HANDLE_KIND_CHAT:
        return WECOM_CHAT_TYPE_GROUP
    return WECOM_CHAT_TYPE_SINGLE
