# -*- coding: utf-8 -*-
"""XiaoYi Channel implementation.

XiaoYi uses A2A (Agent-to-Agent) protocol over WebSocket.

"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

import aiohttp

from agentscope_runtime.engine.schemas.agent_schemas import (
    FileContent,
    ImageContent,
    ContentType,
    TextContent,
)

from ....config.config import XiaoYiConfig as XiaoYiChannelConfig
from ....constant import DEFAULT_MEDIA_DIR
from ..base import (
    BaseChannel,
    OnReplySent,
    OutgoingContentPart,
    ProcessHandler,
)
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


# =============================================================================
# Data Structures
# =============================================================================


@dataclass
class ConnectionState:
    """State for a single WebSocket connection."""

    connected: bool = False
    ready: bool = False
    connecting: bool = False
    last_pong_time: float = 0.0
    ws: Optional[aiohttp.ClientWebSocketResponse] = None
    session: Optional[aiohttp.ClientSession] = None
    receive_task: Optional[asyncio.Task] = None
    heartbeat_task: Optional[asyncio.Task] = None
    server_name: str = ""


# =============================================================================
# Heartbeat Manager
# =============================================================================


class HeartbeatManager:
    """Heartbeat manager with timeout detection.

    Fixes the issue where QwenPaw's simple heartbeat loop cannot detect
    zombie connections (server disconnects without sending close frame).
    """

    def __init__(
        self,
        connection_state: ConnectionState,
        interval: float,
        timeout: float,
        on_timeout: callable,
        server_name: str,
        agent_id: str,
    ):
        self.state = connection_state
        self.interval = interval
        self.timeout = timeout
        self.on_timeout = on_timeout
        self.server_name = server_name
        self.agent_id = agent_id
        self._task: Optional[asyncio.Task] = None
        self._last_pong_time: float = time.time()
        self._pending_disconnect_task: Optional[asyncio.Task] = None

    def start(self) -> None:
        """Start heartbeat loop."""
        self._last_pong_time = time.time()
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        """Stop heartbeat loop."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def on_pong_received(self) -> None:
        """Call when pong/heartbeat response received."""
        self._last_pong_time = time.time()

    async def _loop(self) -> None:
        """Heartbeat loop with timeout detection."""
        # Wait a bit before first heartbeat to let connection stabilize
        await asyncio.sleep(min(self.interval, 5))

        while (
            self.state.connected and self.state.ws and not self.state.ws.closed
        ):
            try:
                # Check for heartbeat timeout
                elapsed = time.time() - self._last_pong_time
                if elapsed > self.timeout:
                    logger.error(
                        f"XiaoYi [{self.server_name}]: Heartbeat timeout "
                        f"({elapsed:.1f}s > {self.timeout}s), forcing reconnect",
                    )
                    self.on_timeout()
                    break

                # Send heartbeat
                if self.state.ws and not self.state.ws.closed:
                    heartbeat_msg = {
                        "msgType": "heartbeat",
                        "agentId": self.agent_id,
                        "timestamp": int(time.time() * 1000),
                    }
                    await self.state.ws.send_json(heartbeat_msg)
                    logger.debug(
                        f"XiaoYi [{self.server_name}]: Heartbeat sent",
                    )

                await asyncio.sleep(self.interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(
                    f"XiaoYi [{self.server_name}]: Heartbeat error: {e}",
                )
                break

        logger.debug(f"XiaoYi [{self.server_name}]: Heartbeat loop ended")


# =============================================================================
# WebSocket Connection Manager
# =============================================================================


class XiaoYiConnection:
    """Manages a single WebSocket connection to a XiaoYi server.

    This class encapsulates the lifecycle of one WebSocket connection,
    including connect, receive, heartbeat, and reconnect logic.
    """

    def __init__(
        self,
        server_name: str,
        ws_url: str,
        ak: str,
        sk: str,
        agent_id: str,
        on_message: callable,
        on_disconnect: callable,
    ):
        self.server_name = server_name
        self.ws_url = ws_url
        self.ak = ak
        self.sk = sk
        self.agent_id = agent_id
        self.on_message = on_message
        self.on_disconnect = on_disconnect

        self.state = ConnectionState(server_name=server_name)
        self.heartbeat = HeartbeatManager(
            connection_state=self.state,
            interval=HEARTBEAT_INTERVAL,
            timeout=HEARTBEAT_INTERVAL * 6,  # 6x interval = 180s (3 min)
            on_timeout=self._handle_heartbeat_timeout,
            server_name=server_name,
            agent_id=self.agent_id,
        )

    async def connect(self) -> bool:
        """Establish WebSocket connection. Returns True on success."""
        if self.state.connected or self.state.connecting:
            return False

        self.state.connecting = True
        headers = generate_auth_headers(self.ak, self.sk, self.agent_id)

        # Clean up any existing session
        await self._cleanup()

        self.state.session = aiohttp.ClientSession()
        ws_timeout = aiohttp.ClientWSTimeout(ws_close=CONNECTION_TIMEOUT)

        try:
            logger.info(
                f"XiaoYi [{self.server_name}]: Connecting to {self.ws_url}...",
            )
            self.state.ws = await self.state.session.ws_connect(
                self.ws_url,
                headers=headers,
                timeout=ws_timeout,
                ssl=False,
            )

            self.state.connected = True
            self.state.ready = True
            self.state.connecting = False

            logger.info(
                f"XiaoYi [{self.server_name}]: WebSocket connected",
            )

            # Send init message
            await self._send_init_message()

            # Start heartbeat
            self.heartbeat.start()

            # Start receive loop
            self.state.receive_task = asyncio.create_task(
                self._receive_loop(),
            )

            return True

        except Exception as e:
            logger.error(
                f"XiaoYi [{self.server_name}]: Connection error: {e}",
            )
            self.state.connecting = False
            self.state.connected = False
            await self._cleanup()
            return False

    async def disconnect(self) -> None:
        """Gracefully disconnect."""
        self.state.connected = False
        self.state.ready = False

        # Stop heartbeat
        await self.heartbeat.stop()

        # Cancel receive task
        if self.state.receive_task:
            self.state.receive_task.cancel()
            try:
                await self.state.receive_task
            except asyncio.CancelledError:
                pass
            self.state.receive_task = None

        # Close WebSocket
        await self._cleanup()

        logger.info(
            f"XiaoYi [{self.server_name}]: Disconnected",
        )

    async def send_json(self, data: Dict[str, Any]) -> bool:
        """Send JSON message. Returns True on success."""
        if not self.state.ws or self.state.ws.closed:
            return False
        try:
            await self.state.ws.send_json(data)
            return True
        except Exception as e:
            logger.error(
                f"XiaoYi [{self.server_name}]: Send error: {e}",
            )
            return False

    async def _send_init_message(self) -> None:
        """Send init message to server."""
        init_msg = {
            "msgType": "clawd_bot_init",
            "agentId": self.agent_id,
        }
        try:
            await self.state.ws.send_json(init_msg)
            logger.debug(
                f"XiaoYi [{self.server_name}]: Init message sent",
            )
        except Exception as e:
            logger.error(
                f"XiaoYi [{self.server_name}]: Failed to send init: {e}",
            )

    async def _receive_loop(self) -> None:
        """Receive and process messages from WebSocket."""
        if not self.state.ws:
            return

        try:
            async for msg in self.state.ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._handle_text_message(msg.data)
                elif msg.type == aiohttp.WSMsgType.BINARY:
                    logger.debug(
                        f"XiaoYi [{self.server_name}]: Binary msg received",
                    )
                elif msg.type == aiohttp.WSMsgType.PING:
                    logger.debug(
                        f"XiaoYi [{self.server_name}]: Ping received",
                    )
                    if self.state.ws:
                        await self.state.ws.pong()
                elif msg.type == aiohttp.WSMsgType.PONG:
                    self.heartbeat.on_pong_received()
                    logger.debug(
                        f"XiaoYi [{self.server_name}]: Pong received",
                    )
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(
                        f"XiaoYi [{self.server_name}]: WS error: "
                        f"{self.state.ws.exception()}",
                    )
                    break
                elif msg.type == aiohttp.WSMsgType.CLOSE:
                    logger.info(
                        f"XiaoYi [{self.server_name}]: WS closed "
                        f"(code={msg.data}, reason={msg.extra})",
                    )
                    break
                elif msg.type == aiohttp.WSMsgType.CLOSING:
                    logger.info(
                        f"XiaoYi [{self.server_name}]: WS closing...",
                    )
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(
                f"XiaoYi [{self.server_name}]: Receive loop error: {e}",
            )
        finally:
            self.state.connected = False
            self.state.ready = False
            self.on_disconnect(self.server_name)

    async def _handle_text_message(self, data: str) -> None:
        """Handle incoming text message."""
        try:
            message = json.loads(data)
        except json.JSONDecodeError:
            logger.error(
                f"XiaoYi [{self.server_name}]: Invalid JSON received",
            )
            return

        # Log at appropriate level based on message type
        msg_type = message.get("msgType", "")
        if msg_type == "heartbeat":
            self.heartbeat.on_pong_received()
            logger.debug(
                f"XiaoYi [{self.server_name}]: Heartbeat response received",
            )
            return

        logger.debug(
            f"XiaoYi [{self.server_name}]: Received: "
            f"{json.dumps(message, indent=2, ensure_ascii=False)[:500]}",
        )

        # Forward to channel handler with server attribution
        await self.on_message(message, self.server_name)

    def _handle_heartbeat_timeout(self) -> None:
        """Handle heartbeat timeout - trigger disconnect."""
        logger.error(
            f"XiaoYi [{self.server_name}]: Heartbeat timeout detected",
        )
        self._pending_disconnect_task = asyncio.create_task(self.disconnect())

    async def _cleanup(self) -> None:
        """Clean up WebSocket and session."""
        if self.state.ws:
            try:
                await self.state.ws.close()
            except Exception:
                pass
            self.state.ws = None

        if self.state.session:
            try:
                await self.state.session.close()
            except Exception:
                pass
            self.state.session = None


# =============================================================================
# XiaoYi Channel (Main Class)
# =============================================================================

# Class-level registry to track active connections per agent_id
_active_connections: Dict[str, "XiaoYiChannel"] = {}
_active_connections_lock = asyncio.Lock()


class XiaoYiChannel(BaseChannel):
    """XiaoYi channel using A2A protocol over WebSocket.

    Refactored version with dual WebSocket connections (primary + backup),
    strict A2A message validation, heartbeat timeout detection, and
    session-to-server routing map.
    """

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

        self.enabled = enabled
        self.ak = ak
        self.sk = sk
        self.agent_id = agent_id
        self.ws_url = ws_url
        self.ws_url_backup = ws_url_backup or self._default_backup_url(ws_url)
        self.task_timeout_ms = task_timeout_ms
        self.bot_prefix = bot_prefix

        # Workspace directory for agent-specific storage
        self._workspace_dir = (
            Path(workspace_dir).expanduser() if workspace_dir else None
        )

        # Use workspace-specific media dir if workspace_dir is provided
        if not media_dir and self._workspace_dir:
            self._media_dir = self._workspace_dir / "media"
        elif media_dir:
            self._media_dir = Path(media_dir).expanduser()
        else:
            self._media_dir = DEFAULT_MEDIA_DIR / "xiaoyi"
        self._media_dir.mkdir(parents=True, exist_ok=True)

        # Connection state
        self._conn1: Optional[XiaoYiConnection] = None
        self._conn2: Optional[XiaoYiConnection] = None
        self._connected = False
        self._reconnect_attempts = 0
        self._stopping = False

        # Session -> server mapping (for reply routing)
        self._session_server_map: Dict[str, str] = {}

        # Session -> task_id mapping
        self._session_task_map: Dict[str, str] = {}

        # Reconnect task
        self._reconnect_task: Optional[asyncio.Task] = None

        # Buffer drain task (to prevent duplicate drainers)
        self._drain_task: Optional[asyncio.Task] = None

        # Message buffer for race condition protection
        # If _enqueue is not set yet, buffer messages here
        self._message_buffer: List[Dict[str, Any]] = []
        self._buffer_lock = asyncio.Lock()
        self._enqueue_ready = asyncio.Event()

    @staticmethod
    def _default_backup_url(primary_url: str) -> str:
        """Generate default backup URL from primary."""
        # Map primary to backup IP-based URL
        if "hag.cloud.huawei.com" in primary_url:
            return primary_url.replace(
                "hag.cloud.huawei.com",
                "116.63.174.231",
            )
        return "wss://116.63.174.231/openclaw/v1/ws/link"

    # =========================================================================
    # Factory Methods
    # =========================================================================

    @classmethod
    def from_env(
        cls,
        process: ProcessHandler,
        on_reply_sent: OnReplySent = None,
    ) -> "XiaoYiChannel":
        """Create channel from environment variables."""
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
            ws_url_backup=os.getenv(
                "XIAOYI_WS_URL_BACKUP",
                "",
            ),
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

    # =========================================================================
    # Config & Health
    # =========================================================================

    def _validate_config(self) -> None:
        """Validate required configuration."""
        if not self.ak:
            raise ValueError("XiaoYi AK (Access Key) is required")
        if not self.sk:
            raise ValueError("XiaoYi SK (Secret Key) is required")
        if not self.agent_id:
            raise ValueError("XiaoYi Agent ID is required")

        # Log config for debugging (mask sensitive values)
        logger.info(
            f"XiaoYi: Config validated - "
            f"agent_id={self.agent_id}, "
            f"ws_url={self.ws_url}, "
            f"ws_url_backup={self.ws_url_backup}",
        )

    async def health_check(self) -> Dict[str, Any]:
        """Check XiaoYi WebSocket connection status."""
        if not self.enabled:
            return {
                "channel": self.channel,
                "status": "disabled",
                "detail": "XiaoYi channel is disabled.",
            }
        if not self._connected:
            return {
                "channel": self.channel,
                "status": "unhealthy",
                "detail": "XiaoYi WebSocket is not connected.",
            }

        # Check both connections
        conn1_ok = self._conn1 and self._conn1.state.connected
        conn2_ok = self._conn2 and self._conn2.state.connected

        if conn1_ok or conn2_ok:
            return {
                "channel": self.channel,
                "status": "healthy",
                "detail": (
                    f"XiaoYi WebSocket connected "
                    f"(server1={'ok' if conn1_ok else 'down'}, "
                    f"server2={'ok' if conn2_ok else 'down'})"
                ),
            }

        return {
            "channel": self.channel,
            "status": "unhealthy",
            "detail": "Both XiaoYi WebSocket connections are closed.",
        }

    # =========================================================================
    # Connection Lifecycle
    # =========================================================================

    async def start(self) -> None:
        """Start WebSocket connections."""
        if not self.enabled:
            logger.debug("XiaoYi: start() skipped (enabled=false)")
            return

        try:
            self._validate_config()
        except ValueError as e:
            logger.error(f"XiaoYi config validation failed: {e}")
            return

        # Check if there's already an active connection for this agent_id
        global _active_connections
        should_connect = True
        async with _active_connections_lock:
            existing = _active_connections.get(self.agent_id)
            if (
                existing is not None
                and existing is not self
                and existing._connected
            ):
                logger.info(
                    f"XiaoYi: Updating settings for existing "
                    f"connection agent_id={self.agent_id}",
                )
                existing._render_style.filter_tool_messages = (
                    self._render_style.filter_tool_messages
                )
                existing._render_style.filter_thinking = (
                    self._render_style.filter_thinking
                )
                existing._render_style.show_tool_details = (
                    self._render_style.show_tool_details
                )
                _active_connections[self.agent_id] = self
                self._copy_state_from(existing)
                existing._mark_inactive()
                should_connect = False

        if not should_connect:
            logger.info(
                "XiaoYi: Reused existing connection with updated settings"
            )
            return

        # Start new connections
        await self._wait_and_register_connection()
        await self._start_connections()

    async def _start_connections(self) -> None:
        """Start both WebSocket connections."""
        logger.info("XiaoYi: Starting dual WebSocket connections...")

        self._conn1 = XiaoYiConnection(
            server_name="server1",
            ws_url=self.ws_url,
            ak=self.ak,
            sk=self.sk,
            agent_id=self.agent_id,
            on_message=self._handle_incoming_message,
            on_disconnect=self._handle_disconnect,
        )

        self._conn2 = XiaoYiConnection(
            server_name="server2",
            ws_url=self.ws_url_backup,
            ak=self.ak,
            sk=self.sk,
            agent_id=self.agent_id,
            on_message=self._handle_incoming_message,
            on_disconnect=self._handle_disconnect,
        )

        # Connect both concurrently
        results = await asyncio.gather(
            self._safe_connect(self._conn1),
            self._safe_connect(self._conn2),
            return_exceptions=True,
        )

        conn1_ok = results[0] is True
        conn2_ok = results[1] is True

        if conn1_ok or conn2_ok:
            self._connected = True
            self._reconnect_attempts = 0
            logger.info(
                f"XiaoYi: Connections established "
                f"(server1={'ok' if conn1_ok else 'failed'}, "
                f"server2={'ok' if conn2_ok else 'failed'})",
            )

            # Start buffer drain task (cancel old one first)
            if self._drain_task and not self._drain_task.done():
                self._drain_task.cancel()
            self._drain_task = asyncio.create_task(self._drain_buffer())
        else:
            logger.error("XiaoYi: Both connections failed")
            self._connected = False
            await self._unregister_connection()
            self._schedule_reconnect()

    async def _safe_connect(self, conn: XiaoYiConnection) -> bool:
        """Safely connect. Exceptions are handled inside conn.connect()."""
        return await conn.connect()

    async def stop(self) -> None:
        """Stop WebSocket connections."""
        logger.info("XiaoYi: Stopping channel...")

        self._stopping = True
        self._connected = False

        # Cancel reconnect task
        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
            self._reconnect_task = None

        # Cancel drain task
        if self._drain_task:
            self._drain_task.cancel()
            try:
                await self._drain_task
            except asyncio.CancelledError:
                pass
            self._drain_task = None

        # Disconnect both connections
        if self._conn1:
            await self._conn1.disconnect()
            self._conn1 = None

        if self._conn2:
            await self._conn2.disconnect()
            self._conn2 = None

        # Unregister from active connections
        await self._unregister_connection()

        logger.info("XiaoYi: Channel stopped")

    # =========================================================================
    # Connection Registry
    # =========================================================================

    async def _wait_and_register_connection(self) -> None:
        """Stop any existing connection with same agent_id, then register."""
        global _active_connections

        existing = None
        async with _active_connections_lock:
            existing = _active_connections.get(self.agent_id)
            if existing is not None and existing is not self:
                _active_connections.pop(self.agent_id, None)
            _active_connections[self.agent_id] = self

        if existing is not None and existing is not self:
            logger.info(
                f"XiaoYi: Stopping old connection for agent_id={self.agent_id}",
            )
            try:
                existing._stopping = True
                existing._connected = False
                await existing.stop()
            except Exception as e:
                logger.debug(f"XiaoYi: Error stopping old connection: {e}")

    async def _unregister_connection(self) -> None:
        """Unregister this connection from active connections."""
        global _active_connections
        async with _active_connections_lock:
            if _active_connections.get(self.agent_id) is self:
                _active_connections.pop(self.agent_id, None)

    def _copy_state_from(self, existing: "XiaoYiChannel") -> None:
        """Copy WebSocket state from existing connection."""
        self._conn1 = existing._conn1
        self._conn2 = existing._conn2
        self._connected = existing._connected
        self._session_task_map = existing._session_task_map
        self._session_server_map = existing._session_server_map

    def _mark_inactive(self) -> None:
        """Mark this instance as no longer owning the connection."""
        self._conn1 = None
        self._conn2 = None
        self._connected = False

    # =========================================================================
    # Reconnection Logic
    # =========================================================================

    def _handle_disconnect(self, server_name: str) -> None:
        """Handle disconnection from a server."""
        logger.warning(f"XiaoYi: {server_name} disconnected")

        # Clean up session mappings pointing to this server
        stale_sessions = [
            sid
            for sid, sname in self._session_server_map.items()
            if sname == server_name
        ]
        for sid in stale_sessions:
            self._session_server_map.pop(sid, None)
            logger.debug(
                f"XiaoYi [MAP]: Removed stale mapping {sid[:40]} -> {server_name}",
            )

        # Check if any connection is still alive
        conn1_ok = self._conn1 and self._conn1.state.connected
        conn2_ok = self._conn2 and self._conn2.state.connected

        if not conn1_ok and not conn2_ok and not self._stopping:
            self._connected = False
            self._schedule_reconnect()

    def _schedule_reconnect(self) -> None:
        """Schedule reconnection attempt."""
        if self._stopping:
            return
        if self._reconnect_attempts >= MAX_RECONNECT_ATTEMPTS:
            logger.error("XiaoYi: Max reconnect attempts reached")
            return

        delay_idx = min(self._reconnect_attempts, len(RECONNECT_DELAYS) - 1)
        delay = RECONNECT_DELAYS[delay_idx]
        self._reconnect_attempts += 1

        logger.info(
            f"XiaoYi: Reconnecting in {delay}s "
            f"(attempt {self._reconnect_attempts})",
        )

        self._reconnect_task = asyncio.create_task(
            self._reconnect_after(delay)
        )

    async def _reconnect_after(self, delay: float) -> None:
        """Reconnect after delay."""
        await asyncio.sleep(delay)
        if self._stopping or self._connected:
            return

        try:
            await self._start_connections()
        except Exception as e:
            logger.error(f"XiaoYi: Reconnect failed: {e}")
            self._schedule_reconnect()

    # =========================================================================
    # Message Handling (Incoming)
    # =========================================================================

    async def _handle_incoming_message(
        self,
        message: Dict[str, Any],
        server_name: str,
    ) -> None:
        """Handle incoming message from a specific server."""
        try:
            # Validate agentId
            msg_agent_id = message.get("agentId")
            if msg_agent_id and msg_agent_id != self.agent_id:
                logger.error(
                    f"XiaoYi [{server_name}]: Mismatched agentId! "
                    f"Received='{msg_agent_id}', Expected='{self.agent_id}'",
                )
                return

            # Extract sessionId for routing map
            session_id = self._extract_session_id(message)
            if session_id:
                self._session_server_map[session_id] = server_name
                logger.debug(
                    f"XiaoYi [MAP]: Session {session_id} -> {server_name}",
                )

            # Route by method
            method = message.get("method", "")
            action = message.get("action", "")

            # Heartbeat response
            if message.get("msgType") == "heartbeat":
                return

            # Clear context
            if method == "clearContext" or action == "clear":
                await self._handle_clear_context(message)
                return

            # Tasks cancel
            if method == "tasks/cancel" or action == "tasks/cancel":
                await self._handle_tasks_cancel(message)
                return

            # A2A request - strict validation
            if self._is_valid_a2a_message(message):
                await self._handle_a2a_request(message)
            else:
                logger.debug(
                    f"XiaoYi [{server_name}]: Message did not pass A2A "
                    f"validation (method={method})",
                )

        except Exception as e:
            logger.error(
                f"XiaoYi [{server_name}]: Error handling message: {e}",
                exc_info=True,
            )

    def _is_valid_a2a_message(self, message: Dict[str, Any]) -> bool:
        """Strict A2A message validation (matching OpenClaw behavior).

        This validates all required fields to ensure the message is a
        valid A2A request before processing.
        """
        if not isinstance(message, dict):
            return False

        # Must have method = message/stream
        if message.get("method") != "message/stream":
            return False

        # Must have jsonrpc = 2.0
        if message.get("jsonrpc") != "2.0":
            logger.debug(
                "XiaoYi A2A validation failed: jsonrpc != '2.0'",
            )
            return False

        # Must have string id
        msg_id = message.get("id")
        if not isinstance(msg_id, str):
            logger.debug(
                f"XiaoYi A2A validation failed: id is not string ({type(msg_id)})",
            )
            return False

        # Must have params with required fields
        params = message.get("params")
        if not isinstance(params, dict):
            logger.debug("XiaoYi A2A validation failed: missing params")
            return False

        # params.id must be string
        if not isinstance(params.get("id"), str):
            logger.debug("XiaoYi A2A validation failed: params.id not string")
            return False

        # sessionId must be in params or top level
        session_id = params.get("sessionId") or message.get("sessionId")
        if not isinstance(session_id, str) or not session_id:
            logger.debug("XiaoYi A2A validation failed: no valid sessionId")
            return False

        # Must have message with role and parts
        msg = params.get("message")
        if not isinstance(msg, dict):
            logger.debug("XiaoYi A2A validation failed: missing message")
            return False

        if not isinstance(msg.get("role"), str):
            logger.debug(
                "XiaoYi A2A validation failed: message.role not string"
            )
            return False

        if not isinstance(msg.get("parts"), list):
            logger.debug(
                "XiaoYi A2A validation failed: message.parts not array"
            )
            return False

        logger.debug("XiaoYi A2A validation passed")
        return True

    def _extract_session_id(self, message: Dict[str, Any]) -> Optional[str]:
        """Extract sessionId from message (params or top level)."""
        if message.get("method") == "message/stream":
            params = message.get("params", {})
            return params.get("sessionId") or message.get("sessionId")

        if message.get("method") in ("tasks/cancel", "clearContext"):
            return message.get("sessionId")

        if message.get("action") == "clear":
            return message.get("sessionId")

        return None

    # =========================================================================
    # A2A Request Processing
    # =========================================================================

    async def _handle_a2a_request(self, message: Dict[str, Any]) -> None:
        """Handle A2A request message."""
        try:
            params = message.get("params", {})
            session_id = params.get("sessionId") or message.get("sessionId")
            task_id = params.get("id") or message.get("id")

            if not session_id:
                logger.warning("XiaoYi: No sessionId in A2A message")
                return

            self._session_task_map[session_id] = task_id
            # Also store with xiaoyi: prefix for lookup consistency
            prefixed = f"xiaoyi:{session_id}"
            if prefixed != session_id:
                self._session_task_map[prefixed] = task_id

            logger.info(
                f"XiaoYi: Processing A2A request "
                f"session={session_id[:40]} task={task_id[:40]}",
            )

            # Extract content parts
            text_parts: List[str] = []
            content_parts: List[Any] = []
            msg = params.get("message", {})
            parts = msg.get("parts", [])

            for part in parts:
                kind = part.get("kind")
                if kind == "text" and part.get("text"):
                    text_parts.append(part["text"])
                elif kind == "file":
                    await self._process_file_part(
                        part,
                        text_parts,
                        content_parts,
                    )

            # Build content
            text_content = " ".join(text_parts).strip()
            if text_content:
                content_parts.insert(
                    0,
                    TextContent(type=ContentType.TEXT, text=text_content),
                )

            if not content_parts:
                logger.debug("XiaoYi: Empty message content, skipping")
                return

            native = {
                "channel_id": self.channel,
                "sender_id": session_id,
                "content_parts": content_parts,
                "meta": {
                    "session_id": session_id,
                    "task_id": task_id,
                    "message_id": message.get("id"),
                },
            }

            # Try to enqueue, with race condition protection
            await self._safe_enqueue(native, session_id)

        except Exception as e:
            logger.error(
                f"XiaoYi: Error handling A2A request: {e}",
                exc_info=True,
            )

    async def _safe_enqueue(
        self,
        native: Dict[str, Any],
        session_id: str,
    ) -> None:
        """Safely enqueue message with buffer fallback.

        Fixes the race condition where _enqueue might not be set yet
        when the first message arrives.
        """
        if self._enqueue:
            try:
                self._enqueue(native)
                logger.debug(
                    f"XiaoYi: Message enqueued for session {session_id[:40]}",
                )
            except Exception as e:
                logger.error(f"XiaoYi: Enqueue error: {e}")
        else:
            # Buffer the message for later processing
            async with self._buffer_lock:
                self._message_buffer.append(native)
            logger.warning(
                f"XiaoYi: _enqueue not set, message buffered for "
                f"session {session_id[:40]}. "
                f"Buffer size: {len(self._message_buffer)}",
            )

    async def _drain_buffer(self) -> None:
        """Drain buffered messages once _enqueue is available.

        This runs as a background task to handle messages that arrived
        before _enqueue was set.
        """
        logger.debug("XiaoYi: Buffer drain task started")

        # Wait up to 60 seconds for _enqueue to be set
        for _ in range(120):  # 120 * 0.5s = 60s
            if self._enqueue:
                break
            await asyncio.sleep(0.5)

        if not self._enqueue:
            logger.error(
                "XiaoYi: _enqueue not set after 60s, "
                f"dropping {len(self._message_buffer)} buffered messages",
            )
            return

        # Drain buffer
        async with self._buffer_lock:
            buffer = self._message_buffer[:]
            self._message_buffer.clear()

        for msg in buffer:
            try:
                self._enqueue(msg)
                logger.debug("XiaoYi: Buffered message drained")
            except Exception as e:
                logger.error(f"XiaoYi: Failed to drain buffered message: {e}")

        logger.info(
            f"XiaoYi: Buffer drained, {len(buffer)} messages processed",
        )

    # =========================================================================
    # File Processing
    # =========================================================================

    async def _process_file_part(
        self,
        part: Dict[str, Any],
        text_parts: List[str],
        content_parts: List[Any],
    ) -> None:
        """Process a file part from A2A message."""
        file_info = part.get("file", {})
        file_url = file_info.get("uri", "")
        filename = file_info.get("name", "file")
        mime_type = file_info.get("mimeType", "")

        if not file_url:
            return

        local_path = await download_file(
            url=file_url,
            media_dir=self._media_dir,
            filename=filename,
        )

        if not local_path:
            text_parts.append(f"[{filename}: download failed]")
            return

        if mime_type.startswith("image/"):
            content_parts.append(
                ImageContent(
                    type=ContentType.IMAGE,
                    image_url=local_path,
                ),
            )
        else:
            content_parts.append(
                FileContent(
                    type=ContentType.FILE,
                    file_url=local_path,
                    filename=filename,
                ),
            )

    # =========================================================================
    # Clear Context & Cancel Handlers
    # =========================================================================

    async def _handle_clear_context(self, message: Dict[str, Any]) -> None:
        """Handle clear context message."""
        session_id = message.get("sessionId") or ""
        request_id = message.get("id") or ""

        logger.info(f"XiaoYi: Clear context for session {session_id}")

        await self._send_clear_context_response(request_id, session_id)

        if session_id:
            self._session_task_map.pop(session_id, None)
            self._session_server_map.pop(session_id, None)

    async def _handle_tasks_cancel(self, message: Dict[str, Any]) -> None:
        """Handle tasks cancel message."""
        session_id = message.get("sessionId") or ""
        request_id = message.get("id") or ""
        task_id = message.get("taskId") or request_id

        logger.info(
            f"XiaoYi: Cancel task {task_id} for session {session_id}",
        )

        await self._send_tasks_cancel_response(request_id, session_id)

    # =========================================================================
    # Response Sending
    # =========================================================================

    async def _send_clear_context_response(
        self,
        request_id: str,
        session_id: str,
        success: bool = True,
    ) -> None:
        """Send clear context response."""
        json_rpc_response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "status": {"state": "cleared" if success else "failed"},
            },
        }

        msg = {
            "msgType": "agent_response",
            "agentId": self.agent_id,
            "sessionId": session_id,
            "taskId": request_id,
            "msgDetail": json.dumps(json_rpc_response),
        }

        await self._send_to_session_server(session_id, msg)

    async def _send_tasks_cancel_response(
        self,
        request_id: str,
        session_id: str,
        success: bool = True,
    ) -> None:
        """Send tasks cancel response."""
        json_rpc_response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "id": request_id,
                "status": {"state": "canceled" if success else "failed"},
            },
        }

        msg = {
            "msgType": "agent_response",
            "agentId": self.agent_id,
            "sessionId": session_id,
            "taskId": request_id,
            "msgDetail": json.dumps(json_rpc_response),
        }

        await self._send_to_session_server(session_id, msg)

    async def _send_to_session_server(
        self,
        session_id: str,
        message: Dict[str, Any],
    ) -> None:
        """Send message to the server associated with a session.

        Uses session->server mapping to route replies to the correct
        WebSocket connection.
        """
        server_name = self._session_server_map.get(session_id)

        # Check which connection is active for this session
        if (
            server_name == "server2"
            and self._conn2
            and self._conn2.state.connected
        ):
            success = await self._conn2.send_json(message)
            if not success:
                # Fallback to server1 if server2 fails
                if self._conn1 and self._conn1.state.connected:
                    await self._conn1.send_json(message)
                    self._session_server_map[session_id] = "server1"
        elif self._conn1 and self._conn1.state.connected:
            success = await self._conn1.send_json(message)
            if success and server_name != "server1":
                # Update mapping
                self._session_server_map[session_id] = "server1"
        elif self._conn2 and self._conn2.state.connected:
            success = await self._conn2.send_json(message)
            if success:
                self._session_server_map[session_id] = "server2"
        else:
            logger.error("XiaoYi: No available connection to send response")

    # =========================================================================
    # Outgoing Message Sending
    # =========================================================================

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send text message via WebSocket."""
        if not self.enabled or not self._connected:
            logger.warning("XiaoYi: Cannot send - not connected")
            return

        meta = meta or {}
        session_id = meta.get("session_id") or to_handle
        task_id = meta.get("task_id") or self._session_task_map.get(session_id)

        if not task_id:
            logger.warning(f"XiaoYi: No task_id for session {session_id}")
            return

        if not text or not text.strip():
            return

        message_id = meta.get("message_id", str(uuid.uuid4()))
        chunks = self._chunk_text(text)

        for chunk in chunks:
            await self._send_chunk(session_id, task_id, message_id, chunk)

    def _chunk_text(self, text: str) -> List[str]:
        """Split text into chunks of TEXT_CHUNK_LIMIT size."""
        if len(text) <= TEXT_CHUNK_LIMIT:
            return [text]

        chunks = []
        lines = text.split("\n")
        current_chunk = ""

        for line in lines:
            if len(line) > TEXT_CHUNK_LIMIT:
                if current_chunk:
                    chunks.append(current_chunk.rstrip("\n"))
                    current_chunk = ""
                for i in range(0, len(line), TEXT_CHUNK_LIMIT):
                    chunks.append(line[i : i + TEXT_CHUNK_LIMIT])
            else:
                test_chunk = (
                    current_chunk + "\n" + line if current_chunk else line
                )
                if len(test_chunk) > TEXT_CHUNK_LIMIT:
                    if current_chunk:
                        chunks.append(current_chunk)
                    current_chunk = line
                else:
                    current_chunk = test_chunk

        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    def _build_artifact_msg(
        self,
        session_id: str,
        task_id: str,
        message_id: str,
        parts: List[Dict[str, Any]],
        append: bool = True,
        final: bool = False,
    ) -> Dict[str, Any]:
        """Build artifact-update message for XiaoYi A2A protocol.

        Per A2A spec, every artifact-update message has lastChunk=true
        as each message represents a complete artifact unit.
        The append flag indicates whether this unit appends to previous
        content (True) or replaces it (False for final message).
        """
        artifact_id = f"artifact_{uuid.uuid4().hex[:16]}"
        json_rpc_response = {
            "jsonrpc": "2.0",
            "id": message_id,
            "result": {
                "taskId": task_id,
                "kind": "artifact-update",
                "append": append,
                "lastChunk": True,  # Always true per A2A spec
                "final": final,
                "artifact": {
                    "artifactId": artifact_id,
                    "parts": parts,
                },
            },
        }
        return {
            "msgType": "agent_response",
            "agentId": self.agent_id,
            "sessionId": session_id,
            "taskId": task_id,
            "msgDetail": json.dumps(json_rpc_response),
        }

    async def _send_chunk(
        self,
        session_id: str,
        task_id: str,
        message_id: str,
        text: str,
    ) -> None:
        """Send a single text chunk via WebSocket."""
        msg = self._build_artifact_msg(
            session_id,
            task_id,
            message_id,
            [{"kind": "text", "text": text}],
        )
        await self._send_to_session_server(session_id, msg)

    async def _send_reasoning_chunk(
        self,
        session_id: str,
        task_id: str,
        message_id: str,
        reasoning_text: str,
    ) -> None:
        """Send a reasoning/thinking chunk via WebSocket."""
        msg = self._build_artifact_msg(
            session_id,
            task_id,
            message_id,
            [{"kind": "reasoningText", "reasoningText": reasoning_text}],
        )
        await self._send_to_session_server(session_id, msg)

    async def send_status_update(
        self,
        session_id: str,
        task_id: str,
        message_id: str,
        text: str,
        state: str,
    ) -> None:
        """Send A2A status-update message.

        This is required by the XiaoYi A2A protocol to signal task state
        transitions (e.g., "working" -> "completed" -> "failed").
        """
        if not self.enabled or not self._connected:
            return

        status_update = {
            "taskId": task_id,
            "kind": "status-update",
            "final": False,
            "status": {
                "message": {
                    "role": "agent",
                    "parts": [{"kind": "text", "text": text}],
                },
                "state": state,
            },
        }

        json_rpc_response = {
            "jsonrpc": "2.0",
            "id": message_id,
            "result": status_update,
        }

        msg = {
            "msgType": "agent_response",
            "agentId": self.agent_id,
            "sessionId": session_id,
            "taskId": task_id,
            "msgDetail": json.dumps(json_rpc_response),
        }

        await self._send_to_session_server(session_id, msg)
        logger.info(
            f"XiaoYi: Sent status-update state={state} session={session_id[:40]}"
        )

    async def send_final_message(
        self,
        session_id: str,
        task_id: str,
        message_id: str,
    ) -> None:
        """Send final artifact-update to signal stream completion.

        Sends a status-update (completed) followed by a final
        artifact-update (append=False, final=True).
        """
        if not self.enabled or not self._connected:
            logger.warning(f"XiaoYi: Cannot send final - not connected")
            return

        # Step 1: Send status update indicating completion
        try:
            await self.send_status_update(
                session_id,
                task_id,
                message_id,
                text="任务处理已完成",
                state="completed",
            )
        except Exception as e:
            logger.error(f"XiaoYi: Failed to send status update: {e}")

        # Step 2: Send final artifact with empty text to end stream
        try:
            msg = self._build_artifact_msg(
                session_id,
                task_id,
                message_id,
                [{"kind": "text", "text": ""}],
                append=False,
                final=True,
            )
            await self._send_to_session_server(session_id, msg)
            logger.info(
                f"XiaoYi: Sent final message session={session_id[:40]}"
            )
        except Exception as e:
            logger.error(f"XiaoYi: Failed to send final message: {e}")

    async def send_media(
        self,
        to_handle: str,
        part: OutgoingContentPart,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send media message via WebSocket."""
        if not self.enabled or not self._connected:
            return

        meta = meta or {}
        session_id = meta.get("session_id") or to_handle
        task_id = meta.get("task_id") or self._session_task_map.get(session_id)

        if not task_id:
            return

        part_type = getattr(part, "type", None)

        if part_type == ContentType.IMAGE:
            artifact_part = {
                "kind": "file",
                "file": {
                    "name": "image",
                    "mimeType": "image/png",
                    "uri": getattr(part, "image_url", ""),
                },
            }
        elif part_type == ContentType.VIDEO:
            artifact_part = {
                "kind": "file",
                "file": {
                    "name": "video",
                    "mimeType": "video/mp4",
                    "uri": getattr(part, "video_url", ""),
                },
            }
        elif part_type == ContentType.FILE:
            artifact_part = {
                "kind": "file",
                "file": {
                    "name": getattr(part, "file_name", "file"),
                    "mimeType": "application/octet-stream",
                    "uri": getattr(part, "file_url", ""),
                },
            }
        else:
            return

        msg = self._build_artifact_msg(
            session_id,
            task_id,
            str(uuid.uuid4()),
            [artifact_part],
            append=False,
            final=True,
        )
        await self._send_to_session_server(session_id, msg)

    # =========================================================================
    # XiaoYi Parts Extraction & Sending
    # =========================================================================

    def _extract_xiaoyi_parts(
        self,
        message: Any,
    ) -> List[Dict[str, Any]]:
        """Extract parts from message with proper XiaoYi kinds."""
        from agentscope_runtime.engine.schemas.agent_schemas import (
            MessageType,
        )

        msg_type = getattr(message, "type", None)
        content = getattr(message, "content", None) or []
        parts = []

        # Check if this is a reasoning/thinking message type
        if msg_type == MessageType.REASONING:
            if self._render_style.filter_thinking:
                return []
            for c in content:
                text = getattr(c, "text", None)
                if text:
                    parts.append(
                        {
                            "kind": "reasoningText",
                            "reasoningText": text + "\n",
                        }
                    )
            return parts

        # Process each content item
        for c in content:
            ctype = getattr(c, "type", None)

            # Handle thinking blocks
            if ctype == ContentType.DATA:
                data = getattr(c, "data", None)
                if isinstance(data, dict):
                    blocks = data.get("blocks", [])
                    if (
                        isinstance(blocks, list)
                        and not self._render_style.filter_thinking
                    ):
                        for block in blocks:
                            if (
                                isinstance(block, dict)
                                and block.get("type") == "thinking"
                            ):
                                thinking_text = block.get("thinking", "")
                                if thinking_text:
                                    parts.append(
                                        {
                                            "kind": "reasoningText",
                                            "reasoningText": thinking_text
                                            + "\n",
                                        }
                                    )

            # Handle TEXT type
            if ctype == ContentType.TEXT and getattr(c, "text", None):
                text = c.text
                if not text.startswith("\n"):
                    text = "\n\n" + text
                parts.append({"kind": "text", "text": text})

            # Handle REFUSAL type
            elif ctype == ContentType.REFUSAL and getattr(c, "refusal", None):
                parts.append({"kind": "text", "text": c.refusal})

        # Handle tool messages
        if self._render_style.filter_tool_messages:
            if msg_type in (
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
            for c in content:
                if getattr(c, "type", None) != ContentType.DATA:
                    continue
                data = getattr(c, "data", None)
                if not isinstance(data, dict):
                    continue
                name = data.get("name") or "tool"
                args = data.get("arguments") or "{}"
                formatted = f"\n\n🔧 **{name}**\n```\n{args}\n```\n"
                parts.append({"kind": "text", "text": formatted})
            return parts

        if msg_type in (
            MessageType.FUNCTION_CALL_OUTPUT,
            MessageType.PLUGIN_CALL_OUTPUT,
            MessageType.MCP_TOOL_CALL_OUTPUT,
        ):
            for c in content:
                if getattr(c, "type", None) != ContentType.DATA:
                    continue
                data = getattr(c, "data", None)
                if not isinstance(data, dict):
                    continue
                name = data.get("name") or "tool"
                output = data.get("output", "")

                try:
                    if isinstance(output, str):
                        parsed = json.loads(output)
                    else:
                        parsed = output

                    if isinstance(parsed, list):
                        texts = []
                        for item in parsed:
                            if (
                                isinstance(item, dict)
                                and item.get("type") == "text"
                            ):
                                texts.append(item.get("text", ""))
                        output_str = "\n".join(texts) if texts else str(parsed)
                    elif isinstance(parsed, dict):
                        output_str = json.dumps(
                            parsed, ensure_ascii=False, indent=2
                        )
                    else:
                        output_str = str(parsed)
                except (json.JSONDecodeError, TypeError):
                    output_str = str(output) if output else ""

                if len(output_str) > 500:
                    output_str = output_str[:500] + "..."

                output_str = output_str.replace("```", "\\`\\`\\`")
                formatted = f"\n\n✅ **{name}**\n```\n{output_str}\n```\n"
                parts.append({"kind": "text", "text": formatted})
            return parts

        # Fallback to renderer
        if not parts:
            rendered_parts = self._renderer.message_to_parts(message)
            for rp in rendered_parts:
                if getattr(rp, "type", None) == ContentType.TEXT:
                    text = getattr(rp, "text", "")
                    if text:
                        parts.append({"kind": "text", "text": text})

        return parts

    async def send_xiaoyi_parts(
        self,
        to_handle: str,
        parts: List[Dict[str, Any]],
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send parts with XiaoYi-specific format."""
        if not self.enabled or not self._connected:
            logger.warning("XiaoYi: Cannot send - not connected")
            return

        meta = meta or {}
        session_id = meta.get("session_id") or to_handle
        task_id = meta.get("task_id") or self._session_task_map.get(session_id)

        if not task_id:
            logger.warning(f"XiaoYi: No task_id for session {session_id}")
            return

        message_id = meta.get("message_id", str(uuid.uuid4()))

        # Build artifact parts
        artifact_parts = []
        for part in parts:
            kind = part.get("kind", "text")
            if kind == "reasoningText":
                artifact_parts.append(
                    {
                        "kind": "reasoningText",
                        "reasoningText": part.get("reasoningText", ""),
                    }
                )
            elif kind == "text":
                artifact_parts.append(
                    {
                        "kind": "text",
                        "text": part.get("text", ""),
                    }
                )

        if not artifact_parts:
            return

        # Check if chunking needed
        max_part_len = max(
            len(p.get("text", "") or p.get("reasoningText", ""))
            for p in artifact_parts
        )

        if max_part_len > TEXT_CHUNK_LIMIT:
            for part in artifact_parts:
                kind = part.get("kind", "text")
                content = part.get("text", "") or part.get("reasoningText", "")
                if len(content) > TEXT_CHUNK_LIMIT:
                    chunks = self._chunk_text(content)
                    for chunk in chunks:
                        if kind == "reasoningText":
                            await self._send_reasoning_chunk(
                                session_id,
                                task_id,
                                message_id,
                                chunk,
                            )
                        else:
                            await self._send_chunk(
                                session_id,
                                task_id,
                                message_id,
                                chunk,
                            )
                else:
                    if kind == "reasoningText":
                        await self._send_reasoning_chunk(
                            session_id,
                            task_id,
                            message_id,
                            content,
                        )
                    else:
                        await self._send_chunk(
                            session_id,
                            task_id,
                            message_id,
                            content,
                        )
            return

        # Send as single message
        msg = self._build_artifact_msg(
            session_id,
            task_id,
            message_id,
            artifact_parts,
        )
        await self._send_to_session_server(session_id, msg)

    # =========================================================================
    # Event Handlers
    # =========================================================================

    async def on_event_message_completed(
        self,
        request: "AgentRequest",
        to_handle: str,
        event: Any,
        send_meta: Dict[str, Any],
    ) -> None:
        """Override to handle XiaoYi-specific message formatting."""
        parts = self._extract_xiaoyi_parts(event)

        if not parts:
            logger.debug("XiaoYi: No parts to send for message")
            return

        await self.send_xiaoyi_parts(to_handle, parts, send_meta)

    def resolve_session_id(
        self,
        sender_id: str,
        channel_meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Resolve session ID from sender and meta."""
        if channel_meta and channel_meta.get("session_id"):
            return f"xiaoyi:{channel_meta['session_id']}"
        return f"xiaoyi:{sender_id}"

    def get_to_handle_from_request(self, request: "AgentRequest") -> str:
        """Get send target from request."""
        meta = getattr(request, "channel_meta", None) or {}
        if meta.get("session_id"):
            return meta["session_id"]
        return getattr(request, "user_id", "") or ""

    def build_agent_request_from_native(
        self,
        native_payload: Any,
    ) -> "AgentRequest":
        """Build AgentRequest from native payload."""
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

    def to_handle_from_target(self, *, user_id: str, session_id: str) -> str:
        """Map dispatch target to channel-specific to_handle."""
        if session_id.startswith("xiaoyi:"):
            return session_id.split(":", 1)[-1]
        return user_id

    async def _run_process_loop(
        self,
        request: "AgentRequest",
        to_handle: str,
        send_meta: Dict[str, Any],
    ) -> None:
        """Run process and send events. Override to send final message."""
        from agentscope_runtime.engine.schemas.agent_schemas import RunStatus

        last_response = None
        session_id = send_meta.get("session_id") or to_handle

        try:
            async for event in self._process(request):
                obj = getattr(event, "object", None)
                status = getattr(event, "status", None)
                if obj == "message" and status == RunStatus.Completed:
                    await self.on_event_message_completed(
                        request,
                        to_handle,
                        event,
                        send_meta,
                    )
                elif obj == "response":
                    last_response = event
                    await self.on_event_response(request, event)

            # Process loop completed - final message is sent via
            # _on_process_completed which BaseChannel calls after this.
            task_id = (
                send_meta.get("task_id")
                or self._session_task_map.get(
                    session_id,
                )
                or self._session_task_map.get(to_handle)
            )
            message_id = send_meta.get("message_id") or str(uuid.uuid4())

            logger.info(
                f"XiaoYi: _run_process_loop completed. "
                f"session={session_id[:40]} task_id={'set' if task_id else 'NONE'} "
                f"message_id={message_id[:40]}",
            )

            err_msg = self._get_response_error_message(last_response)
            if err_msg:
                await self._on_consume_error(
                    request,
                    to_handle,
                    f"Error: {err_msg}",
                )
            if self._on_reply_sent:
                args = self.get_on_reply_sent_args(request, to_handle)
                self._on_reply_sent(self.channel, *args)

        except Exception:
            logger.exception("XiaoYi channel consume_one failed")
            await self._on_consume_error(
                request,
                to_handle,
                "An error occurred while processing your request.",
            )

    async def _on_process_completed(
        self,
        request: "AgentRequest",
        to_handle: str,
        send_meta: Dict[str, Any],
    ) -> None:
        """Send final message when agent processing completes.

        This is called by BaseChannel._stream_with_tracker (main path)
        and BaseChannel._run_process_loop (fallback path) when all
        events have been processed successfully.
        """
        session_id = send_meta.get("session_id") or to_handle
        task_id = (
            send_meta.get("task_id")
            or self._session_task_map.get(session_id)
            or self._session_task_map.get(to_handle)
        )
        message_id = send_meta.get("message_id") or str(uuid.uuid4())

        logger.info(
            f"XiaoYi: Process completed. "
            f"session={session_id[:40]} task_id={'set' if task_id else 'NONE'} "
            f"message_id={message_id[:40]}",
        )

        if task_id and session_id:
            try:
                await self.send_final_message(session_id, task_id, message_id)
                logger.info("XiaoYi: Final message sent successfully")
            except Exception as e:
                logger.error(f"XiaoYi: Failed to send final message: {e}")
        else:
            logger.error(
                f"XiaoYi: CANNOT send final message - "
                f"task_id={task_id}, session_id={session_id}",
            )
