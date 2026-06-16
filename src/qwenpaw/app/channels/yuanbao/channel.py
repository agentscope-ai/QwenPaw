# -*- coding: utf-8 -*-
# pylint: disable=too-many-instance-attributes
"""Yuanbao Channel: WebSocket-based bot messaging for Tencent Yuanbao.

Uses protobuf binary protocol over WebSocket with sign-token authentication.
Supports C2C (direct) and group chat with streaming output.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import aiohttp

from agentscope_runtime.engine.schemas.agent_schemas import (
    AudioContent,
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
    build_heartbeat_msg,
    build_ping_msg,
    build_push_ack,
    build_send_c2c_msg,
    build_send_group_msg,
    decode_auth_bind_rsp,
    decode_conn_msg,
    decode_kickout_msg,
    decode_ping_rsp,
    decode_send_rsp,
)
from .constants import (
    AUTH_ALREADY_CODE,
    AUTH_FAILED_CODES,
    DEFAULT_API_DOMAIN,
    HEARTBEAT_FINISH,
    HEARTBEAT_RUNNING,
    TYPING_KEEPALIVE_INTERVAL,
    DEFAULT_WS_URL,
    HEARTBEAT_INTERVAL,
    HEARTBEAT_TIMEOUT_THRESHOLD,
    MAX_RECONNECT_ATTEMPTS,
    NO_RECONNECT_CLOSE_CODES,
    RECONNECT_DELAYS,
    SEND_TIMEOUT,
    SESSION_ID_SUFFIX_LEN,
)
from ..utils import split_text
from .media import (
    build_file_msg_body,
    build_image_msg_body,
    download_and_upload_media,
    resolve_download_url,
)
from .utils import download_media

if TYPE_CHECKING:
    from agentscope_runtime.engine.schemas.agent_schemas import AgentRequest

logger = logging.getLogger(__name__)


# File extensions treated as audio.  Files with these suffixes are wrapped
# as ``AudioContent`` so they flow through the unified ASR pipeline; all
# other suffixes fall back to ``FileContent``.
_AUDIO_EXTS = frozenset(
    {
        ".mp3",
        ".wav",
        ".m4a",
        ".ogg",
        ".opus",
        ".silk",
        ".amr",
        ".aac",
        ".flac",
    },
)

# Yuanbao ``cloud_custom_data.quote.type`` -> human-readable kind label.
# 1 = text (desc carries text content)
# 2 = image (desc empty)
# 3 = file or audio (desc carries filename; routed by suffix below)
_QUOTE_TYPE_LABEL = {1: "message", 2: "image", 3: "file"}


def _short_id(raw_id: str) -> str:
    """Take last N chars of a raw account/group id."""
    n = SESSION_ID_SUFFIX_LEN
    return raw_id[-n:] if len(raw_id) >= n else raw_id


def _sender_display(nickname: str, raw_sender_id: str) -> str:
    """Build human-readable sender display: nickname#last4."""
    nick = (nickname or "").strip() or "unknown"
    suffix = (
        raw_sender_id[-4:]
        if len(raw_sender_id) >= 4
        else (raw_sender_id or "????")
    )
    return f"{nick}#{suffix}"


