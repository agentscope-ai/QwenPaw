# -*- coding: utf-8 -*-
# pylint: disable=too-many-branches,too-many-statements
"""QQ Channel.

QQ uses WebSocket for incoming events and HTTP API for replies.
No request-reply coupling: handler enqueues Incoming, consumer processes
and sends reply via send_c2c_message / send_channel_message /
send_group_message.
Rich media read (images, videos, files)
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import aiohttp

from agentscope_runtime.engine.schemas.agent_schemas import (
    TextContent,
    ImageContent,
    VideoContent,
    AudioContent,
    FileContent,
    ContentType,
)

from ....config.config import QQConfig as QQChannelConfig
from ....constant import WORKING_DIR
from ....exceptions import ChannelError

from ..base import (
    BaseChannel,
    OnReplySent,
    OutgoingContentPart,
    ProcessHandler,
)
from ..utils import file_url_to_local_path, split_text

if TYPE_CHECKING:
    import concurrent.futures

logger = logging.getLogger(__name__)

# QQ Bot WebSocket op codes
OP_DISPATCH = 0
OP_HEARTBEAT = 1
OP_IDENTIFY = 2
OP_RESUME = 6
OP_RECONNECT = 7
OP_INVALID_SESSION = 9
OP_HELLO = 10
OP_HEARTBEAT_ACK = 11

# Intents
INTENT_PUBLIC_GUILD_MESSAGES = 1 << 30
INTENT_DIRECT_MESSAGE = 1 << 12
INTENT_GROUP_AND_C2C = 1 << 25
INTENT_GUILD_MEMBERS = 1 << 1

RECONNECT_DELAYS = [1, 2, 5, 10, 30, 60]
RATE_LIMIT_DELAY = 60
QUICK_DISCONNECT_THRESHOLD = 5
MAX_QUICK_DISCONNECT_COUNT = 3

DEFAULT_API_BASE = "https://api.sgroup.qq.com"
TOKEN_URL = "https://bots.qq.com/app/getAppAccessToken"
_URL_PATTERN = re.compile(r"https?://[^\s]+|www\.[^\s]+", re.IGNORECASE)
# More aggressive pattern: also catches bare domains like 12306.cn, google.com
_BARE_DOMAIN_PATTERN = re.compile(
    r"https?://[^\s]+|www\.[^\s]+"
    r"|\b[\w][\w.-]*\."
    r"(?:com|cn|org|net|edu|gov|io|co|cc|tv|me|info|biz|app|dev|top|xyz"
    r"|site|vip|shop|tech|club|pro|live|mobi|asia|wiki)"
    r"(?:\.[a-z]{2,3})?\b(?:/[^\s]*)?",
    re.IGNORECASE,
)
_IMAGE_TAG_PATTERN = re.compile(r"\[Image: (https?://[^\]]+)\]", re.IGNORECASE)

# Rich media paths
_DEFAULT_MEDIA_DIR = WORKING_DIR / "media" / "qq"


# ---------------------------------------------------------------------------
# Message event spec: describes how each WS event type maps to meta fields
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _MessageEventSpec:
    """Describes the per-event-type differences for WS message dispatch."""

    message_type: str
    sender_keys: Tuple[str, ...]
    extra_meta_keys: Tuple[str, ...] = ()


_MESSAGE_EVENT_SPECS: Dict[str, _MessageEventSpec] = {
    "C2C_MESSAGE_CREATE": _MessageEventSpec(
        message_type="c2c",
        sender_keys=("user_openid", "id"),
    ),
    "AT_MESSAGE_CREATE": _MessageEventSpec(
        message_type="guild",
        sender_keys=("id", "username"),
        extra_meta_keys=("channel_id", "guild_id"),
    ),
    "DIRECT_MESSAGE_CREATE": _MessageEventSpec(
        message_type="dm",
        sender_keys=("id", "username"),
        extra_meta_keys=("channel_id", "guild_id"),
    ),
    "GROUP_AT_MESSAGE_CREATE": _MessageEventSpec(
        message_type="group",
        sender_keys=("member_openid", "id"),
        extra_meta_keys=("group_openid",),
    ),
}


# ---------------------------------------------------------------------------
# WebSocket state & heartbeat helpers
# ---------------------------------------------------------------------------


@dataclass
class _WSState:
    """Mutable state carried across reconnect attempts."""

    session_id: Optional[str] = None
    last_seq: Optional[int] = None
    reconnect_attempts: int = 0
    last_connect_time: float = 0.0
    quick_disconnect_count: int = 0
    identify_fail_count: int = 0
    should_refresh_token: bool = False


class _HeartbeatController:
    """Manages recurring WebSocket heartbeat via threading.Timer."""

    def __init__(
        self,
        ws: Any,
        stop_event: threading.Event,
        state: _WSState,
    ) -> None:
        self._ws = ws
        self._stop_event = stop_event
        self._state = state
        self._timer: Optional[threading.Timer] = None
        self._interval: Optional[float] = None

    def start(self, interval_ms: float) -> None:
        self._interval = interval_ms
        self._schedule()

    def stop(self) -> None:
        if self._timer:
            self._timer.cancel()
            self._timer = None

    def _schedule(self) -> None:
        if self._interval is None or self._stop_event.is_set():
            return
        self._timer = threading.Timer(
            self._interval / 1000.0,
            self._send_ping,
        )
        self._timer.daemon = True
        self._timer.start()

    def _send_ping(self) -> None:
        if self._stop_event.is_set():
            return
        try:
            if self._ws.connected:
                self._ws.send(
                    json.dumps(
                        {"op": OP_HEARTBEAT, "d": self._state.last_seq},
                    ),
                )
                logger.debug("qq heartbeat sent")
        except Exception:
            pass
        self._schedule()


class QQApiError(RuntimeError):
    """HTTP error returned by QQ API."""

    def __init__(self, path: str, status: int, data: Any):
        self.path = path
        self.status = status
        self.data = data
        super().__init__(f"API {path} {status}: {data}")


def _sanitize_qq_text(text: str) -> tuple[str, bool]:
    """QQ API disallows URL links in plain messages.

    Return the sanitized text and whether any URL was removed.
    """
    if not text:
        return "", False
    sanitized, count = _URL_PATTERN.subn("[链接已省略]", text)
    return sanitized, count > 0


def _aggressive_sanitize_qq_text(text: str) -> tuple[str, bool]:
    """More aggressive URL stripping – also catches bare domain patterns.

    Used as a second-level fallback when QQ still rejects the message
    because of URL-like content that ``_sanitize_qq_text`` did not catch.
    """
    if not text:
        return "", False
    sanitized, count = _BARE_DOMAIN_PATTERN.subn("[链接已省略]", text)
    return sanitized, count > 0


def _is_url_content_error(exc: Exception) -> bool:
    """Return *True* if QQ rejected the message because it contains a URL."""
    if not isinstance(exc, QQApiError):
        return False
    try:
        payload_text = json.dumps(exc.data, ensure_ascii=False).lower()
    except Exception:
        payload_text = str(exc.data).lower()
    return (
        "304003" in payload_text
        or "40034028" in payload_text
        or "不允许包含url" in payload_text
    )


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _should_plaintext_fallback_from_markdown(exc: Exception) -> bool:
    """Only fallback for explicit markdown payload validation failures."""
    if not isinstance(exc, QQApiError):
        return False
    if exc.status < 400 or exc.status >= 500:
        return False
    try:
        payload_text = json.dumps(exc.data, ensure_ascii=False).lower()
    except Exception:
        payload_text = str(exc.data).lower()

    # Check for markdown-related error messages or codes
    return (
        "markdown" in payload_text
        or "msg_type" in payload_text
        or "msg type" in payload_text
        or "message type" in payload_text
        or "50056" in payload_text  # 不允许发送原生 markdown
        or "不允许发送原生 markdown" in payload_text
        or "40034012" in payload_text  # err_code for markdown not allowed
    )


def _get_api_base() -> str:
    """API root address (e.g. sandbox: https://sandbox.api.sgroup.qq.com)"""
    return os.getenv("QQ_API_BASE", DEFAULT_API_BASE).rstrip("/")


def _get_channel_url_sync(access_token: str) -> str:
    import urllib.error
    import urllib.request

    url = f"{_get_api_base()}/gateway"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"QQBot {access_token}",
            "Content-Type": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode() if e.fp else ""
        except Exception:
            pass
        msg = f"HTTP {e.code}: {e.reason}"
        if body:
            msg += f" | body: {body[:500]}"
        raise ChannelError(
            channel_name="qq",
            message=f"Failed to get channel url: {msg}",
        ) from e
    except Exception as e:
        raise ChannelError(
            channel_name="qq",
            message=f"Failed to get channel url: {e}",
        ) from e
    channel_url = data.get("url")
    if not channel_url:
        raise ChannelError(
            channel_name="qq",
            message=f"No url in channel response: {data}",
        )
    return channel_url


_msg_seq: Dict[str, int] = {}
_msg_seq_lock = threading.Lock()


def _get_next_msg_seq(msg_id: str) -> int:
    with _msg_seq_lock:
        n = _msg_seq.get(msg_id, 0) + 1
        _msg_seq[msg_id] = n
        if len(_msg_seq) > 1000:
            for k in list(_msg_seq.keys())[:500]:
                del _msg_seq[k]
        return n


async def _api_request_async(
    session: Any,
    access_token: str,
    method: str,
    path: str,
    body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    url = f"{_get_api_base()}{path}"
    kwargs = {
        "headers": {
            "Authorization": f"QQBot {access_token}",
            "Content-Type": "application/json",
        },
    }
    if body is not None:
        kwargs["json"] = body
    async with session.request(method, url, **kwargs) as resp:
        data = await resp.json()
        if resp.status >= 400:
            raise QQApiError(path=path, status=resp.status, data=data)
        return data


async def _send_message_async(
    session: Any,
    access_token: str,
    path: str,
    content: str,
    msg_id: Optional[str] = None,
    use_markdown: bool = False,
    use_msg_seq: bool = True,
    seq_key: str = "",
) -> None:
    """Send a text message to QQ API.

    Args:
        path: API path, e.g. /v2/users/{openid}/messages
        use_msg_seq: c2c and group need msg_seq+msg_type;
                     channel messages do not.
        seq_key: key for msg_seq counter (e.g. msg_id or "c2c")
    """
    if use_markdown:
        body: Dict[str, Any] = {
            "markdown": {"content": content},
        }
        if use_msg_seq:
            body["msg_type"] = 2
    else:
        body = {"content": content}
        if use_msg_seq:
            body["msg_type"] = 0
    if use_msg_seq:
        body["msg_seq"] = _get_next_msg_seq(
            msg_id or seq_key,
        )
    if msg_id:
        body["msg_id"] = msg_id
    await _api_request_async(
        session,
        access_token,
        "POST",
        path,
        body,
    )


_MEDIA_PATH_PREFIX = {
    "c2c": "/v2/users",
    "group": "/v2/groups",
}


def _media_path(
    message_type: str,
    openid: str,
    suffix: str,
) -> Optional[str]:
    """Build media API path or return None if unsupported."""
    prefix = _MEDIA_PATH_PREFIX.get(message_type)
    if not prefix:
        return None
    return f"{prefix}/{openid}/{suffix}"


async def _upload_media_async(
    session: Any,
    access_token: str,
    openid: str,
    media_type: int,
    url: str = "",
    message_type: str = "c2c",
    file_data: str = "",
    file_name: str = "",
) -> Optional[str]:
    """Upload media to QQ rich media server.

    Supports two modes:
    - URL mode: provide ``url`` for QQ to fetch the resource.
    - Base64 mode: provide ``file_data`` (base64-encoded binary).

    Returns file_info if success, None otherwise.
    """
    path = _media_path(message_type, openid, "files")
    if not path:
        logger.warning("Unsupported type for media upload: %s", message_type)
        return None
    body: Dict[str, Any] = {
        "file_type": media_type,
        "srv_send_msg": False,
    }
    if file_data:
        body["file_data"] = file_data
        if file_name:
            body["file_name"] = file_name
    elif url:
        body["url"] = url
    else:
        logger.warning("No url or file_data provided for media upload")
        return None
    try:
        response = await _api_request_async(
            session,
            access_token,
            "POST",
            path,
            body,
        )
        return response.get("file_info")
    except Exception:
        source = url or "file_data"
        logger.exception("Failed to upload media: %s", source)
        return None


async def _send_media_message_async(
    session: Any,
    access_token: str,
    openid: str,
    file_info: str,
    msg_id: Optional[str] = None,
    message_type: str = "c2c",
    filename: Optional[str] = None,
) -> None:
    """Send rich media message.

    Args:
        filename: optional display filename shown to the recipient.
                  Passed via the ``content`` field so QQ renders the
                  file name and extension in the chat bubble.
    """
    path = _media_path(message_type, openid, "messages")
    if not path:
        logger.warning("Unsupported type for media send: %s", message_type)
        return
    body: Dict[str, Any] = {
        "msg_type": 7,
        "media": {"file_info": file_info},
        "msg_seq": _get_next_msg_seq(msg_id or f"{message_type}_media"),
    }
    if filename:
        body["content"] = filename
    if msg_id:
        body["msg_id"] = msg_id
    await _api_request_async(
        session,
        access_token,
        "POST",
        path,
        body,
    )


async def _send_guild_image_async(
    session: Any,
    access_token: str,
    path: str,
    image_url: str,
    msg_id: Optional[str] = None,
) -> None:
    """Send an image in guild/dm via the ``image`` field (URL mode).

    Guild and DM channels do not use the rich-media upload API.
    Instead they accept an ``image`` URL directly in the message body.
    """
    body: Dict[str, Any] = {"image": image_url}
    if msg_id:
        body["msg_id"] = msg_id
    await _api_request_async(
        session,
        access_token,
        "POST",
        path,
        body,
    )


async def _send_guild_image_file_async(
    session: Any,
    access_token: str,
    path: str,
    file_path: str,
    msg_id: Optional[str] = None,
) -> None:
    """Send an image in guild/dm via form-data ``file_image`` upload.

    Used when the image is a local file rather than a URL.
    """
    api_url = f"{_get_api_base()}{path}"
    loop = asyncio.get_running_loop()

    def _read_file():
        with open(file_path, "rb") as fh:
            return fh.read()

    file_bytes = await loop.run_in_executor(None, _read_file)
    data = aiohttp.FormData()
    if msg_id:
        data.add_field("msg_id", msg_id)
    data.add_field(
        "file_image",
        file_bytes,
        filename=Path(file_path).name,
    )
    async with session.post(
        api_url,
        data=data,
        headers={"Authorization": f"QQBot {access_token}"},
    ) as resp:
        resp_data = await resp.json()
        if resp.status >= 400:
            raise QQApiError(path=path, status=resp.status, data=resp_data)


async def _read_file_as_base64(file_path: str) -> str:
    """Read a local file and return its base64-encoded content.

    File I/O is offloaded to a thread pool to avoid blocking the
    event loop.
    """
    loop = asyncio.get_running_loop()

    def _read():
        with open(file_path, "rb") as fh:
            return base64.b64encode(fh.read()).decode("ascii")

    return await loop.run_in_executor(None, _read)


# QQ rich-media file_type constants
_MEDIA_TYPE_IMAGE = 1
_MEDIA_TYPE_VIDEO = 2
_MEDIA_TYPE_AUDIO = 3
_MEDIA_TYPE_FILE = 4


async def _download_qq_file(
    *,
    http_session: aiohttp.ClientSession,
    file_url: str,
    media_dir: Path,
    filename_hint: str = "",
) -> Optional[str]:
    """Download a QQ file to local media_dir; return local path."""
    try:
        if not filename_hint:
            logger.warning("filename is empty")
            return None

        # Sanitize filename to prevent path traversal
        safe_filename = Path(filename_hint).name

        media_dir.mkdir(parents=True, exist_ok=True)
        local_path = media_dir / safe_filename
        async with http_session.get(file_url) as resp:
            if resp.status != 200:
                logger.warning(
                    "qq download failed: status=%s url=%s",
                    resp.status,
                    file_url,
                )
                return None
            content = await resp.read()
            with open(str(local_path), "wb") as f:
                f.write(content)
        return str(local_path)
    except Exception:
        logger.exception("qq download failed for url=%s", file_url)
        return None


class QQChannel(BaseChannel):
    """QQ Channel:
    WebSocket events -> Incoming -> process -> HTTP API reply.
    """

    channel = "qq"

    def __init__(
        self,
        process: ProcessHandler,
        enabled: bool,
        app_id: str,
        client_secret: str,
        bot_prefix: str = "",
        markdown_enabled: bool = True,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
        media_dir: str = "",
        workspace_dir: Path | None = None,
        max_reconnect_attempts: int = 100,
        ack_message: str = "",
    ):
        super().__init__(
            process,
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            filter_thinking=filter_thinking,
        )
        self.enabled = enabled
        self.app_id = app_id
        self.client_secret = client_secret
        self.bot_prefix = bot_prefix
        self._markdown_enabled = markdown_enabled
        self._workspace_dir = (
            Path(workspace_dir).expanduser() if workspace_dir else None
        )
        # Use workspace-specific media dir if workspace_dir is provided
        if not media_dir and self._workspace_dir:
            self._media_dir = self._workspace_dir / "media"
        elif media_dir:
            self._media_dir = Path(media_dir).expanduser()
        else:
            self._media_dir = _DEFAULT_MEDIA_DIR
        self._max_reconnect_attempts = max_reconnect_attempts
        self._ack_message = ack_message

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ws_thread: Optional[threading.Thread] = None
        self._ws: Any = None
        self._stop_event = threading.Event()
        self._account_id = "default"
        self._token_cache: Optional[Dict[str, Any]] = None
        self._token_lock = threading.Lock()

        self._http: Optional[aiohttp.ClientSession] = None

    def _get_access_token_sync(self) -> str:
        """Sync get access_token for WebSocket thread. Instance-level cache."""
        with self._token_lock:
            if (
                self._token_cache
                and time.time() < self._token_cache["expires_at"] - 300
            ):
                return self._token_cache["token"]
        try:
            import urllib.request

            req = urllib.request.Request(
                TOKEN_URL,
                data=json.dumps(
                    {"appId": self.app_id, "clientSecret": self.client_secret},
                ).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
        except Exception as e:
            raise ChannelError(
                channel_name="qq",
                message=f"Failed to get access_token: {e}",
            ) from e
        token = data.get("access_token")
        if not token:
            raise ChannelError(
                channel_name="qq",
                message=f"No access_token in response: {data}",
            )
        expires_in = data.get("expires_in", 7200)
        if isinstance(expires_in, str):
            expires_in = int(expires_in)
        with self._token_lock:
            self._token_cache = {
                "token": token,
                "expires_at": time.time() + expires_in,
            }
        return token

    async def _get_access_token_async(self) -> str:
        """Async get token for send. Instance-level cache."""
        with self._token_lock:
            if (
                self._token_cache
                and time.time() < self._token_cache["expires_at"] - 300
            ):
                return self._token_cache["token"]
        async with self._http.post(
            TOKEN_URL,
            json={"appId": self.app_id, "clientSecret": self.client_secret},
            headers={"Content-Type": "application/json"},
        ) as resp:
            if resp.status >= 400:
                text = await resp.text()
                raise ChannelError(
                    channel_name="qq",
                    message=f"Token request failed {resp.status}: {text}",
                )
            data = await resp.json()
        token = data.get("access_token")
        if not token:
            raise ChannelError(
                channel_name="qq",
                message=f"No access_token: {data}",
            )
        expires_in = data.get("expires_in", 7200)
        if isinstance(expires_in, str):
            expires_in = int(expires_in)
        with self._token_lock:
            self._token_cache = {
                "token": token,
                "expires_at": time.time() + expires_in,
            }
        return token

    def _clear_token_cache(self) -> None:
        with self._token_lock:
            self._token_cache = None

    @classmethod
    def from_env(
        cls,
        process: ProcessHandler,
        on_reply_sent: OnReplySent = None,
    ) -> "QQChannel":
        return cls(
            process=process,
            enabled=os.getenv("QQ_CHANNEL_ENABLED", "1") == "1",
            app_id=os.getenv("QQ_APP_ID", ""),
            client_secret=os.getenv("QQ_CLIENT_SECRET", ""),
            bot_prefix=os.getenv("QQ_BOT_PREFIX", ""),
            markdown_enabled=_as_bool(os.getenv("QQ_MARKDOWN_ENABLED", "1")),
            on_reply_sent=on_reply_sent,
        )

    @classmethod
    def from_config(
        cls,
        process: ProcessHandler,
        config: QQChannelConfig,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
        workspace_dir: Path | None = None,
    ) -> "QQChannel":
        return cls(
            process=process,
            enabled=config.enabled,
            app_id=config.app_id or "",
            client_secret=config.client_secret or "",
            bot_prefix=config.bot_prefix or "",
            markdown_enabled=getattr(config, "markdown_enabled", True),
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            filter_thinking=filter_thinking,
            media_dir=getattr(config, "media_dir", ""),
            workspace_dir=workspace_dir,
            max_reconnect_attempts=getattr(
                config,
                "max_reconnect_attempts",
                100,
            ),
            ack_message=getattr(config, "ack_message", ""),
        )

    def _resolve_send_path(
        self,
        message_type: str,
        sender_id: str,
        channel_id: Optional[str],
        group_openid: Optional[str],
        guild_id: Optional[str] = None,
    ) -> tuple[str, bool, str]:
        """Return (api_path, use_msg_seq, seq_key)."""
        if message_type == "dm" and guild_id:
            return (
                f"/dms/{guild_id}/messages",
                False,
                "",
            )
        if message_type == "group" and group_openid:
            return (
                f"/v2/groups/{group_openid}/messages",
                True,
                "group",
            )
        if message_type == "guild" and channel_id:
            return (
                f"/channels/{channel_id}/messages",
                False,
                "",
            )
        # c2c or fallback
        return (
            f"/v2/users/{sender_id}/messages",
            True,
            "c2c",
        )

    async def _dispatch_text(
        self,
        message_type: str,
        sender_id: str,
        channel_id: Optional[str],
        group_openid: Optional[str],
        text: str,
        msg_id: Optional[str],
        token: str,
        markdown: bool,
        guild_id: Optional[str] = None,
    ) -> None:
        """Route a text message to the correct QQ send API."""
        path, use_seq, seq_key = self._resolve_send_path(
            message_type,
            sender_id,
            channel_id,
            group_openid,
            guild_id=guild_id,
        )
        await _send_message_async(
            self._http,
            token,
            path,
            text,
            msg_id,
            use_markdown=markdown,
            use_msg_seq=use_seq,
            seq_key=seq_key,
        )

    async def _send_text_with_fallback(
        self,
        message_type: str,
        sender_id: str,
        channel_id: Optional[str],
        group_openid: Optional[str],
        text: str,
        msg_id: Optional[str],
        token: str,
        use_markdown: bool,
        guild_id: Optional[str] = None,
    ) -> bool:
        """Send text with multi-level fallback.

        Fallback chain:
        1. Send as-is (markdown or plain)
        2. If markdown fails with validation -> plain text
        3. If plain text fails with URL error -> aggressive URL strip

        Returns True if text was sent successfully.
        """
        try:
            await self._dispatch_text(
                message_type,
                sender_id,
                channel_id,
                group_openid,
                text,
                msg_id,
                token,
                use_markdown,
                guild_id=guild_id,
            )
            return True
        except Exception as exc:
            if not use_markdown:
                return await self._try_aggressive_url_fallback(
                    exc,
                    text,
                    message_type,
                    sender_id,
                    channel_id,
                    group_openid,
                    msg_id,
                    token,
                    guild_id,
                )
            if not _should_plaintext_fallback_from_markdown(exc):
                logger.exception(
                    "send text failed with markdown; "
                    "skip fallback to avoid duplicates",
                )
                return False
            logger.exception(
                "send text failed with markdown payload validation; "
                "fallback to plain text",
            )

        fallback_text, had_url = _sanitize_qq_text(text)
        if had_url:
            logger.info(
                "qq send fallback: stripped URL content "
                "for API compatibility",
            )
        try:
            await self._dispatch_text(
                message_type,
                sender_id,
                channel_id,
                group_openid,
                fallback_text,
                msg_id,
                token,
                False,
                guild_id=guild_id,
            )
            return True
        except Exception as exc2:
            return await self._try_aggressive_url_fallback(
                exc2,
                text,
                message_type,
                sender_id,
                channel_id,
                group_openid,
                msg_id,
                token,
                guild_id,
            )

    async def _try_aggressive_url_fallback(
        self,
        exc: Exception,
        original_text: str,
        message_type: str,
        sender_id: str,
        channel_id: Optional[str],
        group_openid: Optional[str],
        msg_id: Optional[str],
        token: str,
        guild_id: Optional[str],
    ) -> bool:
        """Attempt aggressive URL stripping if QQ rejected URL content."""
        if not _is_url_content_error(exc):
            logger.exception("send text failed")
            return False
        logger.warning(
            "send text failed due to URL content; "
            "trying aggressive URL stripping",
        )
        aggressive_text, _ = _aggressive_sanitize_qq_text(
            original_text,
        )
        try:
            await self._dispatch_text(
                message_type,
                sender_id,
                channel_id,
                group_openid,
                aggressive_text,
                msg_id,
                token,
                False,
                guild_id=guild_id,
            )
            return True
        except Exception:
            logger.exception(
                "send text aggressive fallback failed",
            )
            return False

    async def _send_images(
        self,
        image_urls: List[str],
        message_type: str,
        target_openid: Optional[str],
        msg_id: Optional[str],
        token: str,
        text_already_sent: bool,
    ) -> None:
        """Upload and send images via QQ rich media API."""
        if not image_urls or message_type not in ("c2c", "group"):
            return
        if not target_openid:
            return
        for image_url in image_urls:
            try:
                file_info = await _upload_media_async(
                    self._http,
                    token,
                    target_openid,
                    media_type=1,
                    url=image_url,
                    message_type=message_type,
                )
                if not file_info:
                    logger.warning(
                        f"Failed to upload image, skipping: {image_url}",
                    )
                    continue
                await _send_media_message_async(
                    self._http,
                    token,
                    target_openid,
                    file_info,
                    msg_id if not text_already_sent else None,
                    message_type=message_type,
                )
                logger.info(f"Successfully sent image: {image_url}")
            except Exception:
                logger.exception(f"Failed to send image: {image_url}")

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send one text via QQ HTTP API.
        Routes by meta or to_handle (group:/channel:/openid).
        """
        if not self.enabled or not text.strip():
            return
        text = text.strip()
        meta = meta or {}
        use_markdown = _as_bool(
            meta.get("markdown_enabled", self._markdown_enabled),
        )
        if not use_markdown:
            text, had_url = _sanitize_qq_text(text)
            if had_url:
                logger.info(
                    "qq send: stripped URL content for API compatibility",
                )
        message_type = meta.get("message_type")
        msg_id = meta.get("message_id")
        sender_id = meta.get("sender_id") or to_handle
        channel_id = meta.get("channel_id")
        group_openid = meta.get("group_openid")
        guild_id = meta.get("guild_id")
        if message_type is None:
            if to_handle.startswith("group:"):
                message_type = "group"
                group_openid = to_handle[6:]
            elif to_handle.startswith("channel:"):
                message_type = "guild"
                channel_id = to_handle[8:]
            else:
                message_type = "c2c"
        try:
            token = await self._get_access_token_async()
        except Exception:
            logger.exception("get access_token failed")
            return

        image_urls = _IMAGE_TAG_PATTERN.findall(text)
        clean_text = _IMAGE_TAG_PATTERN.sub("", text).strip()

        text_sent = False
        for chunk in split_text(clean_text) if clean_text else []:
            text_sent = await self._send_text_with_fallback(
                message_type,
                sender_id,
                channel_id,
                group_openid,
                chunk,
                msg_id,
                token,
                use_markdown,
                guild_id=guild_id,
            )

        target_openid = sender_id if message_type == "c2c" else group_openid
        await self._send_images(
            image_urls,
            message_type,
            target_openid,
            msg_id,
            token,
            text_sent,
        )

    _EXT_TYPE_MAP = {
        ".jpg": "image",
        ".jpeg": "image",
        ".png": "image",
        ".gif": "image",
        ".webp": "image",
        ".bmp": "image",
        ".mp4": "video",
        ".avi": "video",
        ".mov": "video",
        ".mkv": "video",
        ".webm": "video",
        ".mpeg": "video",
        ".mp3": "audio",
        ".wav": "audio",
        ".ogg": "audio",
        ".m4a": "audio",
        ".aac": "audio",
        ".wma": "audio",
    }

    def _resolve_attachment_type(
        self,
        att_type: str,
        file_name: str,
    ) -> str:
        """Resolve attachment type from content_type or extension."""
        if not att_type:
            ext = Path(file_name).suffix.lower()
            return self._EXT_TYPE_MAP.get(ext, "file")
        if att_type == "voice":
            return "audio"
        if att_type in ("image", "video", "audio", "file"):
            return att_type
        mime = att_type.split(";")[0].strip().lower()
        for prefix in ("image/", "video/", "audio/"):
            if mime.startswith(prefix):
                return prefix.rstrip("/")
        return "file"

    def _download_attachment_sync(
        self,
        url: str,
        file_name: str,
    ) -> Optional[str]:
        """Download attachment via event loop; return local path."""
        loop = self._loop
        if not (loop and loop.is_running()):
            return url
        try:
            future = asyncio.run_coroutine_threadsafe(
                _download_qq_file(
                    http_session=self._http,
                    file_url=url,
                    media_dir=self._media_dir,
                    filename_hint=file_name,
                ),
                loop,
            )
            return future.result(timeout=30)
        except Exception:
            logger.exception("failed to download attachment")
            return None

    @staticmethod
    def _make_content_part(
        resolved_type: str,
        local_path: str,
        file_name: str,
    ) -> Optional[OutgoingContentPart]:
        """Build a typed content part from resolved type."""
        if resolved_type == "image":
            return ImageContent(
                type=ContentType.IMAGE,
                image_url=local_path,
            )
        if resolved_type == "video":
            return VideoContent(
                type=ContentType.VIDEO,
                video_url=local_path,
            )
        if resolved_type == "audio":
            return AudioContent(
                type=ContentType.AUDIO,
                data=local_path,
            )
        if resolved_type == "file":
            return FileContent(
                type=ContentType.FILE,
                filename=file_name,
                file_url=local_path,
            )
        return None

    def _parse_qq_attachments(
        self,
        attachments: List[Dict[str, Any]],
    ) -> List[OutgoingContentPart]:
        """Parse QQ message attachments to content parts."""
        parts: List[OutgoingContentPart] = []
        if not attachments or not self._http:
            return parts
        for att in attachments:
            url = att.get("url", "")
            file_name = att.get("filename", "")
            if not url:
                continue
            att_type = att.get(
                "content_type",
                att.get("type", ""),
            )
            resolved = self._resolve_attachment_type(
                att_type,
                file_name,
            )
            local_path = self._download_attachment_sync(
                url,
                file_name,
            )
            if not local_path:
                continue
            part = self._make_content_part(
                resolved,
                local_path,
                file_name,
            )
            if part:
                parts.append(part)
        return parts

    def build_agent_request_from_native(self, native_payload: Any) -> Any:
        """Build AgentRequest from QQ native dict (runtime content_parts).

        Parses attachments from QQ messages and converts them to
        ImageContent, VideoContent, AudioContent, FileContent.
        """
        payload = native_payload if isinstance(native_payload, dict) else {}
        channel_id = payload.get("channel_id") or self.channel
        sender_id = payload.get("sender_id") or ""
        content_parts = payload.get("content_parts") or []
        meta = payload.get("meta") or {}
        attachments = meta.get("attachments") or []
        if attachments:
            media_parts = self._parse_qq_attachments(attachments)
            content_parts = list(content_parts) + media_parts
        session_id = self.resolve_session_id(sender_id, meta)
        return self.build_agent_request_from_user_content(
            channel_id=channel_id,
            sender_id=sender_id,
            session_id=session_id,
            content_parts=content_parts,
            channel_meta=meta,
        )

    # ------------------------------------------------------------------
    # Instant acknowledgment
    # ------------------------------------------------------------------

    async def _send_ack_async(
        self,
        message_type: str,
        sender_id: str,
        msg_id: str,
        group_openid: str = "",
        guild_id: str = "",
        channel_id: str = "",
    ) -> None:
        """Send ACK message entirely on the async event loop."""
        token = await self._get_access_token_async()
        path, use_seq, seq_key = self._resolve_send_path(
            message_type,
            sender_id,
            channel_id or None,
            group_openid or None,
            guild_id=guild_id or None,
        )
        await _send_message_async(
            self._http,
            token,
            path,
            self._ack_message,
            msg_id or None,
            use_markdown=False,
            use_msg_seq=use_seq,
            seq_key=seq_key,
        )

    def _schedule_ack(
        self,
        message_type: str,
        sender_id: str,
        msg_id: str,
        group_openid: str = "",
        guild_id: str = "",
        channel_id: str = "",
    ) -> None:
        """Schedule a fire-and-forget ACK from the sync WS thread.

        Sends ``self._ack_message`` as an instant text reply so the
        user knows the bot received their message.  The entire
        operation (token + HTTP send) runs on the async event loop,
        so the WS thread is never blocked.  Failure is logged at
        debug level but never interrupts normal message handling.
        """
        if not self._ack_message:
            return
        loop = self._loop
        if not (loop and loop.is_running() and self._http):
            return
        coro = self._send_ack_async(
            message_type,
            sender_id,
            msg_id,
            group_openid=group_openid,
            guild_id=guild_id,
            channel_id=channel_id,
        )
        try:
            fut = asyncio.run_coroutine_threadsafe(coro, loop)
            fut.add_done_callback(self._on_ack_done)
        except Exception:
            logger.debug(
                "qq ack failed to schedule for %s sender=%s",
                message_type,
                sender_id[:16] if sender_id else "?",
            )

    @staticmethod
    def _on_ack_done(fut: "concurrent.futures.Future[None]") -> None:
        """Silently log exceptions from fire-and-forget ACK futures."""
        exc = fut.exception()
        if exc:
            logger.debug("qq ack send error: %r", exc)

    # ------------------------------------------------------------------
    # WebSocket: message event handling
    # ------------------------------------------------------------------

    def _handle_msg_event(
        self,
        event_type: str,
        d: Dict[str, Any],
    ) -> None:
        """Handle one WS message event via spec lookup."""
        spec = _MESSAGE_EVENT_SPECS.get(event_type)
        if spec is None:
            return
        author = d.get("author") or {}
        text = (d.get("content") or "").strip()
        if not text and not d.get("attachments"):
            return
        if self.bot_prefix and text.startswith(self.bot_prefix):
            return
        sender = ""
        for key in spec.sender_keys:
            sender = author.get(key) or ""
            if sender:
                break
        if not sender:
            return
        msg_id = d.get("id", "")
        att = d.get("attachments") or []
        meta: Dict[str, Any] = {
            "message_type": spec.message_type,
            "message_id": msg_id,
            "sender_id": sender,
            "incoming_raw": d,
            "attachments": att,
        }
        for key in spec.extra_meta_keys:
            meta[key] = d.get(key, "")
        self._schedule_ack(
            spec.message_type,
            sender,
            msg_id,
            group_openid=d.get("group_openid", ""),
            guild_id=d.get("guild_id", ""),
            channel_id=d.get("channel_id", ""),
        )

        native = {
            "channel_id": "qq",
            "sender_id": sender,
            "content_parts": [
                TextContent(type=ContentType.TEXT, text=text),
            ],
            "meta": meta,
        }
        request = self.build_agent_request_from_native(native)
        request.channel_meta = meta
        if self._enqueue is not None:
            self._enqueue(request)
        extra_vals = tuple(meta.get(k, "") for k in spec.extra_meta_keys)
        extra_str = "".join(
            f" {k}={v}" for k, v in zip(spec.extra_meta_keys, extra_vals)
        )
        logger.info(
            "qq recv %s from=%s%s text=%r",
            spec.message_type,
            sender,
            extra_str,
            text[:100],
        )

    # ------------------------------------------------------------------
    # WebSocket: payload dispatch
    # ------------------------------------------------------------------

    def _handle_ws_payload(
        self,
        payload: Dict[str, Any],
        ws: Any,
        token: str,
        state: _WSState,
        hb: _HeartbeatController,
    ) -> Optional[str]:
        """Process one WS payload.

        Return "break" to exit loop, else None.
        """
        op = payload.get("op")
        d = payload.get("d")
        s = payload.get("s")
        t = payload.get("t")
        if s is not None:
            state.last_seq = s

        if op == OP_HELLO:
            hi = d or {}
            interval = hi.get("heartbeat_interval", 45000)
            if state.session_id and state.last_seq is not None:
                ws.send(
                    json.dumps(
                        {
                            "op": OP_RESUME,
                            "d": {
                                "token": f"QQBot {token}",
                                "session_id": state.session_id,
                                "seq": state.last_seq,
                            },
                        },
                    ),
                )
            else:
                intents = INTENT_PUBLIC_GUILD_MESSAGES | INTENT_GUILD_MEMBERS
                if state.identify_fail_count < 3:
                    intents |= INTENT_DIRECT_MESSAGE | INTENT_GROUP_AND_C2C
                ws.send(
                    json.dumps(
                        {
                            "op": OP_IDENTIFY,
                            "d": {
                                "token": f"QQBot {token}",
                                "intents": intents,
                                "shard": [0, 1],
                            },
                        },
                    ),
                )
            hb.start(interval)
            return None

        if op == OP_DISPATCH:
            if t == "READY":
                state.session_id = (d or {}).get("session_id")
                state.identify_fail_count = 0
                state.reconnect_attempts = 0
                state.last_connect_time = time.time()
                logger.info("qq ready session_id=%s", state.session_id)
            elif t == "RESUMED":
                state.identify_fail_count = 0
                state.reconnect_attempts = 0
                state.last_connect_time = time.time()
                logger.info("qq session resumed")
            elif t in _MESSAGE_EVENT_SPECS:
                self._handle_msg_event(t, d or {})
            return None

        if op == OP_HEARTBEAT_ACK:
            logger.debug("qq heartbeat ack")
            return None

        if op == OP_RECONNECT:
            logger.info("qq server requested reconnect")
            return "break"

        if op == OP_INVALID_SESSION:
            can_resume = d
            logger.error("qq invalid session can_resume=%s", can_resume)
            if not can_resume:
                state.session_id = None
                state.last_seq = None
                state.identify_fail_count += 1
                state.should_refresh_token = True
            return "break"

        return None

    # ------------------------------------------------------------------
    # WebSocket: reconnect delay
    # ------------------------------------------------------------------

    def _compute_reconnect_delay(self, state: _WSState) -> float:
        """Compute delay before next reconnect, updating state counters."""
        elapsed = (
            time.time() - state.last_connect_time
            if state.last_connect_time
            else None
        )
        if elapsed is not None and elapsed < QUICK_DISCONNECT_THRESHOLD:
            state.quick_disconnect_count += 1
            if state.quick_disconnect_count >= MAX_QUICK_DISCONNECT_COUNT:
                state.session_id = None
                state.last_seq = None
                state.should_refresh_token = True
                state.quick_disconnect_count = 0
                state.reconnect_attempts = min(
                    state.reconnect_attempts,
                    len(RECONNECT_DELAYS) - 1,
                )
                return RATE_LIMIT_DELAY
        else:
            state.quick_disconnect_count = 0
        return RECONNECT_DELAYS[
            min(state.reconnect_attempts, len(RECONNECT_DELAYS) - 1)
        ]

    # ------------------------------------------------------------------
    # WebSocket: single connection attempt
    # ------------------------------------------------------------------

    def _ws_connect_once(
        self,
        state: _WSState,
        websocket: Any,
    ) -> bool:
        """Run one WS connection.

        Return True to reconnect, False to stop.
        """
        if self._stop_event.is_set():
            return False
        if state.should_refresh_token:
            self._clear_token_cache()
            state.should_refresh_token = False
        try:
            token = self._get_access_token_sync()
            url = _get_channel_url_sync(token)
        except Exception as e:
            logger.warning("qq get token/gateway failed: %s", e)
            return True
        logger.info("qq connecting to %s", url)
        try:
            ws = websocket.create_connection(url)
        except Exception as e:
            logger.warning("qq ws connect failed: %s", e)
            return True

        self._ws = ws
        hb = _HeartbeatController(ws, self._stop_event, state)
        try:
            while not self._stop_event.is_set():
                raw = ws.recv()
                if not raw:
                    break
                action = self._handle_ws_payload(
                    json.loads(raw),
                    ws,
                    token,
                    state,
                    hb,
                )
                if action == "break":
                    break
        except websocket.WebSocketConnectionClosedException:
            pass
        except OSError:
            if not self._stop_event.is_set():
                raise
        except Exception as e:
            logger.exception("qq ws loop: %s", e)
        finally:
            self._ws = None
            hb.stop()
            try:
                ws.close()
            except Exception:
                pass

        delay = self._compute_reconnect_delay(state)
        state.reconnect_attempts += 1
        max_attempts = self._max_reconnect_attempts
        if max_attempts != -1 and state.reconnect_attempts >= max_attempts:
            logger.error("qq max reconnect attempts reached")
            return False
        logger.info(
            "qq reconnecting in %ss (attempt %s)",
            delay,
            state.reconnect_attempts,
        )
        self._stop_event.wait(timeout=delay)
        return not self._stop_event.is_set()

    # ------------------------------------------------------------------
    # WebSocket: main loop
    # ------------------------------------------------------------------

    def _run_ws_forever(self) -> None:
        try:
            import websocket
        except ImportError:
            logger.error(
                "websocket-client not installed. pip install websocket-client",
            )
            return
        state = _WSState()
        try:
            while self._ws_connect_once(state, websocket):
                pass
        except Exception:
            logger.exception("qq ws thread unexpected error")
        finally:
            self._stop_event.set()
            logger.info("qq ws thread stopped")

    async def start(self) -> None:
        if not self.enabled:
            logger.debug("qq channel disabled by QQ_CHANNEL_ENABLED=0")
            return
        if not self.app_id or not self.client_secret:
            raise ChannelError(
                channel_name="qq",
                message=(
                    "QQ_APP_ID and QQ_CLIENT_SECRET "
                    "are required when channel is enabled"
                ),
            )
        self._loop = asyncio.get_running_loop()
        self._stop_event.clear()
        self._ws_thread = threading.Thread(
            target=self._run_ws_forever,
            daemon=True,
        )
        self._ws_thread.start()
        if self._http is None:
            self._http = aiohttp.ClientSession()

    async def stop(self) -> None:
        if not self.enabled:
            return
        self._stop_event.set()
        ws = self._ws
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
        if self._ws_thread:
            self._ws_thread.join(timeout=2)
            self._ws_thread = None
        if self._http is not None:
            await self._http.close()
            self._http = None

    # ------------------------------------------------------------------
    # Rich-media sending: send_content_parts / send_media overrides
    # ------------------------------------------------------------------

    def _resolve_media_meta(
        self,
        meta: Optional[Dict[str, Any]],
    ) -> tuple[
        str,
        Optional[str],
        Optional[str],
        Optional[str],
        Optional[str],
    ]:
        """Extract routing fields from meta for media sending.

        Returns (message_type, sender_id, channel_id, group_openid, guild_id).
        """
        meta = meta or {}
        message_type = meta.get("message_type", "c2c")
        sender_id = meta.get("sender_id")
        channel_id = meta.get("channel_id")
        group_openid = meta.get("group_openid")
        guild_id = meta.get("guild_id")
        return message_type, sender_id, channel_id, group_openid, guild_id

    def _resolve_media_url_and_path(
        self,
        part: OutgoingContentPart,
    ) -> tuple[Optional[str], Optional[str]]:
        """Extract URL and local file path from a content part.

        Returns (url_or_none, local_path_or_none).
        """
        content_type = getattr(part, "type", None)
        url: Optional[str] = None
        local_path: Optional[str] = None

        if content_type == ContentType.IMAGE:
            raw = getattr(part, "image_url", None) or ""
        elif content_type == ContentType.VIDEO:
            raw = getattr(part, "video_url", None) or ""
        elif content_type == ContentType.AUDIO:
            raw = getattr(part, "data", None) or ""
        elif content_type == ContentType.FILE:
            raw = getattr(part, "file_url", None) or ""
        else:
            return None, None

        if not raw:
            return None, None

        # file:// protocol → treat as local file
        if raw.startswith("file://"):
            resolved = file_url_to_local_path(raw) or raw
            if os.path.isfile(resolved):
                local_path = resolved
            else:
                logger.warning("qq: file:// path not found: %s", resolved)
            return url, local_path

        if raw.startswith(("http://", "https://")):
            url = raw
        elif os.path.isfile(raw):
            local_path = raw
        else:
            url = raw

        return url, local_path

    @staticmethod
    def _content_type_to_media_type(
        content_type: Any,
    ) -> Optional[int]:
        """Map ContentType to QQ rich-media file_type integer."""
        mapping = {
            ContentType.IMAGE: _MEDIA_TYPE_IMAGE,
            ContentType.VIDEO: _MEDIA_TYPE_VIDEO,
            ContentType.AUDIO: _MEDIA_TYPE_FILE,
            ContentType.FILE: _MEDIA_TYPE_FILE,
        }
        return mapping.get(content_type)

    async def send_content_parts(
        self,
        to_handle: str,
        parts: List[OutgoingContentPart],
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Override BaseChannel to route media parts through QQ APIs.

        Text/refusal parts are merged and sent as text.
        Media parts (image, video, audio, file) are sent via the
        appropriate QQ API depending on message_type.
        """
        if not self.enabled:
            return

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
                ContentType.VIDEO,
                ContentType.AUDIO,
                ContentType.FILE,
            ):
                media_parts.append(part)

        body = "\n".join(text_parts).strip() if text_parts else ""

        meta = meta or {}
        message_type = meta.get("message_type", "c2c")
        msg_id = meta.get("message_id")

        try:
            token = await self._get_access_token_async()
        except Exception:
            logger.exception("qq send_content_parts: get token failed")
            return

        use_markdown = _as_bool(
            meta.get("markdown_enabled", self._markdown_enabled),
        )

        text_sent = False
        if body:
            sender_id = meta.get("sender_id") or to_handle
            channel_id = meta.get("channel_id")
            group_openid = meta.get("group_openid")
            guild_id = meta.get("guild_id")
            for chunk in split_text(body):
                text_sent = await self._send_text_with_fallback(
                    message_type,
                    sender_id,
                    channel_id,
                    group_openid,
                    chunk,
                    msg_id,
                    token,
                    use_markdown,
                    guild_id=guild_id,
                )

        for media_part in media_parts:
            await self.send_media(
                to_handle,
                media_part,
                meta,
                token=token,
                text_already_sent=text_sent,
            )
            text_sent = True

    async def send_media(
        self,
        to_handle: str,
        part: OutgoingContentPart,
        meta: Optional[Dict[str, Any]] = None,
        *,
        token: Optional[str] = None,
        text_already_sent: bool = True,
    ) -> None:
        """Send a single media part via the appropriate QQ API.

        Routing logic per message_type:
        - **c2c / group**: Upload via rich-media ``/files`` endpoint,
          then send via ``/messages`` with ``msg_type=7``.
          Group does NOT support file_type=4 (file).
        - **guild / dm**: Only images are supported.
          Use ``image`` field (URL) or ``file_image`` (form-data upload).
        """
        if not self.enabled:
            return

        meta = meta or {}
        (
            message_type,
            sender_id,
            channel_id,
            group_openid,
            guild_id,
        ) = self._resolve_media_meta(meta)
        msg_id = meta.get("message_id")
        content_type = getattr(part, "type", None)

        if token is None:
            try:
                token = await self._get_access_token_async()
            except Exception:
                logger.exception("qq send_media: get token failed")
                return

        url, local_path = self._resolve_media_url_and_path(part)
        if not url and not local_path:
            logger.warning(
                "qq send_media: no url or local path for %s",
                content_type,
            )
            return

        if message_type in ("c2c", "group"):
            await self._send_media_c2c_or_group(
                message_type=message_type,
                content_type=content_type,
                sender_id=sender_id or to_handle,
                group_openid=group_openid,
                url=url,
                local_path=local_path,
                msg_id=msg_id if not text_already_sent else None,
                token=token,
            )
        elif message_type in ("guild", "dm"):
            await self._send_media_guild_or_dm(
                message_type=message_type,
                content_type=content_type,
                channel_id=channel_id,
                guild_id=guild_id,
                url=url,
                local_path=local_path,
                msg_id=msg_id if not text_already_sent else None,
                token=token,
            )
        else:
            logger.warning(
                "qq send_media: unsupported message_type=%s",
                message_type,
            )

    async def _send_media_c2c_or_group(
        self,
        *,
        message_type: str,
        content_type: Any,
        sender_id: str,
        group_openid: Optional[str],
        url: Optional[str],
        local_path: Optional[str],
        msg_id: Optional[str],
        token: str,
    ) -> None:
        """Upload + send rich media for c2c or group scenarios."""
        media_type = self._content_type_to_media_type(content_type)
        if media_type is None:
            logger.warning(
                "qq _send_media_c2c_or_group: unknown content_type=%s",
                content_type,
            )
            return

        # Group does not support file_type=4 (file)
        if message_type == "group" and media_type == _MEDIA_TYPE_FILE:
            logger.warning(
                "qq: group does not support sending files (file_type=4), "
                "skipping",
            )
            return

        target_openid = sender_id if message_type == "c2c" else group_openid
        if not target_openid:
            logger.warning(
                "qq _send_media_c2c_or_group: no target openid",
            )
            return

        file_data = ""
        display_filename = ""
        source_path = url or local_path or ""
        if local_path and not url:
            try:
                file_data = await _read_file_as_base64(local_path)
                display_filename = Path(local_path).name
            except Exception:
                logger.exception(
                    "qq: failed to read local file as base64: %s",
                    local_path,
                )
                return
        elif url:
            display_filename = Path(url.split("?")[0]).name

        try:
            file_info = await _upload_media_async(
                self._http,
                token,
                target_openid,
                media_type=media_type,
                url=url or "",
                message_type=message_type,
                file_data=file_data,
                file_name=display_filename,
            )
            if not file_info:
                logger.warning(
                    "qq: media upload returned no file_info for %s",
                    source_path,
                )
                return
            await _send_media_message_async(
                self._http,
                token,
                target_openid,
                file_info,
                msg_id,
                message_type=message_type,
                filename=display_filename,
            )
            logger.info(
                "qq: sent %s media (%s) to %s",
                message_type,
                content_type,
                target_openid,
            )
        except Exception:
            logger.exception(
                "qq: failed to send %s media (%s)",
                message_type,
                content_type,
            )

    async def _send_media_guild_or_dm(
        self,
        *,
        message_type: str,
        content_type: Any,
        channel_id: Optional[str],
        guild_id: Optional[str],
        url: Optional[str],
        local_path: Optional[str],
        msg_id: Optional[str],
        token: str,
    ) -> None:
        """Send media for guild (text channel) or dm scenarios.

        Per QQ official docs, guild/dm supports sending images and
        videos via the ``image`` field (URL) or ``file_image``
        (form-data upload).  Audio and file types are not supported.
        """
        if content_type not in (ContentType.IMAGE, ContentType.VIDEO):
            logger.warning(
                "qq: guild/dm does not support sending %s, skipping",
                content_type,
            )
            return

        if message_type == "dm" and guild_id:
            path = f"/dms/{guild_id}/messages"
        elif message_type == "guild" and channel_id:
            path = f"/channels/{channel_id}/messages"
        else:
            logger.warning(
                "qq _send_media_guild_or_dm: missing channel_id or guild_id",
            )
            return

        try:
            if url:
                await _send_guild_image_async(
                    self._http,
                    token,
                    path,
                    url,
                    msg_id,
                )
            elif local_path:
                await _send_guild_image_file_async(
                    self._http,
                    token,
                    path,
                    local_path,
                    msg_id,
                )
            logger.info(
                "qq: sent %s media (%s) to guild/dm",
                message_type,
                content_type,
            )
        except Exception:
            logger.exception(
                "qq: failed to send %s media (%s) to guild/dm",
                message_type,
                content_type,
            )
