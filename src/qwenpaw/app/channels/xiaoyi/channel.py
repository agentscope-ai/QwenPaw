# -*- coding: utf-8 -*-
"""XiaoYi Channel implementation.

XiaoYi uses A2A (Agent-to-Agent) protocol over WebSocket.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
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


# Class-level registry to track active connections per agent_id
_active_connections: Dict[str, "XiaoYiChannel"] = {}
_active_connections_lock = asyncio.Lock()


class XiaoYiChannel(BaseChannel):
    """XiaoYi channel using A2A protocol over WebSocket.

    This channel connects to XiaoYi server as a WebSocket client
    and handles A2A (Agent-to-Agent) protocol messages.
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

        # WebSocket state
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._connected = False
        self._reconnect_attempts = 0
        self._stopping = False  # Flag to prevent reconnect during stop

        # Session -> task_id mapping
        self._session_task_map: Dict[str, str] = {}

        # Heartbeat task
        self._heartbeat_task: Optional[asyncio.Task] = None

        # Receive loop task
        self._receive_task: Optional[asyncio.Task] = None

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
        """Validate required configuration."""
        if not self.ak:
            raise ValueError("XiaoYi AK (Access Key) is required")
        if not self.sk:
            raise ValueError("XiaoYi SK (Secret Key) is required")
        if not self.agent_id:
            raise ValueError("XiaoYi Agent ID is required")

    async def start(self) -> None:
        """Start WebSocket connection."""
        if not self.enabled:
            logger.debug("XiaoYi: start() skipped (enabled=false)")
            return

        try:
            self._validate_config()
        except ValueError as e:
            logger.error(f"XiaoYi config validation failed: {e}")
            return

        # Check if there's already an active connection for this agent_id
        # and reuse it if only filter settings changed
        global _active_connections
        should_connect = True
        async with _active_connections_lock:
            existing = _active_connections.get(self.agent_id)
            if (
                existing is not None
                and existing is not self
                and existing._connected  # pylint: disable=protected-access
            ):
                # pylint: disable=protected-access
                # Found active connection - update settings
                logger.info(
                    "XiaoYi: Updating settings for existing "
                    f"connection agent_id={self.agent_id}",
                )
                # Update render style settings on the existing channel
                existing._render_style.filter_tool_messages = (
                    self._render_style.filter_tool_messages
                )
                existing._render_style.filter_thinking = (
                    self._render_style.filter_thinking
                )
                existing._render_style.show_tool_details = (
                    self._render_style.show_tool_details
                )
                # Re-register this instance
                # (so the new instance becomes the active one)
                _active_connections[self.agent_id] = self
                # Copy the WebSocket state to this instance
                self._ws = existing._ws
                self._session = existing._session
                self._connected = existing._connected
                self._heartbeat_task = existing._heartbeat_task
                self._receive_task = existing._receive_task
                self._session_task_map = existing._session_task_map
                # Mark old instance as not owning the connection anymore
                existing._ws = None
                existing._session = None
                existing._connected = False
                existing._heartbeat_task = None
                existing._receive_task = None
                should_connect = False

        if not should_connect:
            logger.info(
                "XiaoYi: Reused existing connection with updated settings",
            )
            return

        # No existing connection or can't reuse - start new connection
        await self._wait_and_register_connection()

        logger.info(f"XiaoYi: Connecting to {self.ws_url}...")

        try:
            await self._connect()
        except Exception as e:
            logger.error(f"XiaoYi connection failed: {e}")
            # Unregister on failure
            await self._unregister_connection()
            self._schedule_reconnect()

    async def _wait_and_register_connection(self) -> None:
        """Stop any existing connection with same agent_id, then register."""
        global _active_connections

        # First, get existing connection and remove it from registry
        existing = None
        async with _active_connections_lock:
            existing = _active_connections.get(self.agent_id)
            if existing is not None and existing is not self:
                # Remove from registry immediately
                _active_connections.pop(self.agent_id, None)
            # Register this instance
            _active_connections[self.agent_id] = self

        # Now stop the old connection outside the lock
        if existing is not None and existing is not self:
            # pylint: disable=protected-access
            logger.info(
                "XiaoYi: Stopping old connection for "
                f"agent_id={self.agent_id}",
            )
            try:
                # Set stopping flag FIRST to prevent any reconnect
                existing._stopping = True
                existing._connected = False
                # Cancel tasks and wait for them to finish
                if existing._heartbeat_task:
                    existing._heartbeat_task.cancel()
                    try:
                        await existing._heartbeat_task
                    except asyncio.CancelledError:
                        pass
                if existing._receive_task:
                    existing._receive_task.cancel()
                    try:
                        await existing._receive_task
                    except asyncio.CancelledError:
                        pass
                # Close WebSocket
                if existing._ws:
                    await existing._ws.close()
                if existing._session:
                    await existing._session.close()
                logger.debug("XiaoYi: Old connection stopped")
            except Exception as e:
                logger.debug(f"XiaoYi: Error stopping old connection: {e}")

        logger.debug(
            f"XiaoYi: Registered connection for agent_id={self.agent_id}",
        )

    async def _unregister_connection(self) -> None:
        """Unregister this connection from active connections."""
        global _active_connections
        async with _active_connections_lock:
            if _active_connections.get(self.agent_id) is self:
                _active_connections.pop(self.agent_id, None)
                logger.debug(
                    "XiaoYi: Unregistered connection for "
                    f"agent_id={self.agent_id}",
                )

    async def _connect(self) -> None:
        """Establish WebSocket connection."""
        headers = generate_auth_headers(self.ak, self.sk, self.agent_id)

        # Clean up any existing session first
        await self._cleanup_session()

        self._session = aiohttp.ClientSession()
        ws_timeout = aiohttp.ClientWSTimeout(ws_close=CONNECTION_TIMEOUT)

        try:
            self._ws = await self._session.ws_connect(
                self.ws_url,
                headers=headers,
                timeout=ws_timeout,
            )

            self._connected = True
            self._reconnect_attempts = 0
            logger.info("XiaoYi: WebSocket connected")

            # Send init message
            await self._send_init_message()

            # Start heartbeat
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

            # Start receive loop
            self._receive_task = asyncio.create_task(self._receive_loop())

        except Exception as e:
            logger.error(f"XiaoYi: WebSocket connection error: {e}")
            self._connected = False
            raise

    async def _send_init_message(self) -> None:
        """Send init message to server."""
        if not self._ws:
            return

        init_msg = {
            "msgType": "clawd_bot_init",
            "agentId": self.agent_id,
        }

        try:
            await self._ws.send_json(init_msg)
        except Exception as e:
            logger.error(f"XiaoYi: Failed to send init message: {e}")

    async def _heartbeat_loop(self) -> None:
        """Send heartbeat messages periodically."""
        while self._connected and self._ws:
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL)

                if not self._connected or not self._ws:
                    break

                heartbeat_msg = {
                    "msgType": "heartbeat",
                    "agentId": self.agent_id,
                }

                await self._ws.send_json(heartbeat_msg)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"XiaoYi: Heartbeat error: {e}")
                break

    async def _receive_loop(self) -> None:
        """Receive and process messages from WebSocket."""
        if not self._ws:
            return

        try:
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._handle_message(msg.data)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(
                        f"XiaoYi: WebSocket error: {self._ws.exception()}",
                    )
                    break
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    logger.info("XiaoYi: WebSocket closed")
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"XiaoYi: Receive loop error: {e}")
        finally:
            self._connected = False
            # Only reconnect if not stopping
            if not self._stopping:
                self._schedule_reconnect()

    async def _handle_message(self, data: str) -> None:
        """Handle incoming WebSocket message."""
        try:
            message = json.loads(data)
            logger.debug(
                "XiaoYi: Received message: "
                f"{json.dumps(message, indent=2)}",
            )

            # Validate agent_id
            if message.get("agentId") and message["agentId"] != self.agent_id:
                logger.warning(
                    "XiaoYi: Mismatched agentId "
                    f"{message['agentId']}, expected {self.agent_id}",
                )
                return

            # Handle clear context
            if (
                message.get("method") == "clearContext"
                or message.get("action") == "clear"
            ):
                await self._handle_clear_context(message)
                return

            # Handle tasks cancel
            if (
                message.get("method") == "tasks/cancel"
                or message.get("action") == "tasks/cancel"
            ):
                await self._handle_tasks_cancel(message)
                return

            # Handle A2A request
            if message.get("method") == "message/stream":
                await self._handle_a2a_request(message)

        except json.JSONDecodeError as e:
            logger.error(f"XiaoYi: Failed to parse message: {e}")
        except Exception as e:
            logger.error(f"XiaoYi: Error handling message: {e}", exc_info=True)

    async def _handle_a2a_request(self, message: Dict[str, Any]) -> None:
        """Handle A2A request message."""
        try:
            session_id = message.get("params", {}).get(
                "sessionId",
            ) or message.get("sessionId")
            task_id = message.get("params", {}).get("id") or message.get("id")

            if not session_id:
                logger.warning("XiaoYi: No sessionId in message")
                return

            self._session_task_map[session_id] = task_id

            # Extract content parts
            text_parts: List[str] = []
            content_parts: List[Any] = []
            params = message.get("params", {})
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

            if self._enqueue:
                self._enqueue(native)
            else:
                logger.warning("XiaoYi: _enqueue not set, message dropped")

        except Exception as e:
            logger.error(
                f"XiaoYi: Error handling A2A request: {e}",
                exc_info=True,
            )

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

    async def _handle_clear_context(self, message: Dict[str, Any]) -> None:
        """Handle clear context message."""
        session_id = message.get("sessionId") or ""
        request_id = message.get("id") or ""

        logger.info(f"XiaoYi: Clear context for session {session_id}")

        # Send clear response
        await self._send_clear_context_response(request_id, session_id)

        # Clean up session
        if session_id:
            self._session_task_map.pop(session_id, None)

    async def _handle_tasks_cancel(self, message: Dict[str, Any]) -> None:
        """Handle tasks cancel message."""
        session_id = message.get("sessionId") or ""
        request_id = message.get("id") or ""
        task_id = message.get("taskId") or request_id

        logger.info(f"XiaoYi: Cancel task {task_id} for session {session_id}")

        # Send cancel response
        await self._send_tasks_cancel_response(request_id, session_id)

    async def _send_clear_context_response(
        self,
        request_id: str,
        session_id: str,
        success: bool = True,
    ) -> None:
        """Send clear context response."""
        if not self._ws or not self._connected:
            return

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

        try:
            await self._ws.send_json(msg)
        except Exception as e:
            logger.error(f"XiaoYi: Failed to send clear context response: {e}")

    async def _send_tasks_cancel_response(
        self,
        request_id: str,
        session_id: str,
        success: bool = True,
    ) -> None:
        """Send tasks cancel response."""
        if not self._ws or not self._connected:
            return

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

        try:
            await self._ws.send_json(msg)
        except Exception as e:
            logger.error(f"XiaoYi: Failed to send cancel response: {e}")

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
            "XiaoYi: Reconnecting in "
            f"{delay}s (attempt {self._reconnect_attempts})",
        )

        async def reconnect():
            await asyncio.sleep(delay)
            if self._stopping or self._connected:
                return

            # Clean up old session before reconnecting
            await self._cleanup_session()

            try:
                await self._connect()
                logger.info("XiaoYi: Reconnected successfully")
            except Exception as e:
                logger.error(f"XiaoYi: Reconnect failed: {e}")
                self._schedule_reconnect()

        asyncio.create_task(reconnect())

    async def _cleanup_session(self) -> None:
        """Clean up WebSocket and session."""
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

    async def stop(self) -> None:
        """Stop WebSocket connection."""
        logger.info("XiaoYi: Stopping channel...")

        self._stopping = True  # Prevent reconnect during stop
        self._connected = False

        # Cancel tasks
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None

        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            self._receive_task = None

        # Close WebSocket
        if self._ws:
            await self._ws.close()
            self._ws = None

        # Close session
        if self._session:
            await self._session.close()
            self._session = None

        # Unregister from active connections
        await self._unregister_connection()

        # Keep _stopping = True to prevent any reconnection attempts
        # This channel instance will not be reused after stop
        logger.info("XiaoYi: Channel stopped")

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send text message via WebSocket.

        For A2A protocol with append=true, messages are chunked
        at TEXT_CHUNK_LIMIT characters to avoid WebSocket disconnection
        on large messages.
        """
        if not self.enabled or not self._ws or not self._connected:
            logger.warning("XiaoYi: Cannot send - not connected")
            return

        meta = meta or {}
        session_id = meta.get("session_id") or to_handle
        task_id = meta.get("task_id") or self._session_task_map.get(session_id)

        if not task_id:
            logger.warning(f"XiaoYi: No task_id for session {session_id}")
            return

        # Don't send empty text
        if not text or not text.strip():
            return

        # Get or create message ID for this session
        message_id = meta.get("message_id", str(uuid.uuid4()))

        # Chunk text if too large
        chunks = self._chunk_text(text)

        for chunk in chunks:
            await self._send_chunk(session_id, task_id, message_id, chunk)

    def _chunk_text(self, text: str) -> List[str]:
        """Split text into chunks of TEXT_CHUNK_LIMIT size."""
        if len(text) <= TEXT_CHUNK_LIMIT:
            return [text]

        chunks = []
        # Try to split at newlines for better readability
        lines = text.split("\n")
        current_chunk = ""

        for line in lines:
            # If single line is too long, split it
            if len(line) > TEXT_CHUNK_LIMIT:
                # First add any accumulated chunk
                if current_chunk:
                    chunks.append(current_chunk.rstrip("\n"))
                    current_chunk = ""

                # Split long line into chunks
                for i in range(0, len(line), TEXT_CHUNK_LIMIT):
                    chunks.append(line[i : i + TEXT_CHUNK_LIMIT])
            else:
                # Check if adding this line would exceed limit
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
        last_chunk: bool = False,
        final: bool = False,
    ) -> Dict[str, Any]:
        """Build artifact-update message for XiaoYi A2A protocol."""
        artifact_id = f"artifact_{uuid.uuid4().hex[:16]}"
        json_rpc_response = {
            "jsonrpc": "2.0",
            "id": message_id,
            "result": {
                "taskId": task_id,
                "kind": "artifact-update",
                "append": True,
                "lastChunk": last_chunk,
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
        if not self._ws or not self._connected:
            return
        msg = self._build_artifact_msg(
            session_id,
            task_id,
            message_id,
            [{"kind": "text", "text": text}],
        )
        try:
            await self._ws.send_json(msg)
        except Exception as e:
            logger.error(f"XiaoYi: Failed to send chunk: {e}")

    async def _send_reasoning_chunk(
        self,
        session_id: str,
        task_id: str,
        message_id: str,
        reasoning_text: str,
    ) -> None:
        """Send a reasoning/thinking chunk via WebSocket."""
        if not self._ws or not self._connected:
            return
        msg = self._build_artifact_msg(
            session_id,
            task_id,
            message_id,
            [{"kind": "reasoningText", "reasoningText": reasoning_text}],
        )
        try:
            await self._ws.send_json(msg)
        except Exception as e:
            logger.error(f"XiaoYi: Failed to send reasoning chunk: {e}")

    async def send_final_message(
        self,
        session_id: str,
        task_id: str,
        message_id: str,
    ) -> None:
        """Send final empty message to end the stream."""
        if not self.enabled or not self._ws or not self._connected:
            return
        msg = self._build_artifact_msg(
            session_id,
            task_id,
            message_id,
            [{"kind": "text", "text": ""}],
            last_chunk=True,
            final=True,
        )
        try:
            await self._ws.send_json(msg)
        except Exception as e:
            logger.error(f"XiaoYi: Failed to send final message: {e}")

    async def send_media(
        self,
        to_handle: str,
        part: OutgoingContentPart,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send media message via WebSocket."""
        if not self.enabled or not self._ws or not self._connected:
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
            last_chunk=True,
            final=True,
        )
        try:
            await self._ws.send_json(msg)
        except Exception as e:
            logger.error(f"XiaoYi: Failed to send media: {e}")

    def _extract_xiaoyi_parts(
        self,
        message: Any,
    ) -> List[Dict[str, Any]]:
        # pylint: disable=too-many-branches,too-many-statements
        # pylint: disable=too-many-nested-blocks
        """Extract parts from message with proper XiaoYi kinds.

        XiaoYi supports:
        - kind="reasoningText": For thinking/reasoning content
        - kind="text": For regular text content
        """
        from agentscope_runtime.engine.schemas.agent_schemas import (
            MessageType,
        )

        msg_type = getattr(message, "type", None)
        content = getattr(message, "content", None) or []
        parts = []

        # Check if this is a reasoning/thinking message type
        if msg_type == MessageType.REASONING:
            # Check if thinking is filtered
            if self._render_style.filter_thinking:
                return []
            for c in content:
                text = getattr(c, "text", None)
                if text:
                    # Add newline separator for each thinking content
                    parts.append(
                        {
                            "kind": "reasoningText",
                            "reasoningText": text + "\n",
                        },
                    )
            return parts

        # Process each content item
        for c in content:
            ctype = getattr(c, "type", None)

            # Handle thinking blocks (inside DATA content as dict)
            if ctype == ContentType.DATA:
                data = getattr(c, "data", None)
                if isinstance(data, dict):
                    # Check for thinking content in blocks
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
                                    # Add newline separator
                                    parts.append(
                                        {
                                            "kind": "reasoningText",
                                            "reasoningText": thinking_text
                                            + "\n",
                                        },
                                    )

            # Handle TEXT type (regular message content)
            # Add leading newline to separate from previous content
            if ctype == ContentType.TEXT and getattr(c, "text", None):
                text = c.text
                # Add leading newlines if not already present
                if not text.startswith("\n"):
                    text = "\n\n" + text
                parts.append({"kind": "text", "text": text})

            # Handle REFUSAL type
            elif ctype == ContentType.REFUSAL and getattr(c, "refusal", None):
                parts.append({"kind": "text", "text": c.refusal})

        # Handle tool call/output messages
        # with complete, independent formatting
        # Check if tool messages should be filtered
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
            # Tool call: format as "🔧 **name**" + code block with args
            for c in content:
                if getattr(c, "type", None) != ContentType.DATA:
                    continue
                data = getattr(c, "data", None)
                if not isinstance(data, dict):
                    continue
                name = data.get("name") or "tool"
                args = data.get("arguments") or "{}"
                # Complete, independent formatting for each tool call
                formatted = f"\n\n🔧 **{name}**\n```\n{args}\n```\n"
                parts.append({"kind": "text", "text": formatted})
            return parts

        if msg_type in (
            MessageType.FUNCTION_CALL_OUTPUT,
            MessageType.PLUGIN_CALL_OUTPUT,
            MessageType.MCP_TOOL_CALL_OUTPUT,
        ):
            # Tool output: format as "✅ **name**" + code block with result
            for c in content:
                if getattr(c, "type", None) != ContentType.DATA:
                    continue
                data = getattr(c, "data", None)
                if not isinstance(data, dict):
                    continue
                name = data.get("name") or "tool"
                output = data.get("output", "")

                # Parse output and format as JSON
                try:
                    if isinstance(output, str):
                        parsed = json.loads(output)
                    else:
                        parsed = output

                    # Handle list format like [{'type': 'text', 'text': '...'}]
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
                            parsed,
                            ensure_ascii=False,
                            indent=2,
                        )
                    else:
                        output_str = str(parsed)
                except (json.JSONDecodeError, TypeError):
                    output_str = str(output) if output else ""

                # Truncate if too long
                if len(output_str) > 500:
                    output_str = output_str[:500] + "..."

                # Escape backticks in output
                # to avoid breaking code blocks
                output_str = output_str.replace("```", "\\`\\`\\`")

                # Complete, independent formatting
                # for each tool output
                # Ensure code block is properly closed
                formatted = f"\n\n✅ **{name}**\n```\n{output_str}\n```\n"
                parts.append({"kind": "text", "text": formatted})
            return parts

        # If no parts extracted, use renderer as fallback
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
        # pylint: disable=too-many-branches,too-many-nested-blocks
        """Send parts with XiaoYi-specific format.

        Each part is a dict with:
        - kind: "text" or "reasoningText"
        - text/reasoningText: the content string
        """
        if not self.enabled or not self._ws or not self._connected:
            logger.warning("XiaoYi: Cannot send - not connected")
            return

        meta = meta or {}
        session_id = meta.get("session_id") or to_handle
        task_id = meta.get("task_id") or self._session_task_map.get(session_id)

        if not task_id:
            logger.warning(f"XiaoYi: No task_id for session {session_id}")
            return

        message_id = meta.get("message_id", str(uuid.uuid4()))

        # Build artifact parts for XiaoYi
        artifact_parts = []
        for part in parts:
            kind = part.get("kind", "text")
            if kind == "reasoningText":
                artifact_parts.append(
                    {
                        "kind": "reasoningText",
                        "reasoningText": part.get("reasoningText", ""),
                    },
                )
            elif kind == "text":
                artifact_parts.append(
                    {
                        "kind": "text",
                        "text": part.get("text", ""),
                    },
                )

        if not artifact_parts:
            return

        # Check if any part exceeds chunk limit
        max_part_len = max(
            len(p.get("text", "") or p.get("reasoningText", ""))
            for p in artifact_parts
        )

        if max_part_len > TEXT_CHUNK_LIMIT:
            # Chunk each part separately, preserving kind
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
                    # Send small parts as-is
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

        # Send as single message with proper parts
        msg = self._build_artifact_msg(
            session_id,
            task_id,
            message_id,
            artifact_parts,
        )
        try:
            await self._ws.send_json(msg)
        except Exception as e:
            logger.error(f"XiaoYi: Failed to send parts: {e}")

    async def on_event_message_completed(
        self,
        request: "AgentRequest",
        to_handle: str,
        event: Any,
        send_meta: Dict[str, Any],
    ) -> None:
        """Override to handle XiaoYi-specific message formatting.

        Separates thinking/reasoning content from regular text.
        """
        # Extract parts with proper kinds
        parts = self._extract_xiaoyi_parts(event)

        if not parts:
            logger.debug("XiaoYi: No parts to send for message")
            return

        # Send with XiaoYi format
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

            # Send final message to end the stream
            task_id = send_meta.get("task_id") or self._session_task_map.get(
                session_id,
            )
            message_id = str(uuid.uuid4())

            if task_id and session_id:
                await self.send_final_message(session_id, task_id, message_id)

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
