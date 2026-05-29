# -*- coding: utf-8 -*-
# pylint: disable=too-many-instance-attributes
"""Yuanbao Channel: WebSocket-based bot messaging for Tencent Yuanbao.

Uses protobuf binary protocol over WebSocket with sign-token authentication.
Supports C2C (direct) and group chat with streaming output.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp

from agentscope_runtime.engine.schemas.agent_schemas import (
    ContentType,
    FileContent,
    ImageContent,
    TextContent,
)

from ....config.config import YuanbaoConfig as YuanbaoChannelConfig
from ....constant import DEFAULT_MEDIA_DIR
from ..base import (
    BaseChannel,
    OnReplySent,
    OutgoingContentPart,
    ProcessHandler,
)
from .auth import TokenManager
from .codec import (
    CMD_AUTH_BIND,
    CMD_KICKOUT,
    CMD_PING,
    CMD_TYPE_PUSH,
    CMD_TYPE_RESPONSE,
    build_auth_bind_msg,
    build_ping_msg,
    build_push_ack,
    build_send_c2c_msg,
    build_send_group_msg,
    decode_auth_bind_rsp,
    decode_conn_msg,
    decode_inbound_message,
    decode_kickout_msg,
    decode_ping_rsp,
    decode_push_msg,
    decode_send_rsp,
)
from .constants import (
    AUTH_ALREADY_CODE,
    AUTH_FAILED_CODES,
    DEFAULT_API_DOMAIN,
    DEFAULT_WS_URL,
    HEARTBEAT_INTERVAL,
    HEARTBEAT_TIMEOUT_THRESHOLD,
    MAX_RECONNECT_ATTEMPTS,
    NO_RECONNECT_CLOSE_CODES,
    RECONNECT_DELAYS,
    SEND_TIMEOUT,
)
from ..utils import split_text
from .media import (
    build_file_msg_body,
    build_image_msg_body,
    download_and_upload_media,
    resolve_download_url,
)
from .utils import download_media

logger = logging.getLogger(__name__)


class YuanbaoChannel(BaseChannel):
    """Yuanbao channel using protobuf WebSocket for real-time messaging."""

    channel = "yuanbao"
    uses_manager_queue = True

    def __init__(
        self,
        process: ProcessHandler,
        enabled: bool,
        app_key: str,
        app_secret: str,
        api_domain: str = DEFAULT_API_DOMAIN,
        bot_prefix: str = "",
        media_dir: str = "",
        workspace_dir: Path | None = None,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
        dm_policy: str = "open",
        group_policy: str = "open",
        allow_from: Optional[List[str]] = None,
        deny_message: str = "",
        require_mention: bool = True,
        access_control_dm: bool = False,
        access_control_group: bool = False,
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
            access_control_dm=access_control_dm,
            access_control_group=access_control_group,
        )

        self.enabled = enabled
        self.app_key = app_key
        self.app_secret = app_secret
        self.api_domain = api_domain
        self.bot_prefix = bot_prefix
        self._workspace_dir = (
            Path(workspace_dir).expanduser() if workspace_dir else None
        )

        if not media_dir and self._workspace_dir:
            self._media_dir = self._workspace_dir / "media"
        elif media_dir:
            self._media_dir = Path(media_dir).expanduser()
        else:
            self._media_dir = DEFAULT_MEDIA_DIR / "yuanbao"
        self._media_dir.mkdir(parents=True, exist_ok=True)

        # Token manager (sign-token API)
        self._token_manager: Optional[TokenManager] = None

        # WebSocket state
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._media_session: Optional[aiohttp.ClientSession] = None
        self._connected = False
        self._reconnect_attempts = 0
        self._stopping = False

        # Bot identity (resolved during sign-token)
        self._bot_id: str = ""

        # Session tracking for reply routing
        self._session_map: Dict[str, Dict[str, Any]] = {}

        # Heartbeat state
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._receive_task: Optional[asyncio.Task] = None
        self._heartbeat_interval = HEARTBEAT_INTERVAL
        self._heartbeat_ack_received = True
        self._heartbeat_timeout_count = 0

        # Pending request-response matching
        self._pending_requests: Dict[str, asyncio.Future] = {}

        # Message dedup
        self._seen_message_ids: Dict[str, float] = {}

        # Track reconnect task to prevent GC
        self._reconnect_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_config(
        cls,
        process: ProcessHandler,
        config: YuanbaoChannelConfig,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
        workspace_dir: Path | None = None,
    ) -> "YuanbaoChannel":
        if isinstance(config, dict):
            return cls(
                process=process,
                enabled=config.get("enabled", False),
                app_key=config.get("app_key", ""),
                app_secret=config.get("app_secret", ""),
                api_domain=config.get(
                    "api_domain",
                    DEFAULT_API_DOMAIN,
                ),
                bot_prefix=config.get("bot_prefix", ""),
                media_dir=config.get("media_dir", ""),
                on_reply_sent=on_reply_sent,
                show_tool_details=show_tool_details,
                filter_tool_messages=filter_tool_messages,
                filter_thinking=filter_thinking,
                workspace_dir=workspace_dir,
                dm_policy=config.get("dm_policy", "open"),
                group_policy=config.get("group_policy", "open"),
                allow_from=config.get("allow_from", []),
                deny_message=config.get("deny_message", ""),
                require_mention=config.get("require_mention", True),
                access_control_dm=bool(
                    config.get("access_control_dm", False),
                ),
                access_control_group=bool(
                    config.get("access_control_group", False),
                ),
            )

        return cls(
            process=process,
            enabled=config.enabled,
            app_key=config.app_key,
            app_secret=config.app_secret,
            api_domain=config.api_domain,
            bot_prefix=config.bot_prefix,
            media_dir=getattr(config, "media_dir", "") or "",
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            filter_thinking=filter_thinking,
            workspace_dir=workspace_dir,
            dm_policy=getattr(config, "dm_policy", "open"),
            group_policy=getattr(config, "group_policy", "open"),
            allow_from=getattr(config, "allow_from", []),
            deny_message=getattr(config, "deny_message", ""),
            require_mention=getattr(config, "require_mention", True),
            access_control_dm=bool(
                getattr(config, "access_control_dm", False),
            ),
            access_control_group=bool(
                getattr(config, "access_control_group", False),
            ),
        )

    # ------------------------------------------------------------------
    # Session / handle helpers (like wecom / feishu)
    # ------------------------------------------------------------------

    def resolve_session_id(
        self,
        sender_id: str,
        channel_meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Build session_id from meta or sender_id."""
        meta = channel_meta or {}
        group_code = (meta.get("group_code") or "").strip()
        chat_type = (meta.get("chat_type") or "").strip()
        if chat_type == "group" and group_code:
            return f"yuanbao:group:{group_code}"
        if sender_id:
            return f"yuanbao:{sender_id}"
        return f"yuanbao:unknown"

    def get_to_handle_from_request(self, request: Any) -> str:
        """Return session_id as send target (like wecom)."""
        session_id = getattr(request, "session_id", "") or ""
        user_id = getattr(request, "user_id", "") or ""
        return session_id or f"yuanbao:{user_id}"

    def get_on_reply_sent_args(
        self,
        request: Any,
        to_handle: str,
    ) -> tuple:
        return (
            getattr(request, "user_id", "") or "",
            getattr(request, "session_id", "") or "",
        )

    def to_handle_from_target(self, *, user_id: str, session_id: str) -> str:
        """Map cron dispatch target to channel-specific to_handle."""
        return session_id or f"yuanbao:{user_id}"

    @staticmethod
    def _parse_target_from_handle(to_handle: str) -> Dict[str, str]:
        """Parse to_handle → chat_type, target_id.

        - ``yuanbao:group:<code>`` → group, <code>
        - ``yuanbao:<sender>``     → c2c, <sender>
        """
        handle = (to_handle or "").strip()
        if handle.startswith("yuanbao:group:"):
            return {
                "chat_type": "group",
                "target_id": handle.removeprefix("yuanbao:group:"),
            }
        if handle.startswith("yuanbao:direct:"):
            return {
                "chat_type": "c2c",
                "target_id": handle.removeprefix("yuanbao:direct:"),
            }
        if handle.startswith("yuanbao:"):
            return {
                "chat_type": "c2c",
                "target_id": handle.removeprefix("yuanbao:"),
            }
        return {"chat_type": "c2c", "target_id": handle}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _validate_config(self) -> None:
        if not self.app_key:
            raise ValueError("Yuanbao app_key is required")
        if not self.app_secret:
            raise ValueError("Yuanbao app_secret is required")

    async def health_check(self) -> Dict[str, Any]:
        if not self.enabled:
            return {
                "channel": self.channel,
                "status": "disabled",
                "detail": "Yuanbao channel is disabled.",
            }
        if not self._connected or self._ws is None or self._ws.closed:
            return {
                "channel": self.channel,
                "status": "unhealthy",
                "detail": "Yuanbao WebSocket is not connected.",
            }
        return {
            "channel": self.channel,
            "status": "healthy",
            "detail": f"Connected as bot={self._bot_id}",
        }

    async def start(self) -> None:
        """Start: sign token → connect WebSocket → auth bind."""
        if not self.enabled:
            logger.debug("yuanbao: start() skipped (enabled=false)")
            return

        try:
            self._validate_config()
        except ValueError as exc:
            logger.error("yuanbao: config validation failed: %s", exc)
            return

        self._token_manager = TokenManager(
            app_key=self.app_key,
            app_secret=self.app_secret,
            api_domain=self.api_domain,
        )

        logger.info("yuanbao: starting channel...")
        try:
            await self._connect()
        except Exception as exc:
            logger.error("yuanbao: initial connection failed: %s", exc)
            self._schedule_reconnect()

    async def _connect(self) -> None:
        """Sign token → WebSocket connect → protobuf AuthBind."""
        await self._cleanup_session()

        # Step 1: Get token via sign-token API
        token_data = await self._token_manager.get_token()
        self._bot_id = token_data.bot_id
        logger.info(
            "yuanbao: got token for bot_id=%s",
            self._bot_id,
        )

        # Step 2: Connect WebSocket (binary protocol)
        self._session = aiohttp.ClientSession()
        try:
            self._ws = await self._session.ws_connect(
                DEFAULT_WS_URL,
                timeout=aiohttp.ClientWSTimeout(
                    ws_close=float(SEND_TIMEOUT),
                ),
            )
        except Exception:
            self._connected = False
            raise

        logger.info("yuanbao: WebSocket connected, sending auth...")

        # Step 3: Send AuthBind protobuf
        auth_binary = build_auth_bind_msg(
            biz_id="ybBot",
            uid=self._bot_id,
            source=token_data.source,
            token=token_data.token,
        )
        if auth_binary is None:
            raise RuntimeError("Failed to encode AuthBind message")

        await self._ws.send_bytes(auth_binary)

        # Step 4: Wait for auth response
        auth_ok = await self._wait_for_auth_response()
        if not auth_ok:
            raise RuntimeError("AuthBind failed")

        self._connected = True
        self._reconnect_attempts = 0
        self._heartbeat_ack_received = True
        self._heartbeat_timeout_count = 0

        logger.info("yuanbao: authenticated as bot=%s ✅", self._bot_id)

        # Start heartbeat and receive loops
        self._heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(),
        )
        self._receive_task = asyncio.create_task(
            self._receive_loop(),
        )

    async def _wait_for_auth_response(self) -> bool:
        """Wait for AuthBindRsp from server."""
        try:
            msg = await asyncio.wait_for(
                self._ws.receive(),
                timeout=SEND_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.error("yuanbao: auth response timeout")
            return False

        if msg.type != aiohttp.WSMsgType.BINARY:
            logger.error(
                "yuanbao: expected binary auth response, got %s",
                msg.type,
            )
            return False

        conn_msg = decode_conn_msg(msg.data)
        if not conn_msg:
            logger.error("yuanbao: failed to decode auth response")
            return False

        head = conn_msg["head"]
        if head.get("cmd") != CMD_AUTH_BIND:
            logger.error(
                "yuanbao: unexpected auth cmd: %s",
                head.get("cmd"),
            )
            return False

        raw_data = conn_msg["data"]
        logger.info(
            "yuanbao: auth response head=%s, data_len=%s, status=%s",
            head.get("cmd"),
            len(raw_data) if raw_data else 0,
            head.get("status", 0),
        )

        # AuthBindRsp may be empty on success (status in head)
        status_code = head.get("status", 0)
        rsp = decode_auth_bind_rsp(raw_data) if raw_data else {}
        if rsp is None:
            rsp = {}

        code = rsp.get("code", status_code)
        if code == 0 or code == AUTH_ALREADY_CODE:
            connect_id = rsp.get("connectId", "")
            logger.info(
                "yuanbao: auth success connectId=%s",
                connect_id,
            )
            return True

        logger.error(
            "yuanbao: auth failed: code=%s, message=%s",
            code,
            rsp.get("message", ""),
        )
        return False

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    async def _heartbeat_loop(self) -> None:
        """Send periodic protobuf Ping to keep connection alive."""
        while self._connected and self._ws and not self._ws.closed:
            try:
                await asyncio.sleep(self._heartbeat_interval)
                if not self._connected or not self._ws or self._ws.closed:
                    break

                if not self._heartbeat_ack_received:
                    self._heartbeat_timeout_count += 1
                    logger.warning(
                        "yuanbao: heartbeat timeout (%s/%s)",
                        self._heartbeat_timeout_count,
                        HEARTBEAT_TIMEOUT_THRESHOLD,
                    )
                    if (
                        self._heartbeat_timeout_count
                        >= HEARTBEAT_TIMEOUT_THRESHOLD
                    ):
                        logger.error(
                            "yuanbao: heartbeat threshold reached, reconnecting",
                        )
                        await self._force_close_ws()
                        break
                else:
                    self._heartbeat_timeout_count = 0

                self._heartbeat_ack_received = False
                ping_binary = build_ping_msg()
                if ping_binary is not None:
                    await asyncio.wait_for(
                        self._ws.send_bytes(ping_binary),
                        timeout=SEND_TIMEOUT,
                    )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("yuanbao: heartbeat error: %s", exc)
                await self._force_close_ws()
                break

    async def _force_close_ws(self) -> None:
        if self._ws and not self._ws.closed:
            try:
                await self._ws.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Receive loop
    # ------------------------------------------------------------------

    async def _receive_loop(self) -> None:
        """Receive and dispatch binary protobuf frames."""
        if not self._ws:
            return
        try:
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.BINARY:
                    await self._handle_binary_frame(msg.data)
                elif msg.type == aiohttp.WSMsgType.CLOSE:
                    code = msg.data or 0
                    logger.info(
                        "yuanbao: ws closed by server code=%s",
                        code,
                    )
                    if code in NO_RECONNECT_CLOSE_CODES:
                        logger.error(
                            "yuanbao: non-retryable close code=%s",
                            code,
                        )
                        self._stopping = True
                    break
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(
                        "yuanbao: ws error: %s",
                        self._ws.exception(),
                    )
                    break
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("yuanbao: receive loop error: %s", exc)
        finally:
            self._connected = False
            if not self._stopping:
                self._schedule_reconnect()

    async def _handle_binary_frame(self, raw: bytes) -> None:
        """Decode and dispatch a binary ConnMsg frame."""
        conn_msg = decode_conn_msg(raw)
        if not conn_msg or not conn_msg.get("head"):
            logger.warning(
                "yuanbao: received undecodable frame (%s bytes)",
                len(raw),
            )
            return

        head = conn_msg["head"]
        cmd_type = head.get("cmdType", 0)
        cmd = head.get("cmd", "")
        data = conn_msg.get("data", b"")

        logger.info(
            "yuanbao: frame cmdType=%s cmd=%s module=%s data_len=%s",
            cmd_type,
            cmd,
            head.get("module", ""),
            len(data) if data else 0,
        )

        if cmd_type == CMD_TYPE_RESPONSE:
            await self._handle_response(head, data)
        elif cmd_type == CMD_TYPE_PUSH:
            await self._handle_push(head, data, raw)
        else:
            logger.info("yuanbao: unhandled cmdType=%s", cmd_type)

    async def _handle_response(
        self,
        head: dict,
        data: bytes,
    ) -> None:
        """Handle a response frame (auth, ping, or business)."""
        cmd = head.get("cmd", "")

        if cmd == CMD_PING:
            self._heartbeat_ack_received = True
            rsp = decode_ping_rsp(data)
            if rsp and rsp.get("heartInterval"):
                self._heartbeat_interval = rsp["heartInterval"]
            return

        if cmd == CMD_AUTH_BIND:
            rsp = decode_auth_bind_rsp(data)
            status = head.get("status", 0)
            if status != 0 and status in AUTH_FAILED_CODES:
                logger.warning(
                    "yuanbao: auth failed in-band code=%s, refreshing",
                    status,
                )
                await self._handle_auth_failure()
            return

        # Business response — log and resolve pending request
        rsp = decode_send_rsp(data) if data else {}
        logger.info(
            "yuanbao: response cmd=%s status=%s rsp=%s",
            cmd,
            head.get("status", 0),
            rsp,
        )
        msg_id = head.get("msgId", "")
        if msg_id in self._pending_requests:
            future = self._pending_requests.pop(msg_id)
            if not future.done():
                future.set_result(rsp)

    async def _handle_push(
        self,
        head: dict,
        data: bytes,
        raw_frame: bytes,
    ) -> None:
        """Handle a push frame (inbound message).

        Push structure: ConnMsg.data may contain:
        1. PushMsg wrapper (cmd, module, msgId, data) → inner data is InboundMessagePush
        2. Direct InboundMessagePush (try as fallback)
        """
        # Send push ACK if required
        if head.get("needAck"):
            ack = build_push_ack(head)
            if ack is not None and self._ws and not self._ws.closed:
                try:
                    await self._ws.send_bytes(ack)
                except Exception:
                    pass

        cmd = head.get("cmd", "")

        # Kickout
        if cmd == CMD_KICKOUT:
            kickout = decode_kickout_msg(data)
            reason = kickout.get("reason", "") if kickout else ""
            logger.warning("yuanbao: kicked out: %s", reason)
            self._stopping = True
            await self._force_close_ws()
            return

        if not data:
            return

        # Try decoding InboundMessagePush from multiple paths:
        inbound = None

        # Path 1: Data is JSON text (server sends JSON, not protobuf, for push)
        try:
            json_data = json.loads(data)
            if isinstance(json_data, dict) and json_data.get(
                "callback_command",
            ):
                inbound = self._parse_json_inbound(json_data)
                logger.info("yuanbao: decoded via JSON push")
        except (ValueError, UnicodeDecodeError):
            pass

        # Path 2: Protobuf InboundMessagePush (direct)
        if not inbound or not inbound.get("callback_command"):
            inbound = decode_inbound_message(data)
            if inbound and inbound.get("callback_command"):
                logger.info("yuanbao: decoded via protobuf InboundMessagePush")

        # Path 3: PushMsg wrapper → inner data
        if not inbound or not inbound.get("callback_command"):
            push_msg = decode_push_msg(data)
            if push_msg and push_msg.get("data"):
                push_data = push_msg["data"]
                if isinstance(push_data, str):
                    try:
                        push_data = base64.b64decode(push_data)
                    except Exception:
                        pass
                if isinstance(push_data, (bytes, bytearray)):
                    inbound = decode_inbound_message(push_data)
                    if inbound:
                        logger.info("yuanbao: decoded via PushMsg wrapper")

        if inbound and inbound.get("callback_command"):
            logger.info(
                "yuanbao: received message cmd=%s from=%s",
                inbound.get("callback_command"),
                inbound.get("from_account", ""),
            )
            await self._handle_chat_message(inbound)
        else:
            logger.info(
                "yuanbao: push not decoded (head_cmd=%s, data_len=%s)",
                cmd,
                len(data),
            )

    def _parse_json_inbound(self, data: dict) -> dict:
        """Parse a JSON-format inbound message into internal format."""
        msg_body = []
        for elem in data.get("msg_body", []):
            content = elem.get("msg_content", {})
            # Pass through the entire msg_content to preserve all fields
            # (video, audio, etc.) rather than cherry-picking known keys.
            if isinstance(content, str):
                try:
                    content = json.loads(content)
                except (ValueError, TypeError):
                    content = {"text": content}
            msg_body.append(
                {
                    "msg_type": elem.get("msg_type", ""),
                    "msg_content": content
                    if isinstance(content, dict)
                    else {},
                },
            )

        return {
            "callback_command": data.get("callback_command", ""),
            "from_account": data.get("from_account", ""),
            "to_account": data.get("to_account", ""),
            "sender_nickname": data.get("sender_nickname", ""),
            "group_code": data.get("group_code", ""),
            "group_name": data.get("group_name", ""),
            "msg_seq": data.get("msg_seq", 0),
            "msg_time": data.get("msg_time", 0),
            "msg_key": data.get("msg_key", ""),
            "msg_id": data.get("msg_id", ""),
            "msg_body": msg_body,
            "bot_owner_id": data.get("bot_owner_id", ""),
            "claw_msg_type": data.get("claw_msg_type", 0),
        }

    async def _handle_auth_failure(self) -> None:
        """Handle auth failure by refreshing token and reconnecting."""
        if self._token_manager:
            try:
                token_data = await self._token_manager.force_refresh()
                self._bot_id = token_data.bot_id
                logger.info(
                    "yuanbao: token refreshed, reconnecting...",
                )
            except Exception as exc:
                logger.error(
                    "yuanbao: token refresh failed: %s",
                    exc,
                )
        await self._force_close_ws()

    # ------------------------------------------------------------------
    # Native → AgentRequest
    # ------------------------------------------------------------------

    def build_agent_request_from_native(self, native_payload: Any) -> Any:
        """Convert Yuanbao native dict → AgentRequest."""
        payload = native_payload if isinstance(native_payload, dict) else {}
        channel_id = payload.get("channel_id") or self.channel
        sender_id = payload.get("sender_id") or ""
        content_parts = payload.get("content_parts") or []
        meta = payload.get("meta") or {}
        session_id = self.resolve_session_id(sender_id, meta)
        request = self.build_agent_request_from_user_content(
            channel_id=channel_id,
            sender_id=sender_id,
            session_id=session_id,
            content_parts=content_parts,
            channel_meta=meta,
        )
        request.user_id = sender_id
        request.channel_meta = meta
        return request

    # ------------------------------------------------------------------
    # Inbound message handling
    # ------------------------------------------------------------------

    async def _handle_chat_message(
        self,
        inbound: Dict[str, Any],
    ) -> None:
        """Convert decoded InboundMessagePush to native payload."""
        msg_id = inbound.get("msg_id", "") or inbound.get(
            "msg_key",
            "",
        )

        # Dedup
        if msg_id and msg_id in self._seen_message_ids:
            return
        if msg_id:
            self._seen_message_ids[msg_id] = asyncio.get_running_loop().time()
            if len(self._seen_message_ids) > 5000:
                self._prune_seen_ids()

        sender_id = inbound.get("from_account", "")
        group_code = inbound.get("group_code", "")
        callback_cmd = inbound.get("callback_command", "")

        # Determine chat type
        is_group = bool(group_code) or "Group" in callback_cmd
        chat_type = "group" if is_group else "c2c"

        # Ignore messages from self
        if sender_id == self._bot_id:
            return

        # Build session id
        if is_group:
            session_id = f"yuanbao:group:{group_code}"
        else:
            session_id = f"yuanbao:direct:{sender_id}"

        # Parse content from protobuf msg_body
        content_parts = await self._parse_msg_body(
            inbound.get("msg_body", []),
        )
        if not content_parts:
            return

        # Store session info for reply routing
        self._session_map[session_id] = {
            "chat_type": chat_type,
            "sender_id": sender_id,
            "group_code": group_code,
            "msg_id": msg_id,
        }

        native = {
            "channel_id": self.channel,
            "sender_id": sender_id,
            "session_id": session_id,
            "content_parts": content_parts,
            "meta": {
                "session_id": session_id,
                "chat_type": chat_type,
                "group_code": group_code,
                "msg_id": msg_id,
                "sender_id": sender_id,
            },
        }

        if self._enqueue:
            self._enqueue(native)
        else:
            logger.warning(
                "yuanbao: _enqueue not set, message dropped",
            )

    async def _resolve_media_url(self, url: str) -> str:
        """Resolve Yuanbao CDN URL to a real download URL via download API."""
        if not self._token_manager or not url:
            return url
        try:
            session = await self._get_or_create_http_session()
            auth_headers = await self._token_manager.get_auth_headers()
            return await resolve_download_url(
                url,
                session,
                self.api_domain,
                auth_headers,
            )
        except Exception as exc:
            logger.warning("yuanbao: resolve media URL failed: %s", exc)
            return url

    async def _parse_msg_body(
        self,
        msg_body: List[dict],
    ) -> List[Any]:
        """Parse protobuf msg_body elements into content parts."""
        parts: List[Any] = []

        for elem in msg_body:
            msg_type = elem.get("msg_type", "")
            content = elem.get("msg_content", {})

            if msg_type == "TIMTextElem":
                text = content.get("text", "").strip()
                if text:
                    if self._bot_id:
                        text = text.replace(
                            f"@{self._bot_id}",
                            "",
                        ).strip()
                    if text:
                        parts.append(
                            TextContent(
                                type=ContentType.TEXT,
                                text=text,
                            ),
                        )

            elif msg_type == "TIMImageElem":
                image_url = ""
                for img_info in content.get(
                    "image_info_array",
                    [],
                ):
                    if img_info.get("url"):
                        image_url = img_info["url"]
                        break
                if not image_url:
                    image_url = content.get("url", "")
                if image_url:
                    resolved_url = await self._resolve_media_url(image_url)
                    local_path = await download_media(
                        resolved_url,
                        self._media_dir,
                        filename="image.jpg",
                    )
                    if local_path:
                        file_uri = Path(local_path).resolve().as_uri()
                        parts.append(
                            ImageContent(
                                type=ContentType.IMAGE,
                                image_url=file_uri,
                            ),
                        )
                    else:
                        parts.append(
                            ImageContent(
                                type=ContentType.IMAGE,
                                image_url=image_url,
                            ),
                        )

            elif msg_type == "TIMFileElem":
                file_url = content.get("url", "")
                filename = content.get("file_name", "file")
                if file_url:
                    resolved_url = await self._resolve_media_url(file_url)
                    local_path = await download_media(
                        resolved_url,
                        self._media_dir,
                        filename=filename,
                    )
                    if local_path:
                        file_uri = Path(local_path).resolve().as_uri()
                        parts.append(
                            FileContent(
                                type=ContentType.FILE,
                                file_url=file_uri,
                                filename=filename,
                            ),
                        )
                    else:
                        parts.append(
                            FileContent(
                                type=ContentType.FILE,
                                file_url=file_url,
                                filename=filename,
                            ),
                        )

            elif msg_type == "TIMVideoFileElem":
                video_url = content.get("videoUrl", "") or content.get(
                    "url",
                    "",
                )
                video_name = (
                    content.get("videoName", "video.mp4") or "video.mp4"
                )
                if video_url:
                    resolved_url = await self._resolve_media_url(video_url)
                    local_path = await download_media(
                        resolved_url,
                        self._media_dir,
                        filename=video_name,
                    )
                    if local_path:
                        file_uri = Path(local_path).resolve().as_uri()
                        parts.append(
                            FileContent(
                                type=ContentType.FILE,
                                file_url=file_uri,
                                filename=video_name,
                            ),
                        )

            elif msg_type == "TIMSoundElem":
                sound_url = content.get("url", "")
                if sound_url:
                    resolved_url = await self._resolve_media_url(sound_url)
                    local_path = await download_media(
                        resolved_url,
                        self._media_dir,
                        filename="voice.wav",
                    )
                    if local_path:
                        file_uri = Path(local_path).resolve().as_uri()
                        parts.append(
                            FileContent(
                                type=ContentType.FILE,
                                file_url=file_uri,
                                filename="voice.wav",
                            ),
                        )

        return parts

    def _prune_seen_ids(self) -> None:
        sorted_ids = sorted(
            self._seen_message_ids.items(),
            key=lambda kv: kv[1],
        )
        remove_count = len(sorted_ids) // 2
        for msg_id, _ in sorted_ids[:remove_count]:
            self._seen_message_ids.pop(msg_id, None)

    # ------------------------------------------------------------------
    # Outgoing: send text / media
    # ------------------------------------------------------------------

    def _resolve_send_target(
        self,
        to_handle: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, str]]:
        """Resolve send target from to_handle or session_map.

        Returns dict with chat_type and target_id, or None.
        """
        meta = meta or {}
        session_id = meta.get("session_id") or to_handle

        # Try session_map first (has real sender_id / group_code)
        session_info = self._session_map.get(session_id, {})
        if session_info:
            chat_type = session_info.get("chat_type", "c2c")
            target_id = (
                session_info.get("group_code")
                if chat_type == "group"
                else session_info.get("sender_id", "")
            )
            if target_id:
                return {"chat_type": chat_type, "target_id": target_id}

        # Fallback: parse from to_handle string
        parsed = self._parse_target_from_handle(to_handle)
        if parsed.get("target_id"):
            return parsed

        logger.warning(
            "yuanbao: no target resolved for to_handle=%s session=%s",
            to_handle[:50] if to_handle else "",
            session_id[:50] if session_id else "",
        )
        return None

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send a text message to a Yuanbao chat."""
        if not self.enabled or not self._ws or not self._connected:
            logger.warning("yuanbao: cannot send — not connected")
            return

        if not text or not text.strip():
            return

        target = self._resolve_send_target(to_handle, meta)
        if not target:
            return

        logger.info(
            "yuanbao: send text to %s:%s len=%s",
            target["chat_type"],
            target["target_id"][:20],
            len(text),
        )

        chunks = split_text(text)
        for chunk in chunks:
            await self._send_text_message(
                target["chat_type"],
                target["target_id"],
                chunk,
            )

    async def _send_text_message(
        self,
        chat_type: str,
        target_id: str,
        text: str,
    ) -> None:
        """Send a text message via protobuf binary WebSocket."""
        if not self._ws or not self._connected:
            return

        msg_body = [
            {
                "msg_type": "TIMTextElem",
                "msg_content": {"text": text},
            },
        ]

        if chat_type == "group":
            result = build_send_group_msg(
                group_code=target_id,
                msg_body=msg_body,
                from_account=self._bot_id,
            )
        else:
            result = build_send_c2c_msg(
                to_account=target_id,
                msg_body=msg_body,
                from_account=self._bot_id,
            )

        if result is None:
            logger.error("yuanbao: failed to encode send message")
            return

        raw, msg_id = result
        try:
            await self._ws.send_bytes(raw)
        except Exception as exc:
            logger.error("yuanbao: failed to send text: %s", exc)

    async def send_content_parts(
        self,
        to_handle: str,
        parts: List[OutgoingContentPart],
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send text and media parts to Yuanbao chat.

        Overrides base: separates text and media, sends text first
        (with chunking), then each media part individually.
        """
        if not self.enabled or not self._ws or not self._connected:
            return

        target = self._resolve_send_target(to_handle, meta)
        if not target:
            return

        prefix = (meta or {}).get("bot_prefix", "") or self.bot_prefix or ""
        text_parts: List[str] = []
        media_parts: List[OutgoingContentPart] = []

        for part in parts:
            part_type = getattr(part, "type", None)
            if part_type == ContentType.TEXT and getattr(part, "text", None):
                text_parts.append(part.text)
            elif part_type == ContentType.REFUSAL and getattr(
                part,
                "refusal",
                None,
            ):
                text_parts.append(part.refusal)
            elif part_type in (
                ContentType.IMAGE,
                ContentType.FILE,
                ContentType.VIDEO,
                ContentType.AUDIO,
            ):
                media_parts.append(part)

        body = "\n".join(text_parts).strip()
        if prefix and body:
            body = prefix + "  " + body

        if body:
            for chunk in split_text(body):
                await self._send_text_message(
                    target["chat_type"],
                    target["target_id"],
                    chunk,
                )

        # Media: upload to COS then send as TIMImageElem / TIMFileElem
        for media_part in media_parts:
            await self._send_media_part(
                target["chat_type"],
                target["target_id"],
                media_part,
            )

    async def _send_media_part(
        self,
        chat_type: str,
        target_id: str,
        part: OutgoingContentPart,
    ) -> None:
        """Upload media to COS and send as TIMImageElem / TIMFileElem."""
        media_url = self._extract_media_url(part)
        if not media_url:
            return

        if not self._token_manager:
            logger.warning("yuanbao: cannot upload media — no token manager")
            return

        try:
            session = await self._get_or_create_http_session()
            auth_headers = await self._token_manager.get_auth_headers()
            result = await download_and_upload_media(
                media_url,
                session,
                self.api_domain,
                auth_headers,
            )

            if result.mime_type.startswith("image/"):
                msg_body = build_image_msg_body(result)
            else:
                msg_body = build_file_msg_body(result)

            await self._send_raw_msg_body(chat_type, target_id, msg_body)
            logger.info(
                "yuanbao: sent media %s → %s",
                result.filename,
                result.url[:60],
            )
        except Exception as exc:
            logger.error("yuanbao: media upload/send failed: %s", exc)
            # Fallback: send as text link
            fallback = self._media_url_fallback_text(part)
            if fallback:
                await self._send_text_message(chat_type, target_id, fallback)

    async def _get_or_create_http_session(self) -> aiohttp.ClientSession:
        """Get or create an aiohttp session for media uploads.

        Uses a dedicated session separate from the WebSocket session to
        avoid connection conflicts.
        """
        if self._media_session is None or self._media_session.closed:
            self._media_session = aiohttp.ClientSession()
        return self._media_session

    @staticmethod
    def _extract_media_url(part: OutgoingContentPart) -> str:
        """Extract the media URL/path from an outgoing content part."""
        part_type = getattr(part, "type", None)
        if part_type == ContentType.IMAGE:
            return getattr(part, "image_url", "") or ""
        if part_type == ContentType.FILE:
            return (
                getattr(part, "file_url", "")
                or getattr(part, "file_id", "")
                or ""
            )
        if part_type == ContentType.VIDEO:
            return getattr(part, "video_url", "") or ""
        if part_type == ContentType.AUDIO:
            return (
                getattr(part, "data", "")
                or getattr(part, "audio_url", "")
                or getattr(part, "file_url", "")
                or ""
            )
        return ""

    @staticmethod
    def _media_url_fallback_text(part: OutgoingContentPart) -> str:
        """Build fallback text when media upload fails."""
        part_type = getattr(part, "type", None)
        if part_type == ContentType.IMAGE:
            url = getattr(part, "image_url", "")
            return f"[图片: {url}]" if url else ""
        if part_type == ContentType.FILE:
            url = getattr(part, "file_url", "") or getattr(part, "file_id", "")
            name = getattr(part, "filename", "file")
            return f"[文件: {name} - {url}]" if url else ""
        if part_type == ContentType.VIDEO:
            url = getattr(part, "video_url", "")
            return f"[视频: {url}]" if url else ""
        if part_type == ContentType.AUDIO:
            return "[音频]"
        return ""

    async def _send_raw_msg_body(
        self,
        chat_type: str,
        target_id: str,
        msg_body: list,
    ) -> None:
        """Send a raw msg_body (list of TIM elements) via WebSocket."""
        if not self._ws or not self._connected:
            return

        if chat_type == "group":
            result = build_send_group_msg(
                group_code=target_id,
                msg_body=msg_body,
                from_account=self._bot_id,
            )
        else:
            result = build_send_c2c_msg(
                to_account=target_id,
                msg_body=msg_body,
                from_account=self._bot_id,
            )

        if result is None:
            logger.error("yuanbao: failed to encode media message")
            return

        raw, msg_id = result
        try:
            await self._ws.send_bytes(raw)
        except Exception as exc:
            logger.error("yuanbao: failed to send media: %s", exc)

    # ------------------------------------------------------------------
    # Reconnect / cleanup / stop
    # ------------------------------------------------------------------

    def _schedule_reconnect(self) -> None:
        if self._stopping:
            return
        if self._reconnect_attempts >= MAX_RECONNECT_ATTEMPTS:
            logger.error("yuanbao: max reconnect attempts reached")
            return

        delay_idx = min(
            self._reconnect_attempts,
            len(RECONNECT_DELAYS) - 1,
        )
        delay = RECONNECT_DELAYS[delay_idx]
        self._reconnect_attempts += 1

        logger.info(
            "yuanbao: reconnecting in %ss (attempt %s)",
            delay,
            self._reconnect_attempts,
        )

        async def _reconnect() -> None:
            await asyncio.sleep(delay)
            if self._stopping or self._connected:
                return
            await self._cleanup_session()
            try:
                await self._connect()
                logger.info("yuanbao: reconnected successfully")
            except Exception as exc:
                logger.error("yuanbao: reconnect failed: %s", exc)
                self._schedule_reconnect()

        self._reconnect_task = asyncio.create_task(_reconnect())

    async def _cleanup_session(self) -> None:
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        if self._session:
            try:
                await self._session.close()
            except Exception:
                pass
            self._session = None

        if self._media_session:
            try:
                await self._media_session.close()
            except Exception:
                pass
            self._media_session = None

    async def stop(self) -> None:
        logger.info("yuanbao: stopping channel...")
        self._stopping = True
        self._connected = False

        for task in (
            self._heartbeat_task,
            self._receive_task,
            self._reconnect_task,
        ):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        self._heartbeat_task = None
        self._receive_task = None
        self._reconnect_task = None

        await self._cleanup_session()

        if self._token_manager:
            await self._token_manager.close()
            self._token_manager = None

        logger.info("yuanbao: channel stopped")
