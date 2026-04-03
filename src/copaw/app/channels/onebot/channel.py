# -*- coding: utf-8 -*-
# pylint: disable=too-many-branches,too-many-statements
"""OneBot v11 Channel.

Reverse WebSocket server for NapCat, go-cqhttp, Lagrange, or any
OneBot v11 implementation.  CoPaw listens on a configurable port;
the OneBot client connects as a WebSocket client.

Message flow:
  NapCat → reverse WS → parse OneBot segments → content_parts → process
  process → content_parts → OneBot segments → reverse WS → NapCat
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from typing import Any, Dict, List, Optional, Set

import aiohttp
from aiohttp import web

from agentscope_runtime.engine.schemas.agent_schemas import (
    AudioContent,
    ContentType,
    FileContent,
    ImageContent,
    TextContent,
    VideoContent,
)

from ....config.config import OneBotConfig as OneBotChannelConfig
from ..base import (
    BaseChannel,
    OnReplySent,
    OutgoingContentPart,
    ProcessHandler,
)
from ..utils import split_text

logger = logging.getLogger(__name__)


class OneBotChannel(BaseChannel):
    """OneBot v11 channel via reverse WebSocket.

    CoPaw acts as a WebSocket server; NapCat (or compatible) connects
    as a client to ``ws://<host>:<port>/ws``.
    """

    channel = "onebot"
    uses_manager_queue = True

    def __init__(
        self,
        process: ProcessHandler,
        enabled: bool,
        ws_host: str = "0.0.0.0",
        ws_port: int = 6199,
        access_token: str = "",
        bot_prefix: str = "",
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
        dm_policy: str = "open",
        group_policy: str = "open",
        allow_from: Optional[list] = None,
        deny_message: str = "",
        require_mention: bool = False,
        share_session_in_group: bool = False,
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
            require_mention=require_mention,
        )
        self.enabled = enabled
        self.bot_prefix = bot_prefix
        self._ws_host = ws_host
        self._ws_port = ws_port
        self._access_token = access_token
        self._share_session_in_group = share_session_in_group

        # WebSocket server state
        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self._connections: Set[web.WebSocketResponse] = set()

        # Echo-based API call tracking
        self._pending_calls: Dict[str, asyncio.Future] = {}

        # Bot self ID (populated on first meta_event/lifecycle)
        self._self_id: Optional[int] = None

    # ------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------

    @classmethod
    def from_env(
        cls,
        process: ProcessHandler,
        on_reply_sent: OnReplySent = None,
    ) -> "OneBotChannel":
        return cls(
            process=process,
            enabled=os.getenv("ONEBOT_CHANNEL_ENABLED", "0") == "1",
            ws_host=os.getenv("ONEBOT_WS_HOST", "0.0.0.0"),
            ws_port=int(os.getenv("ONEBOT_WS_PORT", "6199")),
            access_token=os.getenv("ONEBOT_ACCESS_TOKEN", ""),
            bot_prefix=os.getenv("ONEBOT_BOT_PREFIX", ""),
            on_reply_sent=on_reply_sent,
            dm_policy=os.getenv("ONEBOT_DM_POLICY", "open"),
            group_policy=os.getenv("ONEBOT_GROUP_POLICY", "open"),
            allow_from=(
                os.getenv("ONEBOT_ALLOW_FROM", "").split(",")
                if os.getenv("ONEBOT_ALLOW_FROM")
                else []
            ),
            deny_message=os.getenv("ONEBOT_DENY_MESSAGE", ""),
            require_mention=(os.getenv("ONEBOT_REQUIRE_MENTION", "0") == "1"),
            share_session_in_group=(
                os.getenv("ONEBOT_SHARE_SESSION_IN_GROUP", "0") == "1"
            ),
        )

    @classmethod
    def from_config(
        cls,
        process: ProcessHandler,
        config: OneBotChannelConfig,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
    ) -> "OneBotChannel":
        return cls(
            process=process,
            enabled=config.enabled,
            ws_host=config.ws_host or "0.0.0.0",
            ws_port=config.ws_port or 6199,
            access_token=config.access_token or "",
            bot_prefix=config.bot_prefix or "",
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            filter_thinking=filter_thinking,
            dm_policy=config.dm_policy,
            group_policy=config.group_policy,
            allow_from=config.allow_from,
            deny_message=config.deny_message,
            require_mention=config.require_mention,
            share_session_in_group=getattr(
                config,
                "share_session_in_group",
                False,
            ),
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if not self.enabled:
            logger.debug("onebot channel disabled")
            return
        self._app = web.Application()
        self._app.router.add_get("/ws", self._handle_ws_connection)
        self._app.router.add_get("/ws/", self._handle_ws_connection)
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(
            self._runner,
            self._ws_host,
            self._ws_port,
        )
        await self._site.start()
        logger.info(
            "onebot: reverse WS server listening on %s:%s",
            self._ws_host,
            self._ws_port,
        )

    async def stop(self) -> None:
        if not self.enabled:
            return
        for ws in list(self._connections):
            await ws.close()
        self._connections.clear()
        if self._site:
            await self._site.stop()
            self._site = None
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
        self._app = None
        # Cancel pending API futures
        for fut in self._pending_calls.values():
            if not fut.done():
                fut.cancel()
        self._pending_calls.clear()

    # ------------------------------------------------------------------
    # WebSocket connection handling
    # ------------------------------------------------------------------

    async def _handle_ws_connection(
        self,
        request: web.Request,
    ) -> web.WebSocketResponse:
        """Handle incoming WebSocket connection from NapCat."""
        # Token authentication
        if self._access_token:
            auth_header = request.headers.get("Authorization", "")
            query_token = request.query.get("access_token", "")
            valid = (
                auth_header == f"Bearer {self._access_token}"
                or auth_header == f"Token {self._access_token}"
                or query_token == self._access_token
            )
            if not valid:
                logger.warning(
                    "onebot: rejected connection from %s (bad token)",
                    request.remote,
                )
                return web.Response(status=401, text="Unauthorized")

        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self._connections.add(ws)
        logger.info("onebot: client connected from %s", request.remote)

        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                    except json.JSONDecodeError:
                        logger.warning(
                            "onebot: invalid JSON: %s",
                            msg.data[:200],
                        )
                        continue
                    if "echo" in data:
                        self._handle_api_response(data)
                    else:
                        await self._handle_event(data)
                elif msg.type in (
                    aiohttp.WSMsgType.ERROR,
                    aiohttp.WSMsgType.CLOSE,
                ):
                    break
        except Exception:
            logger.exception("onebot: WS connection error")
        finally:
            self._connections.discard(ws)
            logger.info("onebot: client disconnected from %s", request.remote)

        return ws

    # ------------------------------------------------------------------
    # Event dispatch
    # ------------------------------------------------------------------

    async def _handle_event(self, data: Dict[str, Any]) -> None:
        """Dispatch an OneBot v11 event."""
        post_type = data.get("post_type")
        if post_type == "meta_event":
            self._handle_meta_event(data)
        elif post_type == "message":
            await self._handle_message_event(data)
        # notice / request events: ignored for now

    def _handle_meta_event(self, data: Dict[str, Any]) -> None:
        """Handle lifecycle and heartbeat meta events."""
        meta_type = data.get("meta_event_type")
        if meta_type == "lifecycle":
            self._self_id = data.get("self_id")
            sub = data.get("sub_type", "")
            logger.info(
                "onebot: lifecycle %s, self_id=%s",
                sub,
                self._self_id,
            )
        elif meta_type == "heartbeat":
            logger.debug("onebot: heartbeat from self_id=%s", self._self_id)

    async def _handle_message_event(self, data: Dict[str, Any]) -> None:
        """Handle a message event from OneBot v11."""
        message_type = data.get("message_type")  # "private" or "group"
        user_id = str(data.get("user_id", ""))
        group_id = str(data.get("group_id", ""))
        message_id = str(data.get("message_id", ""))
        segments = data.get("message", [])

        # If message is a list of dicts, parse segments; if string, wrap
        if isinstance(segments, str):
            segments = [{"type": "text", "data": {"text": segments}}]

        # Track bot mention for require_mention
        bot_mentioned = False
        content_parts, bot_mentioned = self._parse_message_segments(segments)
        if not content_parts:
            return

        sender = data.get("sender", {})
        sender_name = sender.get("card") or sender.get("nickname") or user_id

        is_group = message_type == "group"
        meta: Dict[str, Any] = {
            "message_type": message_type,
            "message_id": message_id,
            "sender_id": user_id,
            "sender_name": sender_name,
            "group_id": group_id if is_group else "",
            "is_group": is_group,
            "bot_mentioned": bot_mentioned,
        }

        # Allowlist check
        allowed, deny_msg = self._check_allowlist(user_id, is_group)
        if not allowed:
            if deny_msg:
                to = f"group:{group_id}" if is_group else user_id
                # Fire-and-forget to avoid deadlock: the WS read loop
                # is blocked on this handler, so awaiting send() (which
                # calls _call_api and waits for a WS response) would
                # never complete.
                asyncio.create_task(self.send(to, deny_msg, meta))
            return

        # Mention check (group messages may require @bot)
        if not self._check_group_mention(is_group, meta):
            return

        native = {
            "channel_id": self.channel,
            "sender_id": user_id,
            "content_parts": content_parts,
            "meta": meta,
        }

        request = self.build_agent_request_from_native(native)
        request.channel_meta = meta

        logger.info(
            "onebot recv %s from=%s%s text=%r",
            message_type,
            sender_name,
            f" group={group_id}" if is_group else "",
            self._preview_text(content_parts),
        )

        if self._enqueue is not None:
            self._enqueue(request)

    # ------------------------------------------------------------------
    # Message segment parsing
    # ------------------------------------------------------------------

    def _parse_message_segments(
        self,
        segments: List[Dict[str, Any]],
    ) -> tuple[list, bool]:
        """Parse OneBot v11 message segments to CoPaw content_parts.

        Returns:
            (content_parts, bot_mentioned)
        """
        parts: list = []
        bot_mentioned = False

        for seg in segments:
            seg_type = seg.get("type", "")
            seg_data = seg.get("data", {})

            if seg_type == "text":
                text = (seg_data.get("text") or "").strip()
                if text:
                    parts.append(
                        TextContent(type=ContentType.TEXT, text=text),
                    )

            elif seg_type == "image":
                url = seg_data.get("url") or seg_data.get("file", "")
                if url:
                    parts.append(
                        ImageContent(
                            type=ContentType.IMAGE,
                            image_url=url,
                        ),
                    )

            elif seg_type == "record":
                url = seg_data.get("url") or seg_data.get("file", "")
                if url:
                    parts.append(
                        AudioContent(type=ContentType.AUDIO, data=url),
                    )

            elif seg_type == "video":
                url = seg_data.get("url") or seg_data.get("file", "")
                if url:
                    parts.append(
                        VideoContent(
                            type=ContentType.VIDEO,
                            video_url=url,
                        ),
                    )

            elif seg_type == "file":
                url = seg_data.get("url") or seg_data.get("file", "")
                name = seg_data.get("name", "file")
                if url:
                    parts.append(
                        FileContent(
                            type=ContentType.FILE,
                            file_url=url,
                            filename=name,
                        ),
                    )

            elif seg_type == "at":
                qq = str(seg_data.get("qq", ""))
                if self._self_id and qq == str(self._self_id):
                    bot_mentioned = True

            # reply, face, forward, etc. — ignored for now

        return parts, bot_mentioned

    # ------------------------------------------------------------------
    # Build AgentRequest
    # ------------------------------------------------------------------

    def build_agent_request_from_native(self, native_payload: Any) -> Any:
        payload = native_payload if isinstance(native_payload, dict) else {}
        channel_id = payload.get("channel_id") or self.channel
        sender_id = payload.get("sender_id") or ""
        content_parts = payload.get("content_parts") or []
        meta = payload.get("meta") or {}
        session_id = self.resolve_session_id(sender_id, meta)
        return self.build_agent_request_from_user_content(
            channel_id=channel_id,
            sender_id=sender_id,
            session_id=session_id,
            content_parts=content_parts,
            channel_meta=meta,
        )

    # ------------------------------------------------------------------
    # Session / routing
    # ------------------------------------------------------------------

    def resolve_session_id(
        self,
        sender_id: str,
        channel_meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        meta = channel_meta or {}
        is_group = meta.get("is_group", False)
        group_id = meta.get("group_id", "")
        if is_group:
            if self._share_session_in_group:
                return f"onebot:g:{group_id}"
            return f"onebot:{group_id}:{sender_id}"
        return f"onebot:{sender_id}"

    def get_to_handle_from_request(self, request: Any) -> str:
        meta = getattr(request, "channel_meta", {}) or {}
        if meta.get("is_group"):
            return f"group:{meta.get('group_id', '')}"
        return str(
            meta.get("sender_id") or getattr(request, "user_id", "") or "",
        )

    # ------------------------------------------------------------------
    # Sending messages (CoPaw → NapCat)
    # ------------------------------------------------------------------

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self.enabled or not text.strip():
            return
        meta = meta or {}
        is_group = meta.get("is_group", False) or to_handle.startswith(
            "group:",
        )

        for chunk in split_text(text):
            segments = [{"type": "text", "data": {"text": chunk}}]
            if is_group:
                gid = meta.get("group_id") or to_handle.removeprefix("group:")
                await self._call_api(
                    "send_group_msg",
                    {"group_id": int(gid), "message": segments},
                )
            else:
                uid = meta.get("sender_id") or to_handle
                await self._call_api(
                    "send_private_msg",
                    {"user_id": int(uid), "message": segments},
                )

    async def send_media(
        self,
        to_handle: str,
        part: OutgoingContentPart,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send a media part via OneBot API.

        Supports image, audio (record), and video segments.
        """
        meta = meta or {}
        t = getattr(part, "type", None)

        if t == ContentType.IMAGE:
            url = getattr(part, "image_url", "")
            if not url:
                return
            segments = [{"type": "image", "data": {"file": url}}]
        elif t == ContentType.AUDIO:
            url = getattr(part, "data", "")
            if not url:
                return
            segments = [{"type": "record", "data": {"file": url}}]
        elif t == ContentType.VIDEO:
            url = getattr(part, "video_url", "")
            if not url:
                return
            segments = [{"type": "video", "data": {"file": url}}]
        else:
            return

        is_group = meta.get("is_group", False) or to_handle.startswith(
            "group:",
        )
        if is_group:
            gid = meta.get("group_id") or to_handle.removeprefix("group:")
            await self._call_api(
                "send_group_msg",
                {"group_id": int(gid), "message": segments},
            )
        else:
            uid = meta.get("sender_id") or to_handle
            await self._call_api(
                "send_private_msg",
                {"user_id": int(uid), "message": segments},
            )

    # ------------------------------------------------------------------
    # OneBot v11 API calls (echo-based RPC)
    # ------------------------------------------------------------------

    async def _call_api(
        self,
        action: str,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Call an OneBot v11 API action via WebSocket echo pattern."""
        if not self._connections:
            logger.warning(
                "onebot: no active connection for API call %s",
                action,
            )
            return {}

        echo = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending_calls[echo] = future

        payload = json.dumps(
            {"action": action, "params": params, "echo": echo},
            ensure_ascii=False,
        )

        # Try each connection until one succeeds (handles stale connections
        # during reconnection windows).
        sent = False
        for ws in list(self._connections):
            try:
                await ws.send_str(payload)
                sent = True
                break
            except Exception:
                logger.debug(
                    "onebot: send failed on one connection, trying next",
                )
                continue
        if not sent:
            self._pending_calls.pop(echo, None)
            logger.warning("onebot: all connections failed for %s", action)
            return {}

        try:
            result = await asyncio.wait_for(future, timeout=15.0)
            retcode = result.get("retcode", -1)
            if retcode != 0:
                logger.warning(
                    "onebot API %s retcode=%s: %s",
                    action,
                    retcode,
                    result.get("msg", ""),
                )
            return result
        except asyncio.TimeoutError:
            logger.warning("onebot: API %s timeout (15s)", action)
            return {}
        finally:
            self._pending_calls.pop(echo, None)

    def _handle_api_response(self, data: Dict[str, Any]) -> None:
        """Route an API response to its pending future."""
        echo = data.get("echo")
        if echo and echo in self._pending_calls:
            fut = self._pending_calls[echo]
            if not fut.done():
                fut.set_result(data)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _preview_text(content_parts: list) -> str:
        """Return a short text preview for logging."""
        for p in content_parts:
            if getattr(p, "type", None) == ContentType.TEXT:
                text = getattr(p, "text", "")
                return text[:100] if text else ""
        return "<non-text>"
