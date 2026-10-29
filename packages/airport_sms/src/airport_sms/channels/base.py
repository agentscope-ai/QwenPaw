"""通道入站消息与出站卡片。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InboundMessage:
    """通道入站。"""

    user_id: str
    text: str
    group_id: str
    site_id: str
    mentioned: bool = True
    media_kind: str | None = None
    media_bytes: bytes | None = None


@dataclass(frozen=True)
class OutboundCard:
    """出站卡片。"""

    case_id: str
    state: str
    text: str


__all__ = ["InboundMessage", "OutboundCard"]
