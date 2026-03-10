# -*- coding: utf-8 -*-
"""Typed structures for the WeCom custom channel plugin."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass(slots=True)
class WeComRoute:
    """Persisted mapping from session id to a sendable target."""

    session_id: str
    target_type: str
    target_id: str
    chat_type: str
    last_seen_at: int
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class WeComIncomingMessage:
    """Normalized incoming message envelope used inside the plugin."""

    message_id: str
    sender_id: str
    chat_type: str
    chat_id: str = ""
    message_type: str = ""
    request_id: str = ""
    raw_body: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class WeComSendTarget:
    """Normalized send target derived from CoPaw to_handle strings."""

    target_type: str
    target_id: str
    raw_handle: str


@dataclass(slots=True)
class WeComMediaDescriptor:
    """Descriptor for media payloads before download/upload is added."""

    media_type: str
    sdk_file_id: str = ""
    aes_key: str = ""
    file_name: str = ""
    file_size: int = 0
    extra: Dict[str, Any] = field(default_factory=dict)


def route_to_dict(route: WeComRoute) -> Dict[str, Any]:
    """Serialize a route for JSON persistence."""

    return {
        "session_id": route.session_id,
        "target_type": route.target_type,
        "target_id": route.target_id,
        "chat_type": route.chat_type,
        "last_seen_at": route.last_seen_at,
        "extra": dict(route.extra),
    }


def route_from_dict(payload: Dict[str, Any]) -> Optional[WeComRoute]:
    """Deserialize a route from a JSON object."""

    if not isinstance(payload, dict):
        return None
    session_id = str(payload.get("session_id") or "").strip()
    target_type = str(payload.get("target_type") or "").strip()
    target_id = str(payload.get("target_id") or "").strip()
    chat_type = str(payload.get("chat_type") or "").strip()
    if not (session_id and target_type and target_id and chat_type):
        return None
    return WeComRoute(
        session_id=session_id,
        target_type=target_type,
        target_id=target_id,
        chat_type=chat_type,
        last_seen_at=int(payload.get("last_seen_at") or 0),
        extra=dict(payload.get("extra") or {}),
    )
