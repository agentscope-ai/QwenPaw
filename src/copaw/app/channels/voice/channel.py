# -*- coding: utf-8 -*-
"""Voice Channel: Twilio ConversationRelay + Cloudflare Tunnel."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ..base import BaseChannel, OnReplySent, ProcessHandler
from ..renderer import RenderStyle
from .session import CallSessionManager
from .twilio_manager import TwilioManager

logger = logging.getLogger(__name__)


class VoiceChannel(BaseChannel):
    """CoPaw Voice channel backed by Twilio ConversationRelay.

    ``uses_manager_queue = False`` because voice calls are long-lived
    WebSocket sessions -- the ConversationRelay handler runs its own
    async loop per call.
    """

    channel = "voice"
    uses_manager_queue = False

    def __init__(
        self,
        process: ProcessHandler,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
    ) -> None:
        super().__init__(process, on_reply_sent, show_tool_details)
        # Voice output should be clean speech -- no markdown, no emoji
        self._render_style = RenderStyle(
            show_tool_details=False,
            supports_markdown=False,
            supports_code_fence=False,
            use_emoji=False,
        )
        self.session_mgr = CallSessionManager()
        self.twilio_mgr: Optional[TwilioManager] = None
        self.tunnel_mgr = None  # CloudflareTunnelDriver, set by from_config
        self._config: Any = None
        self._enabled = False

    @classmethod
    def from_config(
        cls,
        process: ProcessHandler,
        config: Any,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
    ) -> "VoiceChannel":
        instance = cls(process, on_reply_sent, show_tool_details)
        instance._config = config
        instance._enabled = getattr(config, "enabled", False)

        sid = getattr(config, "twilio_account_sid", "")
        token = getattr(config, "twilio_auth_token", "")
        if sid and token:
            instance.twilio_mgr = TwilioManager(sid, token)

        # Tunnel driver is created lazily on start()
        return instance

    async def start(self) -> None:
        """Start the voice channel: tunnel + Twilio webhook."""
        if not self._enabled:
            logger.info("Voice channel disabled, skipping start")
            return

        if not self.twilio_mgr:
            logger.warning(
                "Voice channel enabled but Twilio credentials missing",
            )
            return

        phone_number_sid = getattr(self._config, "phone_number_sid", "")
        if not phone_number_sid:
            logger.warning(
                "Voice channel enabled but phone_number_sid not configured",
            )
            return

        # Start Cloudflare tunnel
        from copaw.tunnel import CloudflareTunnelDriver

        self.tunnel_mgr = CloudflareTunnelDriver()
        local_port = getattr(self._config, "local_port", 8088)

        try:
            tunnel_info = await self.tunnel_mgr.start(local_port)
        except Exception:
            logger.exception("Failed to start Cloudflare tunnel")
            return

        # Configure Twilio webhook + status callback
        base_url = tunnel_info.public_url
        webhook_url = f"{base_url}/voice/incoming"
        status_cb_url = f"{base_url}/voice/status-callback"
        try:
            await self.twilio_mgr.configure_voice_webhook(
                phone_number_sid,
                webhook_url,
                status_callback_url=status_cb_url,
            )
        except Exception:
            logger.exception("Failed to configure Twilio webhook")

        logger.info(
            "Voice channel started: tunnel=%s phone=%s",
            tunnel_info.public_url,
            getattr(self._config, "phone_number", ""),
        )

    async def stop(self) -> None:
        """Stop the voice channel: close sessions + tunnel."""
        for session in self.session_mgr.active_sessions():
            try:
                await session.handler.close()
            except Exception:
                pass

        if self.tunnel_mgr:
            try:
                await self.tunnel_mgr.stop()
            except Exception:
                logger.exception("Error stopping tunnel")

        logger.info("Voice channel stopped")

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send text to an active call session (by call_sid)."""
        # to_handle is the call_sid for voice
        session = self.session_mgr.get_session(to_handle)
        if session and session.status == "active":
            await session.handler.send_text(text)

    def build_agent_request_from_native(
        self,
        native_payload: Any,
    ) -> Any:
        """Convert a voice payload dict to AgentRequest."""
        from agentscope_runtime.engine.schemas.agent_schemas import (
            AgentRequest,
            Message,
            MessageType,
            Role,
            TextContent,
            ContentType,
        )

        text = native_payload.get("transcript", "")
        session_id = native_payload.get("session_id", "")
        user_id = native_payload.get("from_number", "")

        msg = Message(
            type=MessageType.MESSAGE,
            role=Role.USER,
            content=[TextContent(type=ContentType.TEXT, text=text)],
        )
        return AgentRequest(
            session_id=session_id,
            user_id=user_id,
            input=[msg],
            channel=self.channel,
        )

    @property
    def config(self) -> Any:
        """Public accessor for the channel configuration."""
        return self._config

    @property
    def process(self) -> ProcessHandler:
        """Public accessor for the process handler."""
        return self._process

    def get_tunnel_url(self) -> str | None:
        """Return the current tunnel public URL."""
        if self.tunnel_mgr:
            return self.tunnel_mgr.get_public_url()
        return None

    def get_tunnel_wss_url(self) -> str | None:
        """Return the current tunnel WSS URL."""
        if self.tunnel_mgr:
            info = self.tunnel_mgr.get_info()
            if info:
                return info.public_wss_url
        return None
