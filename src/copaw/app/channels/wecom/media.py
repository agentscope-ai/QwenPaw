# -*- coding: utf-8 -*-
"""Media parsing helpers for the WeCom custom channel plugin."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from .schema import WeComMediaDescriptor


def extract_media_descriptor(payload: Dict[str, Any]) -> Optional[WeComMediaDescriptor]:
    """Extract a lightweight descriptor from a WeCom message body."""

    if not isinstance(payload, dict):
        return None
    msg_type = str(payload.get("msgtype") or "").strip()
    section = payload.get(msg_type)
    if not msg_type or not isinstance(section, dict):
        return None
    sdk_file_id = str(
        section.get("sdkfileid") or section.get("sdk_file_id") or ""
    ).strip()
    aes_key = str(section.get("aeskey") or section.get("aes_key") or "").strip()
    return WeComMediaDescriptor(
        media_type=msg_type,
        sdk_file_id=sdk_file_id,
        aes_key=aes_key,
        file_name=str(section.get("filename") or section.get("file_name") or "").strip(),
        file_size=int(section.get("filesize") or section.get("file_size") or 0),
        extra=dict(section),
    )


def describe_media_fallback(descriptor: Optional[WeComMediaDescriptor]) -> str:
    """Return a safe text fallback for unsupported or unavailable media."""

    if descriptor is None:
        return "Received unsupported media content."
    label = descriptor.media_type or "media"
    if descriptor.file_name:
        return f"Received {label} content: {descriptor.file_name}"
    return f"Received {label} content."


def extract_mixed_parts(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract list-like mixed payload items from WeCom message bodies."""

    if not isinstance(payload, dict):
        return []
    mixed = payload.get("mixed")
    if not isinstance(mixed, dict):
        return []
    content = mixed.get("content")
    if isinstance(content, list):
        return [item for item in content if isinstance(item, dict)]
    return []
