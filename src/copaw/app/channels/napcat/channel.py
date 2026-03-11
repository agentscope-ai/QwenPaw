# -*- coding: utf-8 -*-
"""NapCat Channel for CoPaw.

NapCat 基于 OneBot 11 协议，使用 WebSocket 接收消息，HTTP API 发送消息。
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp
import websocket

from agentscope_runtime.engine.schemas.agent_schemas import (
    RunStatus,
    TextContent,
    ImageContent,
    VideoContent,
    AudioContent,
    FileContent,
    ContentType,
)

from ..base import (
    BaseChannel,
    OnReplySent,
    OutgoingContentPart,
    ProcessHandler,
)

logger = logging.getLogger(__name__)

# Reconnect settings
RECONNECT_DELAYS = [1, 2, 5, 10, 30, 60]
MAX_RECONNECT_ATTEMPTS = 100
QUICK_DISCONNECT_THRESHOLD = 5
MAX_QUICK_DISCONNECT_COUNT = 3

# Default paths
_DEFAULT_MEDIA_DIR = Path("~/.copaw/media/napcat").expanduser()


class NapCatApiError(RuntimeError):
    """HTTP error returned by NapCat API."""

    def __init__(self, path: str, status: int, data: Any, message: str = None):
        self.path = path
        self.status = status
        self.data = data
        self.message = message
        super().__init__(f"NapCat API {path} {status}: {message or data}")


def _as_bool(value: Any) -> bool:
    """Convert value to boolean."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _parse_message(message: Any) -> List[OutgoingContentPart]:  # noqa: R0912
    """Parse OneBot 11 message to content parts.

    Handles:
    - Plain text (str)
    - Array of message segments
    - Message segments: text, image, record, video, file, etc.
    """
    parts: List[OutgoingContentPart] = []

    if not message:
        return parts

    # If message is a string (plain text)
    if isinstance(message, str):
        if message.strip():
            parts.append(
                TextContent(
                    type=ContentType.TEXT,
                    text=message.strip(),
                ),
            )
        return parts

    # If message is a list of segments
    if isinstance(message, list):
        for segment in message:
            seg_type = segment.get("type", "")
            seg_data = segment.get("data", {})

            if seg_type == "text":
                text = seg_data.get("text", "").strip()
                if text:
                    parts.append(TextContent(type=ContentType.TEXT, text=text))

            elif seg_type == "image":
                # Image can be file path, URL, or base64
                image_data = seg_data.get("file", seg_data.get("url", ""))
                if image_data:
                    parts.append(
                        ImageContent(
                            type=ContentType.IMAGE,
                            image_url=image_data,
                        ),
                    )

            elif seg_type == "record":  # Voice
                record_data = seg_data.get("file", seg_data.get("url", ""))
                if record_data:
                    parts.append(
                        AudioContent(
                            type=ContentType.AUDIO,
                            data=record_data,
                        ),
                    )

            elif seg_type == "video":
                video_data = seg_data.get("file", seg_data.get("url", ""))
                if video_data:
                    parts.append(
                        VideoContent(
                            type=ContentType.VIDEO,
                            video_url=video_data,
                        ),
                    )

            elif seg_type == "file":
                file_data = seg_data.get("file", seg_data.get("url", ""))
                file_name = seg_data.get("name", "file")
                if file_data:
                    parts.append(
                        FileContent(
                            type=ContentType.FILE,
                            filename=file_name,
                            file_url=file_data,
                        ),
                    )

    return parts


def _build_message_segment(text: str, auto_escape: bool = True) -> Any:
    """Build OneBot 11 message segment from text.

    Args:
        text: Message text
        auto_escape: Whether to escape special characters

    Returns:
        Message segment (string or list of segments)
    """
    if auto_escape:
        # Simple escape for CQ codes
        text = text.replace("&", "&amp;")
        text = text.replace("[", "&#91;")
        text = text.replace("]", "&#93;")
    return text


