# -*- coding: utf-8 -*-
"""XiaoYi Channel – dual WebSocket A2A protocol (PING heartbeat)."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from urllib.parse import urlparse

import aiohttp

from agentscope_runtime.engine.schemas.agent_schemas import (
    FileContent,
    ImageContent,
    ContentType,
    TextContent,
    RunStatus,
)
from ....config.config import XiaoYiConfig as XiaoYiChannelConfig
from ....constant import DEFAULT_MEDIA_DIR
from ..base import BaseChannel, OnReplySent, ProcessHandler
from .auth import generate_auth_headers
from .constants import (
    CONNECTION_TIMEOUT,
    DEFAULT_TASK_TIMEOUT_MS,
    HEARTBEAT_INTERVAL,
    MAX_RECONNECT_ATTEMPTS,
    RECONNECT_DELAYS,
    TEXT_CHUNK_LIMIT,
)
from .utils import download_file

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from agentscope_runtime.engine.schemas.agent_schemas import AgentRequest
    from ..base import OutgoingContentPart


@dataclass
class ConnectionState:
    connected: bool = False
    ready: bool = False
    connecting: bool = False
    ws: Optional[aiohttp.ClientWebSocketResponse] = None
    session: Optional[aiohttp.ClientSession] = None
    receive_task: Optional[asyncio.Task] = None
    heartbeat_task: Optional[asyncio.Task] = None
    server_name: str = ""


class HeartbeatManager:
    """WebSocket PING heartbeat – no custom JSON."""

    def __init__(
        self,
        state: ConnectionState,
        interval: float,
        on_timeout: Any,
        server_name: str,
        agent_id: str = "",
    ):
        self.state = state
        self.interval = interval
        self.on_timeout = on_timeout
        self.server_name = server_name
        self.agent_id = agent_id
        self._task: Optional[asyncio.Task] = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        await asyncio.sleep(min(self.interval, 5))
        while (
            self.state.connected and self.state.ws and not self.state.ws.closed
        ):
            try:
                if self.agent_id:
                    await self.state.ws.send_json(
                        {
                            "msgType": "heartbeat",
                            "agentId": self.agent_id,
                            "timestamp": int(time.time() * 1000),
                        },
                    )
                await asyncio.wait_for(self.state.ws.ping(), timeout=15.0)
                logger.debug(
                    "XiaoYi [%s]: Ping reply received",
                    self.server_name,
                )
            except asyncio.TimeoutError:
                logger.error(
                    "XiaoYi [%s]: Ping timed out",
                    self.server_name,
                )
                self.on_timeout()
                break
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(
                    "XiaoYi [%s]: Heartbeat error: %s",
                    self.server_name,
                    e,
                )
                break
            await asyncio.sleep(self.interval)


def _is_ip_address(host: str) -> bool:
    return bool(re.match(r"^(\d{1,3}\.){3}\d{1,3}$", host)) and all(
        0 <= int(p) <= 255 for p in host.split(".")
    )


def _get_ssl_for_url(url: str) -> Any:
    host = urlparse(url).hostname or ""
    return False if _is_ip_address(host) else None


class XiaoYiConnection:
    def __init__(
        self,
        server_name: str,
        ws_url: str,
        ak: str,
        sk: str,
        agent_id: str,
        on_message: Any,
        on_disconnect: Any,
        ssl: Any = None,
    ):
        self.server_name = server_name
        self.ws_url = ws_url
        self.ak, self.sk, self.agent_id = ak, sk, agent_id
        self.on_message = on_message
        self.on_disconnect = on_disconnect
        self.ssl = ssl if ssl is not None else _get_ssl_for_url(ws_url)
        self.state = ConnectionState(server_name=server_name)
        self.heartbeat = HeartbeatManager(
            self.state,
            HEARTBEAT_INTERVAL,
            self._handle_heartbeat_timeout,
            server_name,
            self.agent_id,
        )

    async def connect(self) -> bool:
        if self.state.connected or self.state.connecting:
            return False
        self.state.connecting = True
        headers = generate_auth_headers(self.ak, self.sk, self.agent_id)
        try:
            await self._cleanup()
            self.state.session = aiohttp.ClientSession()
            timeout_ws = aiohttp.ClientWSTimeout(ws_close=CONNECTION_TIMEOUT)
            try:
                if self.ssl is False:
                    logger.warning(
                        "XiaoYi [%s]: SSL disabled for %s",
                        self.server_name,
                        self.ws_url,
                    )
                self.state.ws = await self.state.session.ws_connect(
                    self.ws_url,
                    headers=headers,
                    timeout=timeout_ws,
                    # ssl=self.ssl,
                    ssl=False,
                )
                self.state.connected = True
                self.state.ready = True
                self.state.connecting = False
                logger.info("XiaoYi [%s]: Connected", self.server_name)
                await self._send_init_message()
                self.heartbeat.start()
                self.state.receive_task = asyncio.create_task(
                    self._receive_loop(),
                )
                return True
            except Exception as e:
                logger.error(
                    "XiaoYi [%s]: Connection error: %s",
                    self.server_name,
                    e,
                )
                self.state.connecting = False
                self.state.connected = False
                try:
                    await self._cleanup()
                except Exception:
                    pass
                return False
        except asyncio.CancelledError:
            self.state.connecting = False
            self.state.connected = False
            try:
                await self._cleanup()
            except Exception:
                pass
            raise

    async def disconnect(self) -> None:
        self.state.connected = False
        self.state.ready = False
        await self.heartbeat.stop()
        if self.state.receive_task:
            self.state.receive_task.cancel()
            try:
                await self.state.receive_task
            except asyncio.CancelledError:
                pass
            self.state.receive_task = None
        await self._cleanup()
        logger.info("XiaoYi [%s]: Disconnected", self.server_name)

    async def send_json(self, data: Dict[str, Any]) -> bool:
        if not self.state.ws or self.state.ws.closed:
            return False
        try:
            await self.state.ws.send_json(data)
            return True
        except Exception as e:
            logger.error(
                "XiaoYi [%s]: Send error: %s",
                self.server_name,
                e,
            )
            return False

    async def _send_init_message(self) -> None:
        await self.state.ws.send_json(
            {"msgType": "clawd_bot_init", "agentId": self.agent_id},
        )

    async def _receive_loop(self) -> None:
        if not self.state.ws:
            return
        try:
            async for msg in self.state.ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._handle_text(msg.data)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(
                        "XiaoYi [%s]: WS error: %s",
                        self.server_name,
                        self.state.ws.exception(),
                    )
                    break
                elif msg.type == aiohttp.WSMsgType.CLOSE:
                    logger.info(
                        "XiaoYi [%s]: WS closed",
                        self.server_name,
                    )
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(
                "XiaoYi [%s]: Receive error: %s",
                self.server_name,
                e,
            )
        finally:
            self.state.connected = False
            self.state.ready = False
            self.on_disconnect(self.server_name)

    async def _handle_text(self, data: str) -> None:
        try:
            msg = json.loads(data)
        except json.JSONDecodeError:
            return
        await self.on_message(msg, self.server_name)

    def _handle_heartbeat_timeout(self) -> None:
        logger.error(
            "XiaoYi [%s]: Heartbeat timeout detected",
            self.server_name,
        )
        asyncio.create_task(self.disconnect())

    async def _cleanup(self) -> None:
        ws = self.state.ws
        if ws:
            self.state.ws = None
            try:
                await ws.close()
            except Exception:
                pass
        session = self.state.session
        if session:
            self.state.session = None
            try:
                await session.close()
            except Exception:
                pass

    def transfer_callbacks(self, on_message, on_disconnect) -> None:
        """将连接的回调重新绑定到新的 Channel 实例上。"""
        self.on_message = on_message
        self.on_disconnect = on_disconnect


_active_connections: Dict[str, "XiaoYiChannel"] = {}
_active_connections_lock = asyncio.Lock()


class XiaoYiChannel(BaseChannel):
    channel = "xiaoyi"
    uses_manager_queue = True

    def __init__(
        self,
        process: ProcessHandler,
        enabled: bool,
        ak: str,
        sk: str,
        agent_id: str,
        ws_url: str,
        ws_url_backup: str = "",
        task_timeout_ms: int = DEFAULT_TASK_TIMEOUT_MS,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
        bot_prefix: str = "",
        media_dir: str = "",
        workspace_dir: Path | None = None,
    ):
        super().__init__(
            process,
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            filter_thinking=filter_thinking,
        )
        self.enabled, self.ak, self.sk, self.agent_id = (
            enabled,
            ak,
            sk,
            agent_id,
        )
        self.ws_url = ws_url
        self.ws_url_backup = ws_url_backup or _default_backup_url(ws_url)
        self.task_timeout_ms = task_timeout_ms
        self.bot_prefix = bot_prefix
        self._workspace_dir = (
            Path(workspace_dir).expanduser() if workspace_dir else None
        )
        if not media_dir and self._workspace_dir:
            self._media_dir = self._workspace_dir / "media"
        elif media_dir:
            self._media_dir = Path(media_dir).expanduser()
        else:
            self._media_dir = DEFAULT_MEDIA_DIR / "xiaoyi"
        self._media_dir.mkdir(parents=True, exist_ok=True)

        self._conn1: Optional[XiaoYiConnection] = None
        self._conn2: Optional[XiaoYiConnection] = None
        self._connected = False
        self._reconnect_attempts = 0
        self._stopping = False
        self._session_server_map: Dict[str, str] = {}
        self._session_task_map: Dict[str, str] = {}
        self._reconnect_task: Optional[asyncio.Task] = None
        self._message_buffer: List[Dict[str, Any]] = []
        self._buffer_lock = asyncio.Lock()
        self._drain_task: Optional[asyncio.Task] = None

    @classmethod
    def from_env(
        cls,
        process: ProcessHandler,
        on_reply_sent: OnReplySent = None,
    ) -> "XiaoYiChannel":
        import os

        return cls(
            process=process,
            enabled=os.getenv("XIAOYI_CHANNEL_ENABLED", "0") == "1",
            ak=os.getenv("XIAOYI_AK", ""),
            sk=os.getenv("XIAOYI_SK", ""),
            agent_id=os.getenv("XIAOYI_AGENT_ID", ""),
            ws_url=os.getenv(
                "XIAOYI_WS_URL",
                "wss://hag.cloud.huawei.com/openclaw/v1/ws/link",
            ),
            ws_url_backup=os.getenv("XIAOYI_WS_URL_BACKUP", ""),
            on_reply_sent=on_reply_sent,
            media_dir=os.getenv("XIAOYI_MEDIA_DIR", ""),
        )

    @classmethod
    def from_config(
        cls,
        process: ProcessHandler,
        config: XiaoYiChannelConfig,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
        workspace_dir: Path | None = None,
    ) -> "XiaoYiChannel":
        if isinstance(config, dict):
            return cls(
                process=process,
                enabled=config.get("enabled", False),
                ak=config.get("ak", ""),
                sk=config.get("sk", ""),
                agent_id=config.get("agent_id", ""),
                ws_url=config.get(
                    "ws_url",
                    "wss://hag.cloud.huawei.com/openclaw/v1/ws/link",
                ),
                ws_url_backup=config.get("ws_url_backup", ""),
                task_timeout_ms=config.get(
                    "task_timeout_ms",
                    DEFAULT_TASK_TIMEOUT_MS,
                ),
                on_reply_sent=on_reply_sent,
                show_tool_details=show_tool_details,
                filter_tool_messages=filter_tool_messages,
                filter_thinking=filter_thinking,
                bot_prefix=config.get("bot_prefix", ""),
                media_dir=config.get("media_dir", ""),
                workspace_dir=workspace_dir,
            )
        return cls(
            process=process,
            enabled=config.enabled,
            ak=config.ak,
            sk=config.sk,
            agent_id=config.agent_id,
            ws_url=config.ws_url,
            ws_url_backup=getattr(config, "ws_url_backup", ""),
            task_timeout_ms=config.task_timeout_ms,
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            filter_thinking=filter_thinking,
            bot_prefix=config.bot_prefix,
            media_dir=getattr(config, "media_dir", ""),
            workspace_dir=workspace_dir,
        )

    def _validate_config(self) -> None:
        if not self.ak or not self.sk or not self.agent_id:
            raise ValueError("XiaoYi AK/SK/Agent ID required")

    async def health_check(self) -> Dict[str, Any]:
        if not self.enabled:
            return {"channel": self.channel, "status": "disabled"}
        c1 = self._conn1 and self._conn1.state.connected
        c2 = self._conn2 and self._conn2.state.connected
        if c1 or c2:
            return {
                "channel": self.channel,
                "status": "healthy",
                "detail": (
                    f"server1={'ok' if c1 else 'down'}, "
                    f"server2={'ok' if c2 else 'down'}"
                ),
            }
        return {"channel": self.channel, "status": "unhealthy"}

    async def _ensure_stopped(self) -> None:
        """彻底停止本实例的所有异步活动，不泄漏任何资源。"""
        self._stopping = True
        self._connected = False
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
            self._reconnect_task = None
        if self._drain_task and not self._drain_task.done():
            self._drain_task.cancel()
            try:
                await self._drain_task
            except asyncio.CancelledError:
                pass
            self._drain_task = None
        for conn in (self._conn1, self._conn2):
            if conn:
                await conn.disconnect()
        self._conn1 = None
        self._conn2 = None

    # pylint: disable=protected-access
    async def start(self) -> None:
        if not self.enabled:
            return
        self._validate_config()
        global _active_connections
        async with _active_connections_lock:
            existing = _active_connections.get(self.agent_id)
            if existing is not None and existing is not self:
                if existing._connected:
                    existing._render_style.filter_tool_messages = (
                        self._render_style.filter_tool_messages
                    )
                    existing._render_style.filter_thinking = (
                        self._render_style.filter_thinking
                    )
                    existing._render_style.show_tool_details = (
                        self._render_style.show_tool_details
                    )
                    self._session_task_map = dict(
                        existing._session_task_map,
                    )
                    self._session_server_map = dict(
                        existing._session_server_map,
                    )
                    self._connected = existing._connected
                    self._conn1 = existing._conn1
                    self._conn2 = existing._conn2
                    if self._conn1:
                        self._conn1.transfer_callbacks(
                            self._handle_incoming_message,
                            self._handle_disconnect,
                        )
                    if self._conn2:
                        self._conn2.transfer_callbacks(
                            self._handle_incoming_message,
                            self._handle_disconnect,
                        )
                    _active_connections[self.agent_id] = self
                    existing._conn1 = None
                    existing._conn2 = None
                    await existing._ensure_stopped()
                    if self._drain_task and not self._drain_task.done():
                        self._drain_task.cancel()
                    self._drain_task = asyncio.create_task(
                        self._drain_buffer(),
                    )
                    return
                _active_connections.pop(self.agent_id, None)
                await existing._ensure_stopped()
            _active_connections[self.agent_id] = self
        await self._start_connections()

    async def _start_connections(self) -> None:
        for conn in (self._conn1, self._conn2):
            if conn:
                await conn.disconnect()
        self._conn1 = XiaoYiConnection(
            "server1",
            self.ws_url,
            self.ak,
            self.sk,
            self.agent_id,
            self._handle_incoming_message,
            self._handle_disconnect,
        )
        self._conn2 = XiaoYiConnection(
            "server2",
            self.ws_url_backup,
            self.ak,
            self.sk,
            self.agent_id,
            self._handle_incoming_message,
            self._handle_disconnect,
        )
        r1, r2 = await asyncio.gather(
            self._safe_connect(self._conn1),
            self._safe_connect(self._conn2),
            return_exceptions=True,
        )
        if r1 is True or r2 is True:
            self._connected = True
            self._reconnect_attempts = 0
            if self._drain_task and not self._drain_task.done():
                self._drain_task.cancel()
            self._drain_task = asyncio.create_task(self._drain_buffer())
        else:
            self._connected = False
            self._schedule_reconnect()

    async def _safe_connect(self, conn: XiaoYiConnection) -> bool:
        return await conn.connect()

    async def stop(self) -> None:
        await self._ensure_stopped()
        await self._unregister_connection()

    # pylint: disable=protected-access
    def _copy_state_from(self, other: "XiaoYiChannel") -> None:
        """已废弃：逻辑内联到 start() 中。保留以避免外部调用报错。"""

    def _mark_inactive(self) -> None:
        """已废弃：使用 _ensure_stopped() 替代。保留以避免外部调用报错。"""

    async def _handle_incoming_message(
        self,
        msg: Dict[str, Any],
        server_name: str,
    ) -> None:
        if self._stopping:
            return
        try:
            if msg.get("agentId") and msg["agentId"] != self.agent_id:
                return
            session_id = msg.get("params", {}).get(
                "sessionId",
            ) or msg.get("sessionId")
            if session_id:
                self._session_server_map[session_id] = server_name
            method, action = msg.get("method") or "", msg.get("action") or ""
            if method == "clearContext" or action == "clear":
                await self._handle_clear_context(msg)
            elif method == "tasks/cancel" or action == "tasks/cancel":
                await self._handle_tasks_cancel(msg)
            elif self._is_valid_a2a(msg):
                await self._handle_a2a_request(msg)
        except Exception as e:
            logger.error(
                "XiaoYi: Error handling msg: %s",
                e,
                exc_info=True,
            )
            params = msg.get("params", {}) if isinstance(msg, dict) else {}
            sid = (
                params.get("sessionId")
                or (msg.get("sessionId") if isinstance(msg, dict) else None)
                or ""
            )
            rid = (
                params.get("id")
                or (msg.get("id") if isinstance(msg, dict) else None)
                or ""
            )
            if sid and rid and not self._stopping:
                try:
                    await self._send_error_response(
                        sid,
                        rid,
                        "99911114",
                        f"Internal error: {e}",
                    )
                except Exception:
                    pass

    def _is_valid_a2a(self, msg: Dict[str, Any]) -> bool:
        if (
            not isinstance(msg, dict)
            or msg.get("method") != "message/stream"
            or msg.get("jsonrpc") != "2.0"
        ):
            return False
        params = msg.get("params")
        if not isinstance(params, dict) or not isinstance(
            params.get("id"),
            str,
        ):
            return False
        sid = params.get("sessionId") or msg.get("sessionId")
        if not isinstance(sid, str) or not sid:
            return False
        body = params.get("message")
        return (
            isinstance(body, dict)
            and isinstance(body.get("role"), str)
            and isinstance(body.get("parts"), list)
        )

    async def _handle_a2a_request(self, msg: Dict[str, Any]) -> None:
        params = msg.get("params", {})
        session_id = params.get("sessionId") or msg.get("sessionId")
        task_id = params.get("id") or msg.get("id")
        if not session_id:
            return
        self._session_task_map[session_id] = task_id
        self._session_task_map[f"xiaoyi:{session_id}"] = task_id
        text_parts, content_parts = [], []
        body = params.get("message") or {}
        for part in body.get("parts", []):
            if part.get("kind") == "text" and part.get("text"):
                text_parts.append(part["text"])
            elif part.get("kind") == "file":
                await self._process_file_part(
                    part,
                    text_parts,
                    content_parts,
                )
        if text_parts:
            content_parts.insert(
                0,
                TextContent(
                    type=ContentType.TEXT,
                    text=" ".join(text_parts).strip(),
                ),
            )
        if not content_parts:
            return
        await self._safe_enqueue(
            {
                "channel_id": self.channel,
                "sender_id": session_id,
                "content_parts": content_parts,
                "meta": {
                    "session_id": session_id,
                    "task_id": task_id,
                    "message_id": msg.get("id"),
                },
            },
        )

    async def _safe_enqueue(self, native):
        if self._enqueue:
            self._enqueue(native)
        else:
            async with self._buffer_lock:
                self._message_buffer.append(native)

    async def _drain_buffer(self):
        for _ in range(120):
            if self._enqueue:
                break
            await asyncio.sleep(0.5)
        if not self._enqueue:
            return
        async with self._buffer_lock:
            buf, self._message_buffer = self._message_buffer[:], []
        for m in buf:
            self._enqueue(m)

    async def _process_file_part(self, part, text_parts, content_parts):
        info = part.get("file", {})
        url, name, mime = (
            info.get("uri", ""),
            info.get("name", "file"),
            info.get("mimeType", ""),
        )
        if not url:
            return
        local = await download_file(
            url=url,
            media_dir=self._media_dir,
            filename=name,
        )
        if not local:
            text_parts.append(f"[{name}: download failed]")
        elif mime.startswith("image/"):
            content_parts.append(
                ImageContent(type=ContentType.IMAGE, image_url=local),
            )
        else:
            content_parts.append(
                FileContent(
                    type=ContentType.FILE,
                    file_url=local,
                    filename=name,
                ),
            )

    async def _send_simple_response(
        self,
        sid: str,
        rid: str,
        result: dict,
    ) -> None:
        await self._send_to_session_server(
            sid,
            self._make_response(
                sid,
                rid,
                json.dumps(
                    {"jsonrpc": "2.0", "id": rid, "result": result},
                ),
            ),
        )
        self._session_task_map.pop(sid, None)
        self._session_server_map.pop(sid, None)

    async def _send_error_response(
        self,
        sid: str,
        rid: str,
        code: str,
        message: str,
    ) -> None:
        await self._send_to_session_server(
            sid,
            self._make_response(
                sid,
                rid,
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": rid,
                        "error": {"code": code, "message": message},
                    },
                ),
            ),
        )

    async def _handle_clear_context(self, msg):
        await self._send_simple_response(
            msg.get("sessionId", ""),
            msg.get("id", ""),
            {"status": {"state": "cleared"}},
        )

    async def _handle_tasks_cancel(self, msg):
        rid = msg.get("id", "")
        await self._send_simple_response(
            msg.get("sessionId", ""),
            rid,
            {"id": rid, "status": {"state": "canceled"}},
        )

    def _make_response(self, sid, tid, detail):
        return {
            "msgType": "agent_response",
            "agentId": self.agent_id,
            "sessionId": sid,
            "taskId": tid,
            "msgDetail": detail,
        }

    async def _send_to_session_server(
        self,
        sid: str,
        msg: Dict[str, Any],
    ) -> None:
        srv = self._session_server_map.get(sid, "server1")
        if srv == "server2" and self._conn2 and self._conn2.state.connected:
            await self._conn2.send_json(msg)
        elif self._conn1 and self._conn1.state.connected:
            await self._conn1.send_json(msg)

    def _build_artifact_msg(
        self,
        sid,
        tid,
        mid,
        parts,
        append=True,
        final=False,
    ):
        detail = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": mid,
                "result": {
                    "taskId": tid,
                    "kind": "artifact-update",
                    "append": append,
                    "lastChunk": True,
                    "final": final,
                    "artifact": {
                        "artifactId": uuid.uuid4().hex[:16],
                        "parts": parts,
                    },
                },
            },
        )
        return self._make_response(sid, tid, detail)

    async def send(self, to_handle, text, meta=None):
        if not self.enabled or not self._connected:
            return
        meta = meta or {}
        sid = meta.get("session_id") or to_handle
        tid = meta.get("task_id") or self._session_task_map.get(sid)
        if not tid or not text.strip():
            return
        mid = meta.get("message_id", str(uuid.uuid4()))
        for chunk in self._chunk_text(text):
            await self._send_to_session_server(
                sid,
                self._build_artifact_msg(
                    sid,
                    tid,
                    mid,
                    [{"kind": "text", "text": chunk}],
                ),
            )

    def _chunk_text(self, text):
        if len(text) <= TEXT_CHUNK_LIMIT:
            return [text]
        chunks = []
        for line in text.split("\n"):
            while len(line) > TEXT_CHUNK_LIMIT:
                chunks.append(line[:TEXT_CHUNK_LIMIT])
                line = line[TEXT_CHUNK_LIMIT:]
            if line:
                if chunks and len(chunks[-1]) + len(line) < TEXT_CHUNK_LIMIT:
                    chunks[-1] += "\n" + line
                else:
                    chunks.append(line)
        return chunks

    async def on_event_message_completed(
        self,
        request,
        to_handle,
        event,
        send_meta,
    ):
        parts = self._extract_xiaoyi_parts(event)
        if parts:
            await self.send_xiaoyi_parts(to_handle, parts, send_meta)

    async def send_xiaoyi_parts(self, to_handle, parts, meta=None):
        if not self.enabled or not self._connected:
            return
        meta = meta or {}
        sid = meta.get("session_id") or to_handle
        tid = meta.get("task_id") or self._session_task_map.get(sid)
        if not tid:
            return
        mid = meta.get("message_id", str(uuid.uuid4()))
        for p in parts:
            kind = p.get("kind", "text")
            content = p.get("text") or p.get("reasoningText", "")
            for chunk in self._chunk_text(content):
                part = (
                    {"kind": "reasoningText", "reasoningText": chunk}
                    if kind == "reasoningText"
                    else {"kind": "text", "text": chunk}
                )
                await self._send_to_session_server(
                    sid,
                    self._build_artifact_msg(sid, tid, mid, [part]),
                )

    # pylint: disable=too-many-branches,too-many-nested-blocks
    def _extract_xiaoyi_parts(self, message):
        from agentscope_runtime.engine.schemas.agent_schemas import (
            MessageType,
        )

        msg_type = getattr(message, "type", None)
        content = getattr(message, "content", None) or []
        if msg_type == MessageType.REASONING:
            if self._render_style.filter_thinking:
                return []
            return [
                {"kind": "reasoningText", "reasoningText": c.text + "\n"}
                for c in content
                if getattr(c, "text", None)
            ]
        parts = []
        for c in content:
            ctype = getattr(c, "type", None)
            if ctype == ContentType.DATA:
                data = getattr(c, "data", None)
                if (
                    isinstance(data, dict)
                    and not self._render_style.filter_thinking
                ):
                    for blk in data.get("blocks", []):
                        if (
                            isinstance(blk, dict)
                            and blk.get("type") == "thinking"
                        ):
                            t = blk.get("thinking", "")
                            if t:
                                parts.append(
                                    {
                                        "kind": "reasoningText",
                                        "reasoningText": t + "\n",
                                    },
                                )
            elif ctype == ContentType.TEXT and getattr(c, "text", None):
                parts.append({"kind": "text", "text": c.text})
            elif ctype == ContentType.REFUSAL and getattr(
                c,
                "refusal",
                None,
            ):
                parts.append({"kind": "text", "text": c.refusal})

        if self._render_style.filter_tool_messages and msg_type in (
            MessageType.FUNCTION_CALL,
            MessageType.PLUGIN_CALL,
            MessageType.MCP_TOOL_CALL,
            MessageType.FUNCTION_CALL_OUTPUT,
            MessageType.PLUGIN_CALL_OUTPUT,
            MessageType.MCP_TOOL_CALL_OUTPUT,
        ):
            return []
        if msg_type in (
            MessageType.FUNCTION_CALL,
            MessageType.PLUGIN_CALL,
            MessageType.MCP_TOOL_CALL,
        ):
            return self._fmt_tool_calls(content)
        if msg_type in (
            MessageType.FUNCTION_CALL_OUTPUT,
            MessageType.PLUGIN_CALL_OUTPUT,
            MessageType.MCP_TOOL_CALL_OUTPUT,
        ):
            return self._fmt_tool_outputs(content)
        if not parts:
            for rp in self._renderer.message_to_parts(message):
                if getattr(rp, "type", None) == ContentType.TEXT and getattr(
                    rp,
                    "text",
                    None,
                ):
                    parts.append({"kind": "text", "text": rp.text})
        return parts

    def _fmt_tool_calls(self, content):
        parts = []
        for c in content:
            if getattr(c, "type", None) != ContentType.DATA:
                continue
            data = getattr(c, "data", None)
            if isinstance(data, dict):
                name, args = data.get("name", "tool"), data.get(
                    "arguments",
                    "{}",
                )
                parts.append(
                    {
                        "kind": "text",
                        "text": f"\n\n🔧 **{name}**\n```\n{args}\n```\n",
                    },
                )
        return parts

    def _fmt_tool_outputs(self, content):
        parts = []
        for c in content:
            if getattr(c, "type", None) != ContentType.DATA:
                continue
            data = getattr(c, "data", None)
            if isinstance(data, dict):
                name, output = data.get("name", "tool"), data.get(
                    "output",
                    "",
                )
                try:
                    parsed = (
                        json.loads(output)
                        if isinstance(output, str)
                        else output
                    )
                    if isinstance(parsed, list):
                        out = "\n".join(
                            i.get("text", "")
                            for i in parsed
                            if isinstance(i, dict) and i.get("type") == "text"
                        )
                    elif isinstance(parsed, dict):
                        out = json.dumps(
                            parsed,
                            ensure_ascii=False,
                            indent=2,
                        )
                    else:
                        out = str(parsed)
                except Exception:
                    out = str(output) if output else ""
                out = out[:500] + "..." if len(out) > 500 else out
                parts.append(
                    {
                        "kind": "text",
                        "text": (f"\n\n✅ **{name}**\n```\n{out}\n```\n"),
                    },
                )
        return parts

    async def send_final_message(self, session_id, task_id, message_id):
        if not self.enabled or not self._connected:
            return
        status = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": message_id,
                "result": {
                    "taskId": task_id,
                    "kind": "status-update",
                    "final": False,
                    "status": {
                        "message": {
                            "role": "agent",
                            "parts": [{"kind": "text", "text": ""}],
                        },
                        "state": "completed",
                    },
                },
            },
        )
        await self._send_to_session_server(
            session_id,
            self._make_response(session_id, task_id, status),
        )
        await self._send_to_session_server(
            session_id,
            self._build_artifact_msg(
                session_id,
                task_id,
                message_id,
                [{"kind": "text", "text": ""}],
                append=False,
                final=True,
            ),
        )

    async def _on_process_completed(self, request, to_handle, send_meta):
        session_id = send_meta.get("session_id") or to_handle
        task_id = (
            send_meta.get("task_id")
            or self._session_task_map.get(session_id)
            or self._session_task_map.get(to_handle)
        )
        message_id = send_meta.get("message_id") or str(uuid.uuid4())
        if task_id and session_id:
            await self.send_final_message(session_id, task_id, message_id)
            self._session_task_map.pop(session_id, None)
            self._session_task_map.pop(f"xiaoyi:{session_id}", None)

    async def _run_process_loop(self, request, to_handle, send_meta):
        last = None
        try:
            async for evt in self._process(request):
                if self._stopping:
                    break
                obj = getattr(evt, "object", None)
                if (
                    obj == "message"
                    and getattr(evt, "status", None) == RunStatus.Completed
                ):
                    await self.on_event_message_completed(
                        request,
                        to_handle,
                        evt,
                        send_meta,
                    )
                elif obj == "response":
                    last = evt
                    await self.on_event_response(request, evt)
            err = self._get_response_error_message(last)
            if err:
                await self._on_consume_error(
                    request,
                    to_handle,
                    f"Error: {err}",
                )
            if self._on_reply_sent:
                args = self.get_on_reply_sent_args(request, to_handle)
                self._on_reply_sent(self.channel, *args)
        except Exception:
            logger.exception("XiaoYi channel consume_one failed")
            await self._on_consume_error(
                request,
                to_handle,
                "An error occurred.",
            )

    def _handle_disconnect(self, server_name: str):
        if self._stopping:
            return
        logger.warning("XiaoYi: %s disconnected", server_name)
        for sid, srv in list(self._session_server_map.items()):
            if srv == server_name:
                self._session_server_map.pop(sid, None)
        if (
            not self._stopping
            and not (self._conn1 and self._conn1.state.connected)
            and not (self._conn2 and self._conn2.state.connected)
        ):
            self._connected = False
            self._schedule_reconnect()

    def _schedule_reconnect(self):
        if (
            self._stopping
            or self._reconnect_attempts >= MAX_RECONNECT_ATTEMPTS
        ):
            return
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
        delay = RECONNECT_DELAYS[
            min(self._reconnect_attempts, len(RECONNECT_DELAYS) - 1)
        ]
        self._reconnect_attempts += 1
        logger.info(
            "Reconnecting in %ds (attempt %d)",
            delay,
            self._reconnect_attempts,
        )
        self._reconnect_task = asyncio.create_task(
            self._reconnect_after(delay),
        )

    async def _reconnect_after(self, delay: float) -> None:
        await asyncio.sleep(delay)
        if self._stopping or self._connected:
            return
        await self._start_connections()

    async def _wait_and_register_connection(self):
        global _active_connections
        async with _active_connections_lock:
            _active_connections.pop(self.agent_id, None)
            _active_connections[self.agent_id] = self

    async def _unregister_connection(self):
        global _active_connections
        async with _active_connections_lock:
            stored = _active_connections.get(self.agent_id)
            if stored is self:
                _active_connections.pop(self.agent_id, None)

    def resolve_session_id(self, sender_id: str, channel_meta=None) -> str:
        if channel_meta and channel_meta.get("session_id"):
            return f"xiaoyi:{channel_meta['session_id']}"
        return f"xiaoyi:{sender_id}"

    def get_to_handle_from_request(self, request) -> str:
        meta = getattr(request, "channel_meta", None) or {}
        return str(
            meta.get("session_id") or getattr(request, "user_id", ""),
        )

    def build_agent_request_from_native(self, native_payload):
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

    def to_handle_from_target(self, *, user_id, session_id):
        if session_id.startswith("xiaoyi:"):
            return session_id.split("xiaoyi:")[-1]
        return user_id

    async def send_media(
        self,
        to_handle,
        part: "OutgoingContentPart",
        meta=None,
    ):
        if not self._connected:
            return
        meta = meta or {}
        sid = meta.get("session_id") or to_handle
        tid = meta.get("task_id") or self._session_task_map.get(sid)
        if not tid:
            return
        ptype = getattr(part, "type", None)
        if ptype == ContentType.IMAGE:
            p = {
                "kind": "file",
                "file": {
                    "name": "image",
                    "mimeType": "image/png",
                    "uri": getattr(part, "image_url", ""),
                },
            }
        elif ptype == ContentType.FILE:
            p = {
                "kind": "file",
                "file": {
                    "name": getattr(part, "filename", "file"),
                    "mimeType": "application/octet-stream",
                    "uri": getattr(part, "file_url", ""),
                },
            }
        else:
            return
        await self._send_to_session_server(
            sid,
            self._build_artifact_msg(
                sid,
                tid,
                str(uuid.uuid4()),
                [p],
                append=False,
                final=True,
            ),
        )


def _default_backup_url(primary: str) -> str:
    if "hag.cloud.huawei.com" in primary:
        return primary.replace("hag.cloud.huawei.com", "116.63.174.231")
    return "wss://116.63.174.231/openclaw/v1/ws/link"
