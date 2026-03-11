# -*- coding: utf-8 -*-
"""WeCom AI Bot Channel - Based on wecom-aibot-sdk.

Uses official wecom-aibot-sdk to implement WeCom AI Bot integration:
- Text/Image/Mixed/Voice/File message receiving
- Streaming message replies (typewriter effect)
- Welcome message on enter_chat event
- Automatic heartbeat keepalive and reconnection
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional

from wecom_aibot_sdk import WSClient
from wecom_aibot_sdk.types import WsFrame

from ..base import (
    BaseChannel,
    ImageContent,
    OnReplySent,
    ProcessHandler,
)
from ....config.config import WecomConfig as WecomChannelConfig
from . import handlers, stream
from .utils import save_image_to_dir

if TYPE_CHECKING:
    from agentscope_runtime.engine.schemas.agent_schemas import AgentRequest

logger = logging.getLogger(__name__)


class WecomChannel(BaseChannel):
    """WeCom AI Bot Channel."""

    channel = "wecom"

    def __init__(
        self,
        config: WecomChannelConfig,
        process: ProcessHandler,
        on_reply_sent: OnReplySent = None,
    ):
        """Initialize WeCom Channel.

        Args:
            config: WeCom configuration.
            process: Message processing function.
            on_reply_sent: Reply sent callback.
        """
        super().__init__(
            process=process,
            on_reply_sent=on_reply_sent,
            show_tool_details=True,
            filter_tool_messages=config.filter_tool_messages,
            filter_thinking=config.filter_thinking,
            dm_policy=config.dm_policy,
            group_policy=config.group_policy,
            allow_from=config.allow_from,
            deny_message=config.deny_message,
        )
        self.config = config
        self.bot_id = config.bot_id
        self.secret = config.secret
        self.media_dir = Path(config.media_dir).expanduser()
        self.media_dir.mkdir(parents=True, exist_ok=True)

        # SDK client (created on connect)
        self.client: Optional[WSClient] = None
        self.running = False
        self.active_tasks: set[asyncio.Task] = set()

    @classmethod
    def from_config(
        cls,
        process: ProcessHandler,
        config: WecomChannelConfig,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,  # noqa: ARG003
        filter_tool_messages: bool = False,  # noqa: ARG003
        filter_thinking: bool = False,  # noqa: ARG003
    ) -> "WecomChannel":
        """Create Channel instance from config."""
        return cls(
            config=config,
            process=process,
            on_reply_sent=on_reply_sent,
        )

    @classmethod
    def from_env(
        cls,
        process: ProcessHandler,
        on_reply_sent: OnReplySent = None,
    ) -> "WecomChannel":
        """Create Channel instance from environment variables."""
        config = WecomChannelConfig(
            enabled=True,
            bot_id=os.getenv("WECOM_BOT_ID", ""),
            secret=os.getenv("WECOM_SECRET", ""),
            media_dir=os.getenv("WECOM_MEDIA_DIR", "~/.copaw/media"),
        )
        return cls(
            config=config,
            process=process,
            on_reply_sent=on_reply_sent,
        )

    # -- Lifecycle -------------------------------------------------------

    async def start(self) -> None:
        """Start Channel and establish WebSocket connection."""
        if self.running:
            logger.warning("WecomChannel is already running")
            return

        if not self.bot_id or not self.secret:
            raise ValueError(
                "WeCom config incomplete: bot_id and secret are required",
            )

        self._validate_credentials()
        self.running = True
        logger.info(
            "Starting WeCom Channel, Bot ID: %s... (masked)",
            self.bot_id[:8],
        )

        # Create SDK WSClient - handles WebSocket, heartbeat, reconnection
        self.client = WSClient(bot_id=self.bot_id, secret=self.secret)
        self._register_handlers()

        try:
            await self.client.connect()
        except Exception as exc:
            logger.error("Failed to start WebSocket client: %s", exc)
            self.running = False
            raise

    def _validate_credentials(self) -> None:
        """Log warnings if credential lengths look suspicious."""
        if len(self.bot_id) < 10:
            logger.warning(
                "bot_id length looks suspicious (%d chars), check config",
                len(self.bot_id),
            )
        if len(self.secret) < 20:
            logger.warning(
                "secret length looks suspicious (%d chars), check config",
                len(self.secret),
            )

    async def stop(self) -> None:
        """Stop Channel and close WebSocket connection."""
        if not self.running:
            return

        logger.info("Stopping WeCom Channel")
        self.running = False

        if self.active_tasks:
            await asyncio.gather(*self.active_tasks, return_exceptions=True)
            self.active_tasks.clear()

        if self.client:
            await self.client.disconnect()
            self.client = None

        logger.info("WeCom Channel stopped")

    # -- SDK Event Registration ------------------------------------------

    def _register_handlers(self) -> None:
        """Register all SDK event handlers via client.on()."""
        if not self.client:
            return

        # Connection status events
        self.client.on(
            "connected",
            lambda: logger.info("[WeCom] WebSocket connected"),
        )
        self.client.on(
            "authenticated",
            lambda: logger.info("[WeCom] Authenticated"),
        )
        self.client.on(
            "disconnected",
            lambda reason: logger.warning(
                "[WeCom] Disconnected: %s", reason,
            ),
        )
        self.client.on(
            "reconnecting",
            lambda attempt: logger.info(
                "[WeCom] Reconnecting, attempt %d", attempt,
            ),
        )
        self.client.on(
            "error",
            lambda err: logger.error("[WeCom] Error: %s", err),
        )

        # Message events
        self.client.on("message.text", self._on_text)
        self.client.on("message.image", self._on_image)
        self.client.on("message.mixed", self._on_mixed)
        self.client.on("message.voice", self._on_voice)
        self.client.on("message.file", self._on_file)

        # Event callbacks
        self.client.on("event.enter_chat", self._on_enter_chat)
        self.client.on(
            "event.template_card_event",
            self._on_template_card_event,
        )
        self.client.on("event.feedback_event", self._on_feedback_event)

    # -- Message Event Callbacks (sync, delegate to async handlers) ------

    def _on_text(self, frame: WsFrame) -> None:
        """Text message callback."""
        self._spawn(handlers.handle_text(self, frame))

    def _on_image(self, frame: WsFrame) -> None:
        """Image message callback."""
        self._spawn(handlers.handle_image(self, frame))

    def _on_mixed(self, frame: WsFrame) -> None:
        """Mixed message callback."""
        self._spawn(handlers.handle_mixed(self, frame))

    def _on_voice(self, frame: WsFrame) -> None:
        """Voice message callback."""
        self._spawn(handlers.handle_voice(self, frame))

    def _on_file(self, frame: WsFrame) -> None:
        """File message callback."""
        self._spawn(handlers.handle_file(self, frame))

    def _on_enter_chat(self, frame: WsFrame) -> None:
        """Enter chat event, send welcome message."""
        self._spawn(handlers.send_welcome(self, frame))

    def _on_template_card_event(self, frame: WsFrame) -> None:
        """Template card interaction event."""
        body = frame.get("body", {})
        event = body.get("event", {})
        logger.info(
            "[WeCom] Template card event: %s",
            event.get("eventtype"),
        )

    def _on_feedback_event(self, frame: WsFrame) -> None:
        """User feedback event."""
        body = frame.get("body", {})
        event = body.get("event", {})
        logger.info(
            "[WeCom] User feedback event: %s",
            event.get("eventtype"),
        )

    # -- Async Task Management -------------------------------------------

    def _spawn(self, coro: Any) -> None:
        """Create async task and track it (non-blocking)."""
        task = asyncio.create_task(coro)
        self.active_tasks.add(task)
        task.add_done_callback(self.active_tasks.discard)

    # -- Message Dispatch ------------------------------------------------

    async def dispatch_message(
        self,
        frame: WsFrame,
        content_parts: list,
    ) -> None:
        """Build AgentRequest and initiate streaming reply.

        Args:
            frame: Raw WsFrame from SDK.
            content_parts: List of content parts (text/image).
        """
        headers = frame.get("headers", {})
        req_id = headers.get("req_id", "")
        body = frame.get("body", {})

        from_user = body.get("from", {})
        user_id = from_user.get("userid", "")
        chatid = body.get("chatid") or user_id
        session_id = f"{self.channel}:{chatid}"

        request = self.build_agent_request_from_user_content(
            channel_id=self.channel,
            sender_id=user_id,
            session_id=session_id,
            content_parts=content_parts,
        )

        await stream.dispatch_with_timeout(self, request, frame, req_id)

    # -- Image Download --------------------------------------------------

    async def download_image(
        self,
        url: str,
        aes_key: str,
    ) -> Optional[ImageContent]:
        """Download and decrypt image using SDK, save locally.

        Args:
            url: Image download URL.
            aes_key: AES key for decryption.

        Returns:
            ImageContent with local file path, or None on failure.
        """
        if not self.client:
            logger.error(
                "[WeCom] Client not initialized, cannot download image",
            )
            return None

        try:
            # SDK handles download + AES-256-CBC decryption
            result = await self.client.download_file(url, aes_key)
            data: bytes = result["buffer"]
            return save_image_to_dir(data, self.media_dir)
        except Exception as exc:
            logger.error(
                "[WeCom] Image download/decrypt failed: %s",
                exc,
                exc_info=True,
            )
            return None

    # -- Proactive Message Sending ---------------------------------------

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[Dict[str, Any]] = None,  # noqa: ARG002
    ) -> None:
        """Proactively send Markdown message to specified session.

        Args:
            to_handle: Session identifier (userid or chatid).
            text: Message text (supports Markdown).
            meta: Metadata (not yet used).
        """
        if not self.client:
            logger.warning(
                "[WeCom] Client not initialized, cannot send message",
            )
            return

        try:
            await self.client.send_message(
                to_handle,
                {"msgtype": "markdown", "markdown": {"content": text}},
            )
            logger.info("[WeCom] Proactive message sent to %s", to_handle)
        except Exception as exc:
            logger.error(
                "[WeCom] Failed to send proactive message: %s",
                exc,
                exc_info=True,
            )

    # -- BaseChannel Abstract Method -------------------------------------

    async def consume_one(self, payload: Any) -> None:  # noqa: ARG002
        """Not used in WebSocket mode (BaseChannel abstract method)."""