async def _api_request(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    access_token: str,
    method: str,
    path: str,
    body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Make HTTP API request to NapCat."""
    url = f"http://{host}:{port}{path}"
    headers = {"Content-Type": "application/json"}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"

    kwargs: Dict[str, Any] = {"headers": headers}
    if body is not None:
        kwargs["json"] = body

    async with session.request(method, url, **kwargs) as resp:
        data = await resp.json()
        if resp.status >= 400:
            raise NapCatApiError(path=path, status=resp.status, data=data)
        # Check OneBot retcode and status
        retcode = data.get("retcode", 0)
        status = data.get("status", "ok")
        if retcode != 0 or status == "failed":
            msg = data.get("message") or data.get("wording", "Unknown error")
            raise NapCatApiError(
                path=path,
                status=resp.status,
                data=data,
                message=msg,
            )
        return data


async def _send_group_message(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    access_token: str,
    group_id: str,
    message: Any,
    auto_escape: bool = True,
) -> int:
    """Send message to group.

    Returns:
        message_id on success
    """
    body = {
        "group_id": group_id,
        "message": message,
        "auto_escape": auto_escape,
    }
    result = await _api_request(
        session,
        host,
        port,
        access_token,
        "POST",
        "/send_group_msg",
        body,
    )
    return (result.get("data") or {}).get("message_id", 0)


async def _send_private_message(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    access_token: str,
    user_id: str,
    message: Any,
    auto_escape: bool = True,
) -> int:
    """Send private message.

    Returns:
        message_id on success
    """
    body = {
        "user_id": user_id,
        "message": message,
        "auto_escape": auto_escape,
    }
    result = await _api_request(
        session,
        host,
        port,
        access_token,
        "POST",
        "/send_private_msg",
        body,
    )
    return (result.get("data") or {}).get("message_id", 0)


async def _get_login_info(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    access_token: str,
) -> Dict[str, Any]:
    """Get login info."""
    result = await _api_request(
        session,
        host,
        port,
        access_token,
        "POST",
        "/get_login_info",
        None,
    )
    return result.get("data", {})


async def _get_group_list(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    access_token: str,
) -> List[Dict[str, Any]]:
    """Get group list."""
    result = await _api_request(
        session,
        host,
        port,
        access_token,
        "POST",
        "/get_group_list",
        None,
    )
    return result.get("data", [])


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
            Path(media_dir).expanduser() if media_dir else _DEFAULT_MEDIA_DIR
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
        # Handle both dict and Pydantic model
        if hasattr(config, "get"):
            # It's a dict
            enabled = config.get("enabled", False)
            host = config.get("host", "127.0.0.1")
            port = config.get("port", 3000)
            ws_port = config.get("ws_port", 3001)
            access_token = config.get("access_token", "")
            bot_prefix = config.get("bot_prefix", "")
            dm_policy = config.get("dm_policy", "open")
            group_policy = config.get("group_policy", "open")
            allow_from = config.get("allow_from", [])
            deny_message = config.get("deny_message", "")
            media_dir = config.get("media_dir", "")
        else:
            # It's a Pydantic model
            enabled = getattr(config, "enabled", False)
            host = getattr(config, "host", "127.0.0.1")
            port = getattr(config, "port", 3000)
            ws_port = getattr(config, "ws_port", 3001)
            access_token = getattr(config, "access_token", "")
            bot_prefix = getattr(config, "bot_prefix", "")
            dm_policy = getattr(config, "dm_policy", "open")
            group_policy = getattr(config, "group_policy", "open")
            allow_from = getattr(config, "allow_from", [])
            deny_message = getattr(config, "deny_message", "")
            media_dir = getattr(config, "media_dir", "")

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

    def _should_process(
        self,
        user_id: str,
        group_id: Optional[str] = None,
    ) -> bool:
        """Check if the message should be processed based on policy."""
        # Check allow_from list
        if self.allow_from and user_id not in self.allow_from:
            return False

        # Check group policy
        if group_id:
            if self.group_policy == "deny":
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
                await _send_group_message(
                    self._http,
                    self.host,
                    self.port,
                    self.access_token,
                    group_id,
                    text,
                    auto_escape=True,
                )
            except Exception as e:
                logger.exception(
                    f"NapCat send to group {group_id} failed: {e}",
                )
        else:
            # Private message
            user_id = meta.get("user_id") or to_handle
            try:
                await _send_private_message(
                    self._http,
                    self.host,
                    self.port,
                    self.access_token,
                    user_id,
                    text,
                    auto_escape=True,
                )
            except Exception as e:
                logger.exception(
                    "NapCat send to user %s failed: %s",
                    user_id,
                    e,
                )

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

        # Check policy
        if not self._should_process(user_id, group_id):
            return None

        # Parse message to content parts
        content_parts = _parse_message(raw_message)

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

    async def consume_one(self, payload: Any) -> None:  # noqa: R0912,R0915
        """Process one AgentRequest from queue."""
        request = payload
        if getattr(request, "input", None):
            session_id = getattr(request, "session_id", "") or ""
            contents = list(
                getattr(request.input[0], "content", None) or [],
            )
            should_process, merged = self._apply_no_text_debounce(
                session_id,
                contents,
            )
            if not should_process:
                return
            if merged:
                if hasattr(request.input[0], "model_copy"):
                    request.input[0] = request.input[0].model_copy(
                        update={"content": merged},
                    )
                else:
                    request.input[0].content = merged

        try:
            send_meta = getattr(request, "channel_meta", None) or {}
            send_meta.setdefault("bot_prefix", self.bot_prefix)
            # Add session_id to send_meta so send method can access it
            send_meta["session_id"] = getattr(request, "session_id", "")

            # For group messages, use group_id; otherwise use user_id
            group_id = send_meta.get("group_id")
            message_type = send_meta.get("message_type")

            # Try to get group_id from session_id if not present
            if not group_id and message_type == "group":
                session_id = getattr(request, "session_id", "") or ""
                if session_id.startswith("napcat:group:"):
                    group_id = session_id.split(":")[-1]
            if group_id:
                to_handle = group_id
            else:
                to_handle = request.user_id or ""
            last_response = None
            accumulated_parts: List[OutgoingContentPart] = []
            event_count = 0

            async for event in self._process(request):
                event_count += 1
                obj = getattr(event, "object", None)
                status = getattr(event, "status", None)
                ev_type = getattr(event, "type", None)
                logger.debug(
                    "napcat event #%s: object=%s status=%s type=%s",
                    event_count,
                    obj,
                    status,
                    ev_type,
                )
                if obj == "message" and status == RunStatus.Completed:
                    parts = self._message_to_content_parts(event)
                    logger.info(
                        "napcat completed message: type=%s parts_count=%s",
                        ev_type,
                        len(parts),
                    )
                    accumulated_parts.extend(parts)
                elif obj == "response":
                    last_response = event

            err_msg = self._get_response_error_message(last_response)
            if err_msg:
                err_text = self.bot_prefix + f"Error: {err_msg}"
                await self.send_content_parts(
                    to_handle,
                    [TextContent(type=ContentType.TEXT, text=err_text)],
                    send_meta,
                )
            elif accumulated_parts:
                await self.send_content_parts(
                    to_handle,
                    accumulated_parts,
                    send_meta,
                )
            elif last_response is None:
                err_text = (
                    self.bot_prefix + "An error occurred while processing."
                )
                await self.send_content_parts(
                    to_handle,
                    [TextContent(type=ContentType.TEXT, text=err_text)],
                    send_meta,
                )
            if self._on_reply_sent:
                self._on_reply_sent(
                    self.channel,
                    to_handle,
                    request.session_id or f"{self.channel}:{to_handle}",
                )
        except Exception as e:
            logger.exception("napcat process/reply failed")
            err_msg = str(e).strip() or "An error occurred while processing."
            try:
                fallback_handle = getattr(request, "user_id", "")
                await self.send_content_parts(
                    fallback_handle,
                    [
                        TextContent(
                            type=ContentType.TEXT,
                            text=f"Error: {err_msg}",
                        ),
                    ],
                    getattr(request, "channel_meta", None) or {},
                )
            except Exception:
                logger.exception("send error message failed")

    def _run_ws_forever(self) -> None:
        """Run WebSocket client to receive events."""
        reconnect_attempts = 0
        last_connect_time = 0.0
        quick_disconnect_count = 0

        def connect() -> bool:
            nonlocal reconnect_attempts, last_connect_time, quick_disconnect_count  # noqa: E501
            if self._stop_event.is_set():
                return False

            ws_url = f"ws://{self.host}:{self.ws_port}/ws"
            headers = {}
            if self.access_token:
                headers["Authorization"] = f"Bearer {self.access_token}"

            logger.info(f"napcat connecting to {ws_url}")

            try:
                ws = websocket.create_connection(
                    ws_url,
                    header=headers,
                    timeout=30,
                )
            except Exception as e:
                logger.warning(f"napcat ws connect failed: {e}")
                return True

            current_ws = ws

            try:
                while not self._stop_event.is_set():
                    try:
                        raw = current_ws.recv()
                    except websocket.WebSocketTimeoutException:
                        continue
                    except websocket.WebSocketConnectionClosedException:
                        break

                    if not raw:
                        break

                    try:
                        payload = json.loads(raw)
                    except json.JSONDecodeError:
                        logger.warning(f"napcat invalid JSON: {raw[:200]}")
                        continue

                    # Handle OneBot 11 event
                    self._handle_event(payload)

            except Exception as e:
                logger.exception(f"napcat ws loop: {e}")
            finally:
                try:
                    current_ws.close()
                except Exception:
                    pass

            # Calculate reconnect delay
            if (
                last_connect_time
                and (time.time() - last_connect_time)
                < QUICK_DISCONNECT_THRESHOLD
            ):
                quick_disconnect_count += 1
                if quick_disconnect_count >= MAX_QUICK_DISCONNECT_COUNT:
                    quick_disconnect_count = 0
                    delay = 60  # Rate limit
                else:
                    delay = RECONNECT_DELAYS[
                        min(reconnect_attempts, len(RECONNECT_DELAYS) - 1)
                    ]
            else:
                quick_disconnect_count = 0
                delay = RECONNECT_DELAYS[
                    min(reconnect_attempts, len(RECONNECT_DELAYS) - 1)
                ]

            reconnect_attempts += 1
            if reconnect_attempts >= MAX_RECONNECT_ATTEMPTS:
                logger.error("napcat max reconnect attempts reached")
                return False

            logger.info(
                f"napcat reconnecting in {delay}s (attempt {reconnect_attempts})",  # noqa: E501
            )
            self._stop_event.wait(timeout=delay)
            return not self._stop_event.is_set()

        while connect():
            pass
        self._stop_event.set()
        logger.info("napcat ws thread stopped")

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
            self._login_info = await _get_login_info(
                self._http,
                self.host,
                self.port,
                self.access_token,
            )
            logger.info(f"napcat logged in as: {self._login_info}")

            self._group_list = await _get_group_list(
                self._http,
                self.host,
                self.port,
                self.access_token,
            )
            logger.info(f"napcat joined {len(self._group_list)} groups")
        except Exception as e:
            logger.warning(f"napcat initial fetch failed: {e}")

        # Start WebSocket thread
        self._ws_thread = threading.Thread(
            target=self._run_ws_forever,
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
