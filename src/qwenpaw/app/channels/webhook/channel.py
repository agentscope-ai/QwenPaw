# -*- coding: utf-8 -*-
# pylint: disable=too-many-arguments
"""Webhook channel — passive HTTP receiver + outbound reply sender."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from qwenpaw.schemas import (
    AgentRequest,
    ContentType,
    Message,
    MessageType,
    Role,
    TextContent,
)

from ..base import BaseChannel, OnReplySent, ProcessHandler
from .sender import send_webhook_reply

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

DEFAULT_BIND_ADDRESS = "127.0.0.1"
DEFAULT_PORT = 9070


@dataclass
class WebhookChannelConfig:
    """Per-channel configuration for a webhook instance."""

    channel_id: str
    port: int = DEFAULT_PORT
    bind_address: str = DEFAULT_BIND_ADDRESS
    outbound_url: Optional[str] = None
    secret: Optional[str] = None


@dataclass
class GenericWebhookEvent:
    """Opaque envelope for an incoming webhook POST."""

    raw_body: bytes
    parsed: Dict[str, Any]
    headers: Dict[str, str]
    channel_id: str
    timestamp: datetime
    meta: Dict[str, Any] = field(default_factory=dict)


class WebhookChannel(BaseChannel):
    """Generic HTTP webhook channel.

    Inbound: ``POST /webhooks/<channel_id>`` accepts arbitrary JSON
    payloads, optionally verified against ``X-QwenPaw-Signature`` (HMAC-
    SHA256 of the raw body). Outbound: agent replies are POSTed to
    ``config.outbound_url`` with the same signature scheme.

    The channel runs its own uvicorn server in a background task; it
    does not require the QwenPaw main app to be running.
    """

    channel = "webhook"

    def __init__(
        self,
        process: ProcessHandler,
        enabled: bool = True,
        channel_id: str = "default",
        port: int = DEFAULT_PORT,
        bind_address: str = DEFAULT_BIND_ADDRESS,
        outbound_url: Optional[str] = None,
        secret: Optional[str] = None,
        bot_prefix: str = "",
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        no_text_debounce: bool = True,
        filter_thinking: bool = False,
        dm_policy: str = "open",
        group_policy: str = "open",
        allow_from: Optional[List[str]] = None,
        deny_message: str = "",
        streaming_enabled: bool = False,
    ):
        super().__init__(
            process=process,
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            no_text_debounce=no_text_debounce,
            filter_thinking=filter_thinking,
            dm_policy=dm_policy,
            group_policy=group_policy,
            allow_from=allow_from,
            deny_message=deny_message,
            streaming_enabled=streaming_enabled,
        )
        self.enabled = enabled
        self.bot_prefix = bot_prefix
        self.config = WebhookChannelConfig(
            channel_id=channel_id,
            port=port,
            bind_address=bind_address,
            outbound_url=outbound_url,
            secret=secret,
        )
        self._server_handle: Optional[Any] = None

    # ── Lifecycle ──────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the uvicorn webhook server in the background."""
        if not self.enabled:
            logger.debug("[webhook] channel disabled, skipping start")
            return
        from .server import start_webhook_server

        if self._server_handle is not None:
            logger.debug("[webhook] already running, skipping start")
            return
        self._server_handle = await asyncio.to_thread(
            start_webhook_server,
            self,
        )
        logger.info(
            "[webhook] server listening at %s/webhooks/%s",
            self._server_handle.url,
            self.config.channel_id,
        )

    async def stop(self) -> None:
        """Stop the uvicorn webhook server."""
        if self._server_handle is None:
            return
        try:
            await self._server_handle.close()
        finally:
            self._server_handle = None

    # ── Outbound send ──────────────────────────────────────────────────

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """POST ``text`` to ``to_handle`` (or ``config.outbound_url``)."""
        if not self.enabled:
            logger.debug("[webhook] channel disabled, skipping send")
            return
        url = to_handle or self.config.outbound_url
        if not url:
            logger.warning(
                "[webhook] no outbound_url configured, dropping reply",
            )
            return
        payload: Dict[str, Any] = {
            "text": text,
            "channel": self.channel,
            "channel_id": self.config.channel_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        if meta:
            payload["meta"] = {
                k: v for k, v in meta.items() if not k.startswith("_")
            }
        await send_webhook_reply(url, payload, self.config.secret)

    async def send_content_parts(
        self,
        to_handle: str,
        parts: List[Any],
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send content parts by concatenating text into the ``text`` field."""
        if not self.enabled:
            return
        text_chunks: List[str] = []
        media_urls: List[str] = []
        for p in parts or []:
            t = getattr(p, "type", None)
            if t == ContentType.TEXT and getattr(p, "text", None):
                text_chunks.append(p.text)
            elif t == ContentType.REFUSAL and getattr(p, "refusal", None):
                text_chunks.append(p.refusal)
            elif t in (
                ContentType.IMAGE,
                ContentType.VIDEO,
                ContentType.AUDIO,
                ContentType.FILE,
            ):
                url = (
                    getattr(p, "image_url", None)
                    or getattr(p, "video_url", None)
                    or getattr(p, "file_url", None)
                    or getattr(p, "file_id", None)
                )
                if url:
                    media_urls.append(f"[{t}] {url}")
        body = "\n".join(text_chunks + media_urls).strip()
        if not body:
            return
        await self.send(to_handle, body, meta)

    # ── Inbound dispatch ───────────────────────────────────────────────

    async def dispatch_event(self, event: GenericWebhookEvent) -> None:
        """Convert a ``GenericWebhookEvent`` into an ``AgentRequest`` and
        forward to the agent runtime via the base-class pipeline."""
        payload = {
            "channel_id": self.channel,
            "sender_id": event.parsed.get("sender_id") or event.channel_id,
            "session_id": event.parsed.get("session_id") or event.channel_id,
            "content_parts": [
                TextContent(
                    type=ContentType.TEXT,
                    text=json.dumps(event.parsed, ensure_ascii=False),
                ),
            ],
            "meta": {
                "provider": "webhook",
                "kind": "event",
                "webhook_channel_id": event.channel_id,
                "webhook_timestamp": event.timestamp.isoformat(),
                "incoming_message": True,
            },
            "raw_body_bytes": len(event.raw_body),
            "headers": dict(event.headers),
        }
        await self.consume_one(payload)

    def build_agent_request_from_native(
        self,
        native_payload: Any,
    ) -> AgentRequest:
        """Convert a webhook native dict into an ``AgentRequest``."""
        if isinstance(native_payload, dict):
            payload = native_payload
        else:
            payload = {}
        channel_id = payload.get("channel_id") or self.channel
        sender_id = payload.get("sender_id") or ""
        session_id = payload.get("session_id") or self.resolve_session_id(
            sender_id,
            payload.get("meta"),
        )
        content_parts = payload.get("content_parts") or [
            TextContent(type=ContentType.TEXT, text=" "),
        ]
        msg = Message(
            type=MessageType.MESSAGE,
            role=Role.USER,
            content=content_parts,
        )
        request = AgentRequest(
            session_id=session_id,
            user_id=sender_id,
            input=[msg],
            channel=channel_id,
        )
        meta = payload.get("meta") or {}
        request.channel_meta = meta
        return request

    def resolve_session_id(
        self,
        sender_id: str,
        channel_meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Webhooks are scoped per ``channel_id``; all events on the same
        webhook instance share a session unless ``session_id`` is supplied
        in the payload or meta.
        """
        meta = channel_meta or {}
        explicit = meta.get("session_id") or ""
        if explicit:
            return f"webhook:{explicit}"
        return f"webhook:{self.config.channel_id}"

    # ── Constructors ───────────────────────────────────────────────────

    @classmethod
    def from_env(
        cls,
        process: ProcessHandler,
        on_reply_sent: OnReplySent = None,
    ) -> "WebhookChannel":
        """Build a channel from ``WEBHOOK_*`` environment variables."""
        channel_id = os.getenv("WEBHOOK_CHANNEL_ID", "default")
        port = int(os.getenv("WEBHOOK_PORT", str(DEFAULT_PORT)))
        bind = os.getenv("WEBHOOK_BIND", DEFAULT_BIND_ADDRESS)
        outbound_url = os.getenv("WEBHOOK_OUTBOUND_URL") or None
        secret = os.getenv("WEBHOOK_SECRET") or None
        return cls(
            process=process,
            enabled=os.getenv("WEBHOOK_CHANNEL_ENABLED", "0") == "1",
            channel_id=channel_id,
            port=port,
            bind_address=bind,
            outbound_url=outbound_url,
            secret=secret,
            on_reply_sent=on_reply_sent,
        )

    @classmethod
    def from_config(
        cls,
        process: ProcessHandler,
        config: Any,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        no_text_debounce: bool = True,
        filter_thinking: bool = False,
    ) -> "WebhookChannel":
        """Build a channel from a ``WebhookChannelConfig``-shaped object."""
        return cls(
            process=process,
            enabled=getattr(config, "enabled", True),
            channel_id=getattr(config, "channel_id", "default"),
            port=getattr(config, "port", DEFAULT_PORT),
            bind_address=getattr(config, "bind_address", DEFAULT_BIND_ADDRESS),
            outbound_url=getattr(config, "outbound_url", None),
            secret=getattr(config, "secret", None),
            bot_prefix=getattr(config, "bot_prefix", ""),
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            no_text_debounce=no_text_debounce,
            filter_thinking=filter_thinking,
            dm_policy=getattr(config, "dm_policy", "open"),
            group_policy=getattr(config, "group_policy", "open"),
            allow_from=getattr(config, "allow_from", None),
            deny_message=getattr(config, "deny_message", ""),
        )
