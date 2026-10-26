# -*- coding: utf-8 -*-
"""Messaging transports backed by the host queue, access policy and runtime."""

from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Protocol

from .events import ChatEvent, StreamContent
from .messages import ContentBlock
from .tools import ToolContext, ConfigField


@dataclass(frozen=True)
class ChannelMessage:
    sender_id: str
    content: tuple[ContentBlock, ...]
    session_id: str = ""
    reply_to: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    is_group: bool = False
    mentioned: bool = False
    message_id: str = ""
    acl_sender_id: str = ""
    session_scope: Literal["default", "sender", "group"] = "default"


@dataclass(frozen=True)
class OutgoingMessage:
    target: str
    content: tuple[StreamContent, ...]
    metadata: dict[str, Any] = field(default_factory=dict)
    run_id: str = ""
    require_delivery: bool = False


@dataclass(frozen=True)
class ChannelStreamEvent:
    phase: Literal["start", "delta", "end"]
    target: str
    event: ChatEvent
    stream_type: str
    text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    run_id: str = ""


@dataclass(frozen=True)
class ChannelRunEvent:
    phase: Literal["start", "end"]
    run_id: str
    target: str
    session_id: str
    user_id: str
    message_ids: tuple[str, ...]
    status: Literal["running", "completed", "failed", "cancelled", "rejected"]
    metadata: dict[str, Any] = field(default_factory=dict)
    sender_id: str = ""
    acl_sender_id: str = ""


@dataclass(frozen=True)
class ChannelHealth:
    status: Literal["healthy", "unhealthy", "disabled", "unsupported"]
    detail: str = ""


@dataclass(frozen=True)
class ChannelContext(ToolContext):
    channel_name: str = ""
    _receive: Callable = field(default=None, repr=False, compare=False)

    def receive(self, message: ChannelMessage) -> None:
        """Enqueue an incoming message on the owning workspace's channel."""
        self._receive(message)


class ChannelBackend(Protocol):
    async def start(self, context: ChannelContext) -> None:
        ...

    async def stop(self, context: ChannelContext) -> bool:
        ...

    async def send(
        self,
        context: ChannelContext,
        message: OutgoingMessage,
    ) -> None:
        ...


class StreamingChannelBackend(ChannelBackend, Protocol):
    async def on_stream(
        self,
        context: ChannelContext,
        event: ChannelStreamEvent,
    ) -> None:
        ...


class RunAwareChannelBackend(ChannelBackend, Protocol):
    async def on_run(
        self,
        context: ChannelContext,
        event: ChannelRunEvent,
    ) -> None:
        ...


@dataclass(frozen=True)
class ChannelSpec:
    name: str
    label: str
    create: Callable[[], ChannelBackend]
    config_fields: tuple[ConfigField, ...] = ()
    streaming: bool = False
    description: str = ""
    icon: str = ""
    doc_url: str = ""
