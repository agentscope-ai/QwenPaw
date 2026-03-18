# -*- coding: utf-8 -*-
"""
Channel schema: channel type identifiers, routing (ChannelAddress),
and conversion protocol.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol, runtime_checkable


@dataclass
class ChannelAddress:
    """
    Unified routing for send: kind + id + extra.
    Replaces ad-hoc meta keys (channel_id, user_id, session_webhook, etc.).
    """

    kind: str  # "dm" | "channel" | "webhook" | "console" | ...
    id: str
    extra: Optional[Dict[str, Any]] = None

    def to_handle(self) -> str:
        """String handle for to_handle (e.g. discord:ch:123)."""
        if self.extra and "to_handle" in self.extra:
            return str(self.extra["to_handle"])
        return f"{self.kind}:{self.id}"


# Built-in channel type identifiers. Plugin channels use arbitrary str keys.
BUILTIN_CHANNEL_TYPES = (
    "console",
    "dingtalk",
    "discord",
    "feishu",
    "imessage",
    "matrix",
    "mattermost",
    "mqtt",
    "nextcloud_talk",
    "qq",
    "telegram",
    "voice",
    "xiaoyi",
)

# ChannelType is str to allow plugin channels; built-in set above.
ChannelType = str

# Default channel when none is specified (runner / config).
DEFAULT_CHANNEL: ChannelType = "console"


@runtime_checkable
class ChannelMessageConverter(Protocol):
    """
    Protocol for channel message conversion.
    Channels convert native payloads to AgentRequest and send responses.
    """

    def build_agent_request_from_native(self, native_payload: Any) -> Any:
        """
        Convert this channel's native message payload to AgentRequest.
        Use runtime Message and Content types; no intermediate envelope.
        """

    async def send_response(
        self,
        to_handle: str,
        response: Any,
        meta: Optional[dict] = None,
    ) -> None:
        """Convert AgentResponse to channel reply and send."""