class YuanbaoChannel(BaseChannel):
    """Yuanbao channel using protobuf WebSocket for real-time messaging."""

    channel = "yuanbao"
    uses_manager_queue = True

    def __init__(
        self,
        process: ProcessHandler,
        enabled: bool,
        app_id: str,
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
        accept_bot_messages: bool = False,
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

        self.accept_bot_messages = accept_bot_messages
        self.enabled = enabled
        self.app_id = app_id
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

        # Session tracking for reply routing (short_id → raw ids)
        self._session_map: Dict[str, Dict[str, Any]] = {}
        self._load_session_map_from_disk()

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

        # Typing indicator keepalive tasks: session_id → Task
        self._typing_tasks: Dict[str, asyncio.Task] = {}

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_env(
        cls,
        process: ProcessHandler,
        on_reply_sent: OnReplySent = None,
    ) -> "YuanbaoChannel":
        import os

        allow_from_env = os.getenv("YUANBAO_ALLOW_FROM", "")
        allow_from = (
            [s.strip() for s in allow_from_env.split(",") if s.strip()]
            if allow_from_env
            else []
        )
        return cls(
            process=process,
            enabled=os.getenv("YUANBAO_CHANNEL_ENABLED", "1") == "1",
            app_id=os.getenv("YUANBAO_APP_ID", ""),
            app_secret=os.getenv("YUANBAO_APP_SECRET", ""),
            api_domain=os.getenv("YUANBAO_API_DOMAIN", DEFAULT_API_DOMAIN),
            bot_prefix=os.getenv("YUANBAO_BOT_PREFIX", ""),
            on_reply_sent=on_reply_sent,
            dm_policy=os.getenv("YUANBAO_DM_POLICY", "open"),
            group_policy=os.getenv("YUANBAO_GROUP_POLICY", "open"),
            allow_from=allow_from,
            deny_message=os.getenv("YUANBAO_DENY_MESSAGE", ""),
            require_mention=os.getenv("YUANBAO_REQUIRE_MENTION", "1") == "1",
            accept_bot_messages=os.getenv(
                "YUANBAO_ACCEPT_BOT_MESSAGES",
                "0",
            )
            == "1",
        )

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
                app_id=config.get("app_id", ""),
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
                accept_bot_messages=bool(
                    config.get("accept_bot_messages", False),
                ),
            )

        return cls(
            process=process,
            enabled=config.enabled,
            app_id=config.app_id,
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
            accept_bot_messages=bool(
                getattr(config, "accept_bot_messages", False),
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
        if meta.get("session_id"):
            return meta["session_id"]
        group_code = (meta.get("group_code") or "").strip()
        chat_type = (meta.get("chat_type") or "").strip()
        if chat_type == "group" and group_code:
            return group_code
        if sender_id:
            return _short_id(sender_id)
        return "unknown"

    def get_to_handle_from_request(self, request: Any) -> str:
        """Return session_id as send target."""
        session_id = getattr(request, "session_id", "") or ""
        user_id = getattr(request, "user_id", "") or ""
        return session_id or user_id

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
        return session_id or user_id

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _validate_config(self) -> None:
        if not self.app_id:
            raise ValueError("Yuanbao app_id is required")
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
            app_id=self.app_id,
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
        assert self._token_manager is not None
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
        assert self._ws is not None
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
        if code in (0, AUTH_ALREADY_CODE):
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
                            "yuanbao: heartbeat threshold "
                            "reached, reconnecting",
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
        logger.debug(
            "yuanbao: raw ws frame %d bytes",
            len(raw),
        )
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

        logger.debug(
            "yuanbao: frame cmdType=%s cmd=%s module=%s data_len=%s",
            cmd_type,
            cmd,
            head.get("module", ""),
            len(data) if data else 0,
        )

        if cmd_type == CMD_TYPE_RESPONSE:
            await self._handle_response(head, data)
        elif cmd_type == CMD_TYPE_PUSH:
            await self._handle_push(head, data)
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

        # Business response — resolve pending request
        rsp = decode_send_rsp(data) if data else {}
        logger.debug(
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
    ) -> None:
        """Handle a push frame (inbound message).

        ConnMsg.data contains a JSON-encoded message body.
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

        # Server sends JSON inside the protobuf data field
        try:
            json_data = json.loads(data)
        except (ValueError, UnicodeDecodeError):
            logger.warning(
                "yuanbao: push data is not valid JSON (cmd=%s, %d bytes)",
                cmd,
                len(data),
            )
            return

        if not isinstance(json_data, dict):
            return

        callback_cmd = json_data.get("callback_command", "")
        if not callback_cmd:
            logger.info(
                "yuanbao: push without callback_command (cmd=%s)",
                cmd,
            )
            return

        logger.debug(
            "yuanbao: raw inbound JSON: %s",
            json.dumps(json_data, ensure_ascii=False)[:3000],
        )

        inbound = self._normalize_inbound(json_data)
        logger.info(
            "yuanbao: recv %s from=%s",
            callback_cmd,
            inbound.get("from_account", "")[-8:],
        )
        await self._handle_chat_message(inbound)

    @staticmethod
    def _normalize_inbound(data: dict) -> dict:
        """Normalize inbound JSON.

        Ensures ``msg_content`` is always a dict and parses the
        ``cloud_custom_data`` JSON string into a dict (used for quoted
        message extraction downstream).
        """
        msg_body = []
        for elem in data.get("msg_body", []):
            content = elem.get("msg_content", {})
            if isinstance(content, str):
                try:
                    content = json.loads(content)
                except (ValueError, TypeError):
                    content = {"text": content}
            if not isinstance(content, dict):
                content = {}
            msg_body.append(
                {
                    "msg_type": elem.get("msg_type", ""),
                    "msg_content": content,
                },
            )

        ccd = data.get("cloud_custom_data", "")
        if isinstance(ccd, str):
            try:
                ccd = json.loads(ccd) if ccd else {}
            except (ValueError, TypeError):
                ccd = {}
        if not isinstance(ccd, dict):
            ccd = {}

        normalized = dict(data)
        normalized["msg_body"] = msg_body
        normalized["cloud_custom_data"] = ccd
        return normalized

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

    # pylint: disable=too-many-branches
    async def _handle_chat_message(
        self,
        inbound: Dict[str, Any],
    ) -> None:
        """Convert decoded inbound JSON to native payload."""
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

        raw_sender_id = inbound.get("from_account", "")
        callback_cmd = inbound.get("callback_command", "")
        nickname = inbound.get("sender_nickname", "")

        # Determine chat type from callback_command prefix
        is_group = callback_cmd.startswith("Group.")
        chat_type = "group" if is_group else "c2c"
        group_code = inbound.get("group_code", "") if is_group else ""

        # Filter bot messages unless accept_bot_messages is enabled.
        # Yuanbao does not push the bot's own messages back, so there is
        # no need to filter by self._bot_id here.
        if not self.accept_bot_messages and self._is_bot_message(inbound):
            return

        # Parse content from msg_body
        content_parts, bot_mentioned = await self._parse_msg_body(
            inbound.get("msg_body", []),
            is_group=is_group,
        )
        if not content_parts:
            return

        # Inject quoted-message prefix from cloud_custom_data.quote, if any.
        # Yuanbao only provides desc/sender_* in quote payloads (no url/key,
        # no API to fetch original), so we surface a textual placeholder
        # so the model knows the kind/filename it is replying to.
        #
        # Aligns with wecom / dingtalk: prepend the placeholder to the first
        # TextContent so quote + user input stay as one logical text block.
        # Falls back to a standalone TextContent only when the message has
        # no text part at all (e.g. quoting then sending only an image).
        quote = (inbound.get("cloud_custom_data") or {}).get("quote")
        if isinstance(quote, dict):
            prefix = self._build_quoted_prefix(quote)
            if prefix:
                for i, part in enumerate(content_parts):
                    if isinstance(part, TextContent):
                        content_parts[i] = TextContent(
                            type=ContentType.TEXT,
                            text=f"{prefix}\n{part.text}",
                        )
                        break
                else:
                    content_parts.insert(
                        0,
                        TextContent(type=ContentType.TEXT, text=prefix),
                    )
                logger.info(
                    "yuanbao quoted: type=%s desc_len=%s",
                    quote.get("type"),
                    len(quote.get("desc") or ""),
                )

        # Build meta early so _check_group_mention can inspect it
        meta: Dict[str, Any] = {
            "chat_type": chat_type,
            "group_code": group_code,
            "msg_id": msg_id,
            "raw_sender_id": raw_sender_id,
            "is_group": is_group,
            "user_name": nickname,
        }
        if bot_mentioned:
            meta["bot_mentioned"] = True

        # Group mention policy check (require_mention)
        if not self._check_group_mention(is_group, meta):
            return

        # Build short sender_id and session_id (like feishu/dingtalk)
        sender_display = _sender_display(nickname, raw_sender_id)
        session_id = (
            group_code
            if is_group
            else _short_id(
                raw_sender_id,
            )
        )
        meta["session_id"] = session_id
        meta["sender_id"] = sender_display

        # Store session info for reply routing (short → raw)
        self._session_map[session_id] = {
            "chat_type": chat_type,
            "sender_id": raw_sender_id,
            "group_code": group_code,
            "msg_id": msg_id,
        }
        self._save_session_map_to_disk()

        native = {
            "channel_id": self.channel,
            "sender_id": sender_display,
            "acl_sender_id": raw_sender_id,
            "session_id": session_id,
            "content_parts": content_parts,
            "meta": meta,
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

    def _is_bot_mention(self, content: dict) -> bool:
        """Check if a TIMCustomElem content mentions this bot."""
        data_str = content.get("data", "")
        if not data_str or not isinstance(data_str, str):
            return False
        try:
            custom = json.loads(data_str)
            if custom.get("elem_type") == 1002:
                return custom.get("user_id", "") == self._bot_id
        except (ValueError, TypeError):
            pass
        return False

    def _is_bot_message(self, inbound: dict) -> bool:
        """Return True if the inbound message was sent by a bot.

        Two signals are used in combination:
        1. ``from_account`` starts with ``bot_`` — the platform uses this
           prefix for all custom bot accounts.
        2. Any ``TIMTextElem`` carries a ``data`` field whose JSON payload
           has ``elem_type == 1013`` — the platform attaches this structured
           copy exclusively to bot-originated text messages.
        """
        if inbound.get("from_account", "").startswith("bot_"):
            return True
        for elem in inbound.get("msg_body", []):
            if elem.get("msg_type") != "TIMTextElem":
                continue
            data_str = elem.get("msg_content", {}).get("data", "")
            if not data_str:
                continue
            try:
                parsed = json.loads(data_str)
                if parsed.get("elem_type") == 1013:
                    return True
            except (ValueError, TypeError):
                pass
        return False

    # pylint: disable=unused-argument,too-many-branches
    async def _parse_msg_body(
        self,
        msg_body: List[dict],
        is_group: bool = False,
    ) -> tuple:
        """Parse msg_body elements into content parts.

        Yuanbao only emits four element kinds in practice:
          * ``TIMCustomElem`` (elem_type=1002) -- @mention tag
          * ``TIMTextElem`` -- plain text
          * ``TIMImageElem`` -- image with multi-resolution url array
          * ``TIMFileElem`` -- generic file (incl. audio uploaded as file)

        Audio is routed to :class:`AudioContent` based on the file-name
        suffix so it joins the unified ASR pipeline.  Video / voice elem
        types historically supported by TIM are not pushed by Yuanbao;
        an ``unhandled msg_type`` warning is emitted as a safety net.
        """
        parts: List[Any] = []
        bot_mentioned = False

        for elem in msg_body:
            msg_type = elem.get("msg_type", "")
            content = elem.get("msg_content", {})

            # TIMCustomElem with elem_type 1002 is an @mention tag
            # in group chats — skip it but note the mention.
            if msg_type == "TIMCustomElem":
                bot_mentioned = bot_mentioned or self._is_bot_mention(
                    content,
                )
                continue

            if msg_type == "TIMTextElem":
                text = content.get("text", "").strip()
                if text and self._bot_id:
                    text = text.replace(f"@{self._bot_id}", "").strip()
                if text:
                    parts.append(
                        TextContent(type=ContentType.TEXT, text=text),
                    )

            elif msg_type == "TIMImageElem":
                image_url = ""
                for img_info in content.get("image_info_array", []):
                    if img_info.get("url"):
                        image_url = img_info["url"]
                        break
                if not image_url:
                    image_url = content.get("url", "")
                if image_url:
                    part = await self._download_and_wrap(
                        image_url,
                        filename="image.jpg",
                        kind="image",
                    )
                    if part is not None:
                        parts.append(part)

            elif msg_type == "TIMFileElem":
                file_url = content.get("url", "")
                filename = content.get("file_name", "file") or "file"
                if file_url:
                    kind = self._classify_file(filename)
                    part = await self._download_and_wrap(
                        file_url,
                        filename=filename,
                        kind=kind,
                    )
                    if part is not None:
                        parts.append(part)

            else:
                logger.warning(
                    "yuanbao: unhandled msg_type=%s",
                    msg_type,
                )

        return parts, bot_mentioned

    @staticmethod
    def _classify_file(filename: str) -> str:
        """Classify a TIMFileElem payload as ``audio`` or ``file``.

        Returns ``audio`` when the filename suffix is in :data:`_AUDIO_EXTS`,
        otherwise ``file``.
        """
        if Path(filename).suffix.lower() in _AUDIO_EXTS:
            return "audio"
        return "file"

    async def _download_and_wrap(
        self,
        url: str,
        *,
        filename: str,
        kind: str,
    ) -> Any | None:
        """Resolve + download a media URL and wrap into a Content part.

        On failure, returns a :class:`TextContent` placeholder such as
        ``[image: download failed]`` so the model is still informed and
        no expired CDN URL leaks downstream.
        """
        resolved_url = await self._resolve_media_url(url)
        local_path = await download_media(
            resolved_url,
            self._media_dir,
            filename=filename,
        )
        if not local_path:
            return TextContent(
                type=ContentType.TEXT,
                text=f"[{kind}: download failed]",
            )
        file_uri = Path(local_path).resolve().as_uri()
        if kind == "image":
            return ImageContent(
                type=ContentType.IMAGE,
                image_url=file_uri,
            )
        if kind == "audio":
            return AudioContent(
                type=ContentType.AUDIO,
                data=file_uri,
            )
        return FileContent(
            type=ContentType.FILE,
            file_url=file_uri,
            filename=filename,
        )

    @staticmethod
    def _build_quoted_prefix(quote: dict) -> Optional[str]:
        """Render an inline placeholder for ``cloud_custom_data.quote``.

        Yuanbao only includes ``id`` / ``desc`` / ``sender_*`` in quote
        payloads (no url/key, no API to fetch the original message), so
        this returns a plain bracketed text the model can read.

        The placeholder tells the model:
          * the **kind** of the quoted item (message / image / file / audio)
          * the **filename** when the upstream provides one (type=3)
        so the model can match it against earlier turns in history.
        """
        if not isinstance(quote, dict):
            return None
        qtype_raw = quote.get("type")
        qtype = qtype_raw if isinstance(qtype_raw, int) else 0
        desc = (quote.get("desc") or "").strip()
        label = _QUOTE_TYPE_LABEL.get(qtype, "message")
        # type=3 carries a filename in desc; use the same suffix set as
        # _classify_file so wording stays consistent with non-quoted
        # messages the model has already seen.
        if qtype == 3 and desc and Path(desc).suffix.lower() in _AUDIO_EXTS:
            label = "audio"
        if desc:
            return f"[quoted {label}: {desc}]"
        return f"[quoted {label}]"

    def _prune_seen_ids(self) -> None:
        sorted_ids = sorted(
            self._seen_message_ids.items(),
            key=lambda kv: kv[1],
        )
        remove_count = len(sorted_ids) // 2
        for msg_id, _ in sorted_ids[:remove_count]:
            self._seen_message_ids.pop(msg_id, None)

    # ------------------------------------------------------------------
    # Session map persistence (short_session_id → raw ids)
    # ------------------------------------------------------------------

    def _session_map_path(self) -> Path:
        """Path to persist session mapping for send / cron."""
        if self._workspace_dir:
            return self._workspace_dir / "yuanbao_sessions.json"
        return self._media_dir.parent / "yuanbao_sessions.json"

    def _load_session_map_from_disk(self) -> None:
        """Load session map from disk into memory."""
        path = self._session_map_path()
        if not path.is_file():
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                self._session_map = data
        except Exception:
            logger.debug(
                "yuanbao: load session map from %s failed",
                path,
                exc_info=True,
            )

    def _save_session_map_to_disk(self) -> None:
        """Persist session map to disk."""
        path = self._session_map_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(
                    self._session_map,
                    fh,
                    indent=2,
                    ensure_ascii=False,
                )
        except Exception:
            logger.debug(
                "yuanbao: save session map to %s failed",
                path,
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # Typing indicator (heartbeat-based "Bot is typing…")
    # ------------------------------------------------------------------

    async def _send_typing_heartbeat(
        self,
        session_id: str,
        heartbeat: int,
    ) -> None:
        """Send a single typing heartbeat for the given session."""
        if not self._ws or not self._connected:
            return

        session_info = self._session_map.get(session_id, {})
        if not session_info:
            return

        chat_type = session_info.get("chat_type", "c2c")
        raw_sender_id = session_info.get("sender_id", "")
        group_code = session_info.get("group_code", "")

        result = build_heartbeat_msg(
            from_account=self._bot_id,
            to_account=raw_sender_id,
            heartbeat=heartbeat,
            group_code=group_code if chat_type == "group" else None,
        )
        if result is None:
            return

        raw, _msg_id = result
        try:
            await self._ws.send_bytes(raw)
        except Exception as exc:
            logger.debug("yuanbao: typing heartbeat send failed: %s", exc)

    async def _typing_keepalive_loop(self, session_id: str) -> None:
        """Periodically send HEARTBEAT_RUNNING until cancelled."""
        try:
            while True:
                await self._send_typing_heartbeat(
                    session_id,
                    HEARTBEAT_RUNNING,
                )
                await asyncio.sleep(TYPING_KEEPALIVE_INTERVAL)
        except asyncio.CancelledError:
            pass

    def _start_typing(self, session_id: str) -> None:
        """Start typing indicator for a session (idempotent)."""
        existing = self._typing_tasks.get(session_id)
        if existing and not existing.done():
            return
        self._typing_tasks[session_id] = asyncio.create_task(
            self._typing_keepalive_loop(session_id),
        )

    async def _stop_typing(self, session_id: str) -> None:
        """Cancel typing keepalive and send HEARTBEAT_FINISH."""
        task = self._typing_tasks.pop(session_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
            await self._send_typing_heartbeat(session_id, HEARTBEAT_FINISH)

    async def _before_consume_process(self, request: "AgentRequest") -> None:
        """Start typing indicator before the agent processes the request."""
        meta = getattr(request, "channel_meta", None) or {}
        session_id = meta.get("session_id", "")
        if not session_id:
            return
        self._start_typing(session_id)

    async def _on_process_completed(
        self,
        request: "AgentRequest",
        to_handle: str,
        send_meta: Dict[str, Any],
    ) -> None:
        """Stop typing indicator after all processing is done."""
        session_id = (getattr(request, "channel_meta", None) or {}).get(
            "session_id",
        ) or to_handle
        await self._stop_typing(session_id)

    async def _on_consume_error(
        self,
        request: Any,
        to_handle: str,
        err_text: str,
    ) -> None:
        """Stop typing indicator on error, then send error message."""
        meta = getattr(request, "channel_meta", None) or {}
        session_id = meta.get("session_id") or to_handle
        await self._stop_typing(session_id)
        await super()._on_consume_error(request, to_handle, err_text)

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

        raw, _msg_id = result
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

        raw, _msg_id = result
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

        # Cancel all typing indicator tasks
        for typing_task in self._typing_tasks.values():
            if typing_task and not typing_task.done():
                typing_task.cancel()
        self._typing_tasks.clear()

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
