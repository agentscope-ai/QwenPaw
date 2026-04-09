# -*- coding: utf-8 -*-
"""NapCat Channel for CoPaw.

NapCat 基于 OneBot 11 协议，使用 WebSocket 接收消息，HTTP API 发送消息。
"""

from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp

from agentscope_runtime.engine.schemas.agent_schemas import (
    TextContent,
    ContentType,
)

from ..base import (
    BaseChannel,
    OnReplySent,
    ProcessHandler,
)
from .constants import DEFAULT_MEDIA_DIR
from .api import (
    send_group_message,
    send_private_message,
    get_login_info,
    get_group_list,
)
from .message import (
    parse_message,
    build_message_segment,
)
from .websocket import WebSocketClient

logger = logging.getLogger(__name__)


class NapCatChannel(BaseChannel):
    """NapCat Channel:
    WebSocket events -> Incoming -> process -> HTTP API reply.

    Based on OneBot 11 protocol.
    """

    channel = "napcat"

    def __init__(
        self,
        process: ProcessHandler,
        enabled: bool,
        host: str = "127.0.0.1",
        port: int = 3000,
        ws_port: int = 3001,
        access_token: str = "",
        bot_prefix: str = "",
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
        dm_policy: str = "open",
        group_policy: str = "open",
        allow_from: List[str] = None,
        deny_message: str = "",
        media_dir: str = "",
    ):
        super().__init__(
            process,
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            filter_thinking=filter_thinking,
            dm_policy=dm_policy,
            group_policy=group_policy,
            allow_from=allow_from,
            deny_message=deny_message,
        )
        self.enabled = enabled
        self.host = host
        self.port = port
        self.ws_port = ws_port
        self.access_token = access_token
        self.bot_prefix = bot_prefix
        self._media_dir = (
            Path(media_dir).expanduser() if media_dir else DEFAULT_MEDIA_DIR
        )

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ws_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._account_id = "default"

        self._http: Optional[aiohttp.ClientSession] = None
        self._login_info: Optional[Dict[str, Any]] = None
        self._group_list: List[Dict[str, Any]] = []

    @classmethod
    def from_config(
        cls,
        process: ProcessHandler,
        config: Any,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
    ) -> "NapCatChannel":
        """Create channel from config dict or NapCatConfig model."""

        def get_config_attr(config_obj: Any, attr: str, default: Any) -> Any:
            """Get attribute from dict or Pydantic model."""
            if hasattr(config_obj, "get"):
                return config_obj.get(attr, default)
            return getattr(config_obj, attr, default)

        # Read config values using helper
        enabled = get_config_attr(config, "enabled", False)
        host = get_config_attr(config, "host", "127.0.0.1")
        port = get_config_attr(config, "port", 3000)
        ws_port = get_config_attr(config, "ws_port", 3001)
        access_token = get_config_attr(config, "access_token", "")
        bot_prefix = get_config_attr(config, "bot_prefix", "")
        dm_policy = get_config_attr(config, "dm_policy", "open")
        group_policy = get_config_attr(config, "group_policy", "open")
        allow_from = get_config_attr(config, "allow_from", [])
        deny_message = get_config_attr(config, "deny_message", "")
        media_dir = get_config_attr(config, "media_dir", "")

        return cls(
            process=process,
            enabled=enabled,
            host=host,
            port=port,
            ws_port=ws_port,
            access_token=access_token,
            bot_prefix=bot_prefix,
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            filter_thinking=filter_thinking,
            dm_policy=dm_policy,
            group_policy=group_policy,
            allow_from=allow_from,
            deny_message=deny_message,
            media_dir=media_dir,
        )

    def _is_bot_mentioned(
        self,
        raw_message: Any,
    ) -> bool:
        """Check if the bot was mentioned in the message.

        Checks for CQ code: [CQ:at,qq={bot_qq}]
        Also supports the 'all' mention: [CQ:at,qq=all]

        Args:
            raw_message: The raw message from OneBot 11 event

        Returns:
            True if bot is mentioned
        """
        if not raw_message:
            return False

        # Get bot QQ from login info
        bot_qq = (
            str(self._login_info.get("user_id", ""))
            if self._login_info
            else ""
        )
        if not bot_qq:
            return False

        # Handle both string and list message formats
        if isinstance(raw_message, str):
            # Check for CQ at code with bot QQ
            if f"[CQ:at,qq={bot_qq}]" in raw_message:
                return True
            # Also check for @all (everyone)
            if "[CQ:at,qq=all]" in raw_message:
                return True
        elif isinstance(raw_message, list):
            # Check message segments for at type
            for segment in raw_message:
                if isinstance(segment, dict):
                    seg_type = segment.get("type", "")
                    if seg_type == "at":
                        seg_data = segment.get("data", {})
                        qq = seg_data.get("qq", "")
                        # Check if it's mentioning the bot or everyone
                        if str(qq) == bot_qq or qq == "all":
                            return True

        return False

    def _clean_at_mention(
        self,
        raw_message: Any,
    ) -> Any:
        """Remove the @ bot mention from the message.

        This is used to clean the message before processing,
        so the bot doesn't see the @ mention in its input.

        Args:
            raw_message: The raw message from OneBot 11 event

        Returns:
            Cleaned message without the @ mention
        """
        if not raw_message:
            return raw_message

        # Get bot QQ from login info
        bot_qq = (
            str(self._login_info.get("user_id", ""))
            if self._login_info
            else ""
        )

        # Handle string message format
        if isinstance(raw_message, str):
            cleaned = raw_message
            # Remove CQ at code with bot QQ
            if bot_qq:
                cleaned = cleaned.replace(f"[CQ:at,qq={bot_qq}]", "")
            # Remove @all CQ code
            cleaned = cleaned.replace("[CQ:at,qq=all]", "")
            # Also try without comma format
            if bot_qq:
                cleaned = cleaned.replace(f"[CQ:at qq={bot_qq}]", "")
            cleaned = cleaned.replace("[CQ:at qq=all]", "")
            return cleaned.strip()

        # Handle list message format
        if isinstance(raw_message, list):
            cleaned_segments = []
            for segment in raw_message:
                if isinstance(segment, dict):
                    seg_type = segment.get("type", "")
                    if seg_type == "at":
                        # Skip at segments
                        seg_data = segment.get("data", {})
                        qq = seg_data.get("qq", "")
                        # Skip if it's mentioning bot or everyone
                        if str(qq) == bot_qq or qq == "all":
                            continue
                    # Keep other segments
                    cleaned_segments.append(segment)
                else:
                    cleaned_segments.append(segment)
            return cleaned_segments

        return raw_message

    def _should_process(
        self,
        user_id: str,
        group_id: Optional[str] = None,
        raw_message: Any = None,
    ) -> bool:
        """Check if the message should be processed based on policy.

        For group messages, also checks if the bot was mentioned (unless
        bot_prefix is set, in which case message must start with prefix).

        Args:
            user_id: The user ID who sent the message
            group_id: The group ID if this is a group message
            raw_message: The raw message content for at-mention checking
        """
        # Check allow_from list
        if self.allow_from and user_id not in self.allow_from:
            return False

        # Check group policy
        if group_id:
            if self.group_policy == "deny":
                return False

            # For group messages, check if bot is mentioned
            # (only if no bot_prefix is set, since prefix takes precedence)
            if not self.bot_prefix:
                if not self._is_bot_mentioned(raw_message):
                    # Bot not mentioned in group message, skip processing
                    logger.debug(
                        f"napcat: group message without bot mention, "
                        f"group={group_id}, user={user_id}",
                    )
                    return False
        else:
            # Private message
            if self.dm_policy == "deny":
                return False

        return True

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send text message via NapCat HTTP API.

        Args:
            to_handle: Target ID (group_id or user_id)
            text: Message text
            meta: Optional metadata including message_type
        """
        if not self.enabled or not text.strip():
            return

        text = text.strip()
        meta = meta or {}

        # Build message segment (simple text)
        message = build_message_segment(text, auto_escape=True)

        # Determine if this is group or private message
        # Check multiple sources for group_id
        group_id = meta.get("group_id")
        session_id = meta.get("session_id", "")

        # If no group_id in meta, try to extract from session_id
        if not group_id and session_id.startswith("napcat:group:"):
            group_id = session_id.split(":")[-1]

        message_type = meta.get("message_type", "")
        is_group = (
            bool(group_id)
            or message_type == "group"
            or to_handle.startswith("group:")
        )

        if is_group:
            # group_id already extracted above from session_id if needed
            # Don't overwrite with meta.get("group_id")
            if not group_id:
                # Fallback: extract from session_id in session_id field
                session_id = meta.get("session_id", "")
                if session_id.startswith("napcat:group:"):
                    group_id = session_id.split(":")[-1]
            if not group_id:
                logger.warning(
                    "NapCat send: group_id is None, "
                    f"message_type={message_type}, session_id={session_id}",
                )
            try:
                await send_group_message(
                    self._http,
                    self.host,
                    self.port,
                    self.access_token,
                    group_id,
                    message,
                )
            except Exception:
                logger.exception(f"NapCat send to group {group_id} failed")
        else:
            # Private message
            user_id = meta.get("user_id") or to_handle
            try:
                await send_private_message(
                    self._http,
                    self.host,
                    self.port,
                    self.access_token,
                    user_id,
                    message,
                )
            except Exception:
                logger.exception("NapCat send to user %s failed", user_id)

    def build_agent_request_from_native(self, native_payload: Any) -> Any:
        """Build AgentRequest from NapCat/OneBot 11 event dict."""
        payload = native_payload if isinstance(native_payload, dict) else {}

        # Extract common fields
        post_type = payload.get("post_type", "")
        message_type = payload.get("message_type", "")
        user_id = str(payload.get("user_id", ""))
        group_id = (
            str(payload.get("group_id", ""))
            if payload.get("group_id")
            else None
        )
        raw_message = payload.get("message", "")
        message_id = payload.get("message_id", 0)

        # Skip if not a message
        if post_type != "message":
            return None

        # Skip if has bot_prefix and message doesn't start with it
        if self.bot_prefix and isinstance(raw_message, str):
            if not raw_message.startswith(self.bot_prefix):
                # Check if it's an @ mention (CQ code)
                bot_qq = (
                    str(self._login_info.get("user_id", ""))
                    if self._login_info
                    else ""
                )
                if bot_qq and f"[CQ:at,qq={bot_qq}]" not in raw_message:
                    return None

        # Check policy (pass raw_message for at-mention detection)
        if not self._should_process(user_id, group_id, raw_message):
            return None

        # Clean the message by removing @bot mention (for processing)
        cleaned_message = self._clean_at_mention(raw_message)

        # Parse message to content parts
        content_parts = parse_message(cleaned_message)

        # Build metadata
        meta = {
            "message_type": message_type,
            "message_id": message_id,
            "sender_id": user_id,
            "group_id": group_id,
            "incoming_raw": payload,
        }

        # Build request
        return self.build_agent_request_from_user_content(
            channel_id=self.channel,
            sender_id=user_id,
            session_id=self.resolve_session_id(user_id, meta),
            content_parts=content_parts,
            channel_meta=meta,
        )

    def get_to_handle_from_request(self, request: Any) -> str:
        """Resolve send target (to_handle) from AgentRequest.

        For group messages, use group_id; otherwise use user_id.
        """
        send_meta = getattr(request, "channel_meta", None) or {}
        group_id = send_meta.get("group_id")
        message_type = send_meta.get("message_type")

        # Try to get group_id from session_id if not present
        if not group_id and message_type == "group":
            session_id = getattr(request, "session_id", "") or ""
            if session_id.startswith("napcat:group:"):
                group_id = session_id.split(":")[-1]

        if group_id:
            return group_id
        return getattr(request, "user_id", "") or ""

    async def _before_consume_process(
        self,
        request: Any,
    ) -> None:
        """Set up send_meta before processing request."""
        # Get or create channel_meta
        send_meta = getattr(request, "channel_meta", None)
        if send_meta is None:
            send_meta = {}
            setattr(request, "channel_meta", send_meta)

        # Add bot_prefix to send_meta
        send_meta.setdefault("bot_prefix", self.bot_prefix)

        # Add session_id to send_meta so send method can access it
        send_meta["session_id"] = getattr(request, "session_id", "")

    async def _on_consume_error(
        self,
        request: Any,
        to_handle: str,
        err_text: str,
    ) -> None:
        """Handle error with bot_prefix prefix."""
        # Add bot_prefix to error message
        prefixed_err_text = self.bot_prefix + err_text

        send_meta = getattr(request, "channel_meta", None) or {}
        await self.send_content_parts(
            to_handle,
            [TextContent(type=ContentType.TEXT, text=prefixed_err_text)],
            send_meta,
        )

    def _handle_event(self, payload: Dict[str, Any]) -> None:
        """Handle incoming NapCat/OneBot 11 event."""
        post_type = payload.get("post_type", "")

        if post_type == "message":
            # Build and enqueue request
            request = self.build_agent_request_from_native(payload)
            if request and self._enqueue is not None:
                self._enqueue(request)
                logger.info(
                    f"napcat recv: type={payload.get('message_type')} "
                    f"user={payload.get('user_id')} "
                    f"group={payload.get('group_id', 'N/A')}",
                )
        elif post_type == "notice":
            # Handle notice events (optional)
            logger.debug(f"napcat notice: {payload.get('notice_type')}")
        elif post_type == "request":
            # Handle request events (optional)
            logger.debug(f"napcat request: {payload.get('request_type')}")
        else:
            logger.debug(f"napcat unknown event: {post_type}")

    async def start(self) -> None:
        """Start the channel."""
        if not self.enabled:
            logger.debug("napcat channel disabled")
            return

        if not self.host:
            raise RuntimeError("NapCat host is required")

        self._loop = asyncio.get_running_loop()
        self._stop_event.clear()

        # Start HTTP session
        self._http = aiohttp.ClientSession()

        # Test connection and get login info
        try:
            self._login_info = await get_login_info(
                self._http,
                self.host,
                self.port,
                self.access_token,
            )
            logger.info(f"napcat logged in as: {self._login_info}")

            self._group_list = await get_group_list(
                self._http,
                self.host,
                self.port,
                self.access_token,
            )
            logger.info(f"napcat joined {len(self._group_list)} groups")
        except Exception as e:
            logger.warning(f"napcat initial fetch failed: {e}")

        # Start WebSocket thread
        ws_client = WebSocketClient(
            host=self.host,
            ws_port=self.ws_port,
            access_token=self.access_token,
            stop_event=self._stop_event,
            message_handler=self._handle_event,
        )
        self._ws_thread = threading.Thread(
            target=ws_client.run_forever,
            daemon=True,
        )
        self._ws_thread.start()
        logger.info("napcat channel started")

    async def stop(self) -> None:
        """Stop the channel."""
        if not self.enabled:
            return

        self._stop_event.set()
        if self._ws_thread:
            self._ws_thread.join(timeout=8)

        if self._http is not None:
            await self._http.close()
            self._http = None

        logger.info("napcat channel stopped")

    def resolve_session_id(
        self,
        sender_id: str,
        channel_meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Resolve session_id based on message type.

        Group messages: use group_id as session key
        Private messages: use user_id as session key
        """
        if channel_meta is None:
            return f"{self.channel}:{sender_id}"

        message_type = channel_meta.get("message_type", "")
        group_id = channel_meta.get("group_id")

        if message_type == "group" and group_id:
            # Group message: session per group
            return f"{self.channel}:group:{group_id}"
        else:
            # Private message: session per user
            return f"{self.channel}:{sender_id}"
