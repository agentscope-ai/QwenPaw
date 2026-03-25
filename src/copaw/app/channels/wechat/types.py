# -*- coding: utf-8 -*-
"""Type helpers for Wechat channel payload mapping."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from ..base import (
    AudioContent,
    ContentType,
    FileContent,
    ImageContent,
    OutgoingContentPart,
    TextContent,
    VideoContent,
)


MESSAGE_TYPE_USER = 1
MESSAGE_TYPE_BOT = 2

MESSAGE_STATE_NEW = 0
MESSAGE_STATE_GENERATING = 1
MESSAGE_STATE_FINISH = 2

MESSAGE_ITEM_TEXT = 1
MESSAGE_ITEM_IMAGE = 2
MESSAGE_ITEM_VOICE = 3
MESSAGE_ITEM_FILE = 4
MESSAGE_ITEM_VIDEO = 5

UPLOAD_MEDIA_IMAGE = 1
UPLOAD_MEDIA_VIDEO = 2
UPLOAD_MEDIA_FILE = 3
UPLOAD_MEDIA_VOICE = 4

TYPING_STATUS_TYPING = 1
TYPING_STATUS_CANCEL = 2


@dataclass(slots=True)
class UploadResult:
    """CDN upload result used to construct outbound media items."""

    encrypted_query_param: str
    aes_key_b64: str
    file_size: int
    file_size_cipher: int


def message_item_list_to_parts(
    item_list: Iterable[Dict[str, Any]],
) -> List[OutgoingContentPart]:
    """Convert Wechat message item list into runtime content parts."""
    parts: List[OutgoingContentPart] = []
    for item in item_list:
        item_type = int(item.get("type") or 0)

        if item_type == MESSAGE_ITEM_TEXT:
            text = ((item.get("text_item") or {}).get("text") or "").strip()
            if text:
                parts.append(TextContent(type=ContentType.TEXT, text=text))
            continue

        if item_type == MESSAGE_ITEM_IMAGE:
            media = (item.get("image_item") or {}).get("media") or {}
            query = media.get("encrypt_query_param")
            if query:
                parts.append(
                    ImageContent(
                        type=ContentType.IMAGE,
                        image_url=f"wechat://cdn/{query}",
                    ),
                )
            continue

        if item_type == MESSAGE_ITEM_VIDEO:
            media = (item.get("video_item") or {}).get("media") or {}
            query = media.get("encrypt_query_param")
            if query:
                parts.append(
                    VideoContent(
                        type=ContentType.VIDEO,
                        video_url=f"wechat://cdn/{query}",
                    ),
                )
            continue

        if item_type == MESSAGE_ITEM_FILE:
            file_item = item.get("file_item") or {}
            media = file_item.get("media") or {}
            query = media.get("encrypt_query_param")
            if query:
                filename = file_item.get("file_name") or "attachment.bin"
                parts.append(
                    FileContent(
                        type=ContentType.FILE,
                        filename=filename,
                        file_url=f"wechat://cdn/{query}",
                    ),
                )
            continue

        if item_type == MESSAGE_ITEM_VOICE:
            voice_item = item.get("voice_item") or {}
            text = (voice_item.get("text") or "").strip()
            if text:
                parts.append(TextContent(type=ContentType.TEXT, text=text))
                continue
            media = voice_item.get("media") or {}
            query = media.get("encrypt_query_param")
            if query:
                parts.append(
                    AudioContent(
                        type=ContentType.AUDIO,
                        data=f"wechat://cdn/{query}",
                    ),
                )
    return parts


def build_text_item(text: str) -> Dict[str, Any]:
    """Build Wechat text item payload."""
    return {
        "type": MESSAGE_ITEM_TEXT,
        "text_item": {"text": text},
    }


def build_image_item(upload: UploadResult) -> Dict[str, Any]:
    """Build Wechat image item payload from uploaded CDN reference."""
    return {
        "type": MESSAGE_ITEM_IMAGE,
        "image_item": {
            "media": {
                "encrypt_query_param": upload.encrypted_query_param,
                "aes_key": upload.aes_key_b64,
            },
            "hd_size": upload.file_size_cipher,
            "mid_size": upload.file_size_cipher,
        },
    }


def build_video_item(upload: UploadResult) -> Dict[str, Any]:
    """Build Wechat video item payload from uploaded CDN reference."""
    return {
        "type": MESSAGE_ITEM_VIDEO,
        "video_item": {
            "media": {
                "encrypt_query_param": upload.encrypted_query_param,
                "aes_key": upload.aes_key_b64,
            },
            "video_size": upload.file_size_cipher,
        },
    }


def build_file_item(upload: UploadResult, filename: str) -> Dict[str, Any]:
    """Build Wechat file item payload from uploaded CDN reference."""
    return {
        "type": MESSAGE_ITEM_FILE,
        "file_item": {
            "media": {
                "encrypt_query_param": upload.encrypted_query_param,
                "aes_key": upload.aes_key_b64,
            },
            "file_name": filename,
            "len": str(upload.file_size),
        },
    }


def media_type_for_part(part: OutgoingContentPart) -> Optional[int]:
    """Map runtime content part type to upload media type."""
    part_type = getattr(part, "type", None)
    if part_type == ContentType.IMAGE:
        return UPLOAD_MEDIA_IMAGE
    if part_type == ContentType.VIDEO:
        return UPLOAD_MEDIA_VIDEO
    if part_type == ContentType.FILE:
        return UPLOAD_MEDIA_FILE
    if part_type == ContentType.AUDIO:
        return UPLOAD_MEDIA_VOICE
    return None
