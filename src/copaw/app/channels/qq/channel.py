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
import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiofiles
import aiohttp

from agentscope_runtime.engine.schemas.agent_schemas import (
    RunStatus,
    TextContent,
    ImageContent,
    VideoContent,
    AudioContent,
    FileContent,
    ContentType,
)

from ....config.config import QQConfig as QQChannelConfig
from ....constant import WORKING_DIR

from ..base import (
    BaseChannel,
    OnReplySent,
    OutgoingContentPart,
    ProcessHandler,
)

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
MAX_RECONNECT_ATTEMPTS = 100
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
        raise RuntimeError(f"Failed to get channel url: {msg}") from e
    except Exception as e:
        raise RuntimeError(f"Failed to get channel url: {e}") from e
    channel_url = data.get("url")
    if not channel_url:
        raise RuntimeError(f"No url in channel response: {data}")
    return channel_url


def _api_request_sync(
    access_token: str,
    method: str,
    path: str,
    body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    import urllib.request

    url = f"{_get_api_base()}{path}"
    data = None
    if body is not None:
        data = json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"QQBot {access_token}",
            "Content-Type": "application/json",
        },
        method=method,
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


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


async def _send_c2c_message_async(
    session: Any,
    access_token: str,
    openid: str,
    content: str,
    msg_id: Optional[str] = None,
    use_markdown: bool = False,
) -> None:
    msg_seq = _get_next_msg_seq(msg_id or "c2c")
    if use_markdown:
        body = {
            "markdown": {"content": content},
            "msg_type": 2,
        }
    else:
        body = {"content": content, "msg_type": 0}
    body["msg_seq"] = msg_seq
    if msg_id:
        body["msg_id"] = msg_id
    await _api_request_async(
        session,
        access_token,
        "POST",
        f"/v2/users/{openid}/messages",
        body,
    )


async def _send_message_helper(
    session: Any,
    access_token: str,
    endpoint_path: str,
    content: str,
    msg_id: Optional[str] = None,
    use_markdown: bool = False,
) -> None:
    """Helper function to send messages via QQ API.

    Args:
        session: aiohttp session
        access_token: QQ access token
        endpoint_path: API endpoint path (e.g.,
            "/channels/{id}/messages" or "/dms/{id}/messages")
        content: message content
        msg_id: reply message id
        use_markdown: whether to use markdown format
    """
    body: Dict[str, Any] = (
        {"markdown": {"content": content}}
        if use_markdown
        else {"content": content}
    )
    if msg_id:
        body["msg_id"] = msg_id
    await _api_request_async(
        session,
        access_token,
        "POST",
        endpoint_path,
        body,
    )


async def _send_channel_message_async(
    session: Any,
    access_token: str,
    channel_id: str,
    content: str,
    msg_id: Optional[str] = None,
    use_markdown: bool = False,
) -> None:
    await _send_message_helper(
        session,
        access_token,
        f"/channels/{channel_id}/messages",
        content,
        msg_id,
        use_markdown,
    )


async def _send_dm_message_async(
    session: Any,
    access_token: str,
    guild_id: str,
    content: str,
    msg_id: Optional[str] = None,
    use_markdown: bool = False,
) -> None:
    """Send a direct message in a guild via /dms/{guild_id}/messages."""
    await _send_message_helper(
        session,
        access_token,
        f"/dms/{guild_id}/messages",
        content,
        msg_id,
        use_markdown,
    )


async def _send_group_message_async(
    session: Any,
    access_token: str,
    group_openid: str,
    content: str,
    msg_id: Optional[str] = None,
    use_markdown: bool = False,
) -> None:
    msg_seq = _get_next_msg_seq(msg_id or "group")
    if use_markdown:
        body = {
            "markdown": {"content": content},
            "msg_type": 2,
        }
    else:
        body = {"content": content, "msg_type": 0}
    body["msg_seq"] = msg_seq
    if msg_id:
        body["msg_id"] = msg_id
    await _api_request_async(
        session,
        access_token,
        "POST",
        f"/v2/groups/{group_openid}/messages",
        body,
    )


async def _upload_media_async(
    session: Any,
    access_token: str,
    openid: str,
    media_type: int,
    url: str,
    message_type: str = "c2c",
) -> Optional[str]:
    """Upload media to QQ rich media server.

    Args:
        session: aiohttp session
        access_token: QQ access token
        openid: user openid or group openid
        media_type: 1 image, 2 video, 3 audio, 4 file
        url: media url
        message_type: "c2c" or "group"

    Returns:
        file_info if success, None otherwise
    """
    try:
        if message_type == "c2c":
            path = f"/v2/users/{openid}/files"
        elif message_type == "group":
            path = f"/v2/groups/{openid}/files"
        else:
            logger.warning(
                f"Unsupported message type for media upload: {message_type}",
            )
            return None

        body = {
            "file_type": media_type,
            "url": url,
            "srv_send_msg": False,
        }
        response = await _api_request_async(
            session,
            access_token,
            "POST",
            path,
            body,
        )
        return response.get("file_info")
    except Exception:
        logger.exception(f"Failed to upload media from url: {url}")
        return None


async def _send_media_message_async(
    session: Any,
    access_token: str,
    openid: str,
    file_info: str,
    msg_id: Optional[str] = None,
    message_type: str = "c2c",
) -> None:
    """Send rich media message.

    Args:
        session: aiohttp session
        access_token: QQ access token
        openid: user openid or group openid
        file_info: file info from upload response
        msg_id: reply message id
        message_type: "c2c" or "group"
    """
    msg_seq = _get_next_msg_seq(msg_id or f"{message_type}_media")
    body = {
        "msg_type": 7,
        "media": {
            "file_info": file_info,
        },
        "msg_seq": msg_seq,
    }
    if msg_id:
        body["msg_id"] = msg_id

    if message_type == "c2c":
        path = f"/v2/users/{openid}/messages"
    elif message_type == "group":
        path = f"/v2/groups/{openid}/messages"
    else:
        logger.warning(
            f"Unsupported message type for media send: {message_type}",
        )
        return

    await _api_request_async(
        session,
        access_token,
        "POST",
        path,
        body,
    )


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
            async with aiofiles.open(str(local_path), "wb") as f:
                await f.write(content)
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
        self._media_dir = (
            Path(media_dir).expanduser() if media_dir else _DEFAULT_MEDIA_DIR
        )

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ws_thread: Optional[threading.Thread] = None
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
            raise RuntimeError(f"Failed to get access_token: {e}") from e
        token = data.get("access_token")
        if not token:
            raise RuntimeError(f"No access_token in response: {data}")
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
                raise RuntimeError(
                    f"Token request failed {resp.status}: {text}",
                )
            data = await resp.json()
        token = data.get("access_token")
        if not token:
            raise RuntimeError(f"No access_token: {data}")
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
        )

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

        async def _dispatch(send_text: str, markdown: bool) -> None:
            if message_type == "c2c":
                await _send_c2c_message_async(
                    self._http,
                    token,
                    sender_id,
                    send_text,
                    msg_id,
                    use_markdown=markdown,
                )
            elif message_type == "dm" and guild_id:
                await _send_dm_message_async(
                    self._http,
                    token,
                    guild_id,
                    send_text,
                    msg_id,
                    use_markdown=markdown,
                )
            elif message_type == "group" and group_openid:
                await _send_group_message_async(
                    self._http,
                    token,
                    group_openid,
                    send_text,
                    msg_id,
                    use_markdown=markdown,
                )
            elif channel_id:
                await _send_channel_message_async(
                    self._http,
                    token,
                    channel_id,
                    send_text,
                    msg_id,
                    use_markdown=markdown,
                )
            else:
                await _send_c2c_message_async(
                    self._http,
                    token,
                    sender_id,
                    send_text,
                    msg_id,
                    use_markdown=markdown,
                )

        # Extract and process [Image: ] tags
        image_urls = _IMAGE_TAG_PATTERN.findall(text)
        # Remove [Image: ] tags from text
        clean_text = _IMAGE_TAG_PATTERN.sub("", text).strip()

        # Send text content if not empty
        text_sent = False
        if clean_text:
            try:
                await _dispatch(clean_text, use_markdown)
                text_sent = True
            except Exception as exc:
                if not use_markdown:
                    if _is_url_content_error(exc):
                        logger.warning(
                            "send text failed due to URL content; "
                            "trying aggressive URL stripping",
                        )
                        aggressive_text, _ = _aggressive_sanitize_qq_text(
                            clean_text,
                        )
                        try:
                            await _dispatch(aggressive_text, False)
                            text_sent = True
                        except Exception:
                            logger.exception(
                                "send text aggressive fallback failed",
                            )
                    else:
                        logger.exception("send text failed")
                elif not _should_plaintext_fallback_from_markdown(exc):
                    logger.exception(
                        "send text failed with markdown; "
                        "skip fallback to avoid duplicates",
                    )
                else:
                    logger.exception(
                        "send text failed with markdown payload validation; "
                        "fallback to plain text",
                    )
                    fallback_text, had_url = _sanitize_qq_text(clean_text)
                    if had_url:
                        logger.info(
                            "qq send fallback: stripped URL content "
                            "for API compatibility",
                        )
                    try:
                        await _dispatch(fallback_text, False)
                        text_sent = True
                    except Exception as exc2:
                        if _is_url_content_error(exc2):
                            logger.warning(
                                "send text fallback still rejected "
                                "due to URL content; trying aggressive "
                                "URL stripping",
                            )
                            aggressive_text, _ = _aggressive_sanitize_qq_text(
                                clean_text,
                            )
                            try:
                                await _dispatch(aggressive_text, False)
                                text_sent = True
                            except Exception:
                                logger.exception(
                                    "send text aggressive fallback failed",
                                )
                        else:
                            logger.exception("send text fallback failed")

        # Send images if any
        if image_urls and message_type in ("c2c", "group"):
            # Determine target openid
            target_openid = (
                sender_id if message_type == "c2c" else group_openid
            )
            if target_openid:
                for image_url in image_urls:
                    try:
                        # Upload image to QQ rich media
                        file_info = await _upload_media_async(
                            self._http,
                            token,
                            target_openid,
                            media_type=1,  # 1 for image
                            url=image_url,
                            message_type=message_type,
                        )
                        if file_info:
                            # Send media message
                            await _send_media_message_async(
                                self._http,
                                token,
                                target_openid,
                                file_info,
                                msg_id if not text_sent
                                # Only reply with msg_id for first message
                                else None,
                                message_type=message_type,
                            )
                            logger.info(
                                f"Successfully sent image: {image_url}",
                            )
                        else:
                            logger.warning(
                                f"Failed to upload image,"
                                f" skipping: {image_url}",
                            )
                    except Exception:
                        logger.exception(f"Failed to send image: {image_url}")

    def _resolve_attachment_type(self, att_type: str, file_name: str) -> str:
        # pylint: disable=too-many-return-statements
        """Resolve attachment type from content_type or file extension.

        Args:
            att_type: MIME type or content type string
            file_name: Optional filename for extension-based fallback

        Returns:
            Normalized type: "image", "video", "audio", or "file"
        """
        if not att_type:
            ext = Path(file_name).suffix.lower()
            ext_map = {
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
            return ext_map.get(ext, "file")

        if att_type in ("image", "video", "voice", "audio", "file"):
            if att_type == "voice":
                return "audio"
            return att_type

        mime_base = att_type.split(";")[0].strip().lower()
        if mime_base.startswith("image/"):
            return "image"
        elif mime_base.startswith("video/"):
            return "video"
        elif mime_base.startswith("audio/"):
            return "audio"
        else:
            return "file"

    def _parse_qq_attachments(
        self,
        attachments: List[Dict[str, Any]],
    ) -> List[OutgoingContentPart]:
        """Parse QQ message attachments to content parts.

        QQ attachment format:
        {'content': '', 'content_type': 'image/jpeg', 'filename': 'abc.jpg',
        'height': 128, 'size': 13588,
          'url': '','width': 198}

        Supports the MIME type matching for flexible content type detection.
        """
        parts: List[OutgoingContentPart] = []
        if not attachments or not self._http:
            return parts

        for att in attachments:
            att_type = att.get("content_type", att.get("type", ""))
            url = att.get("url", "")
            file_name = att.get("filename", "")
            if not url:
                continue
            resolved_type = self._resolve_attachment_type(att_type, file_name)

            if resolved_type in ["image", "video", "audio", "file"]:
                try:
                    loop = self._loop
                    if loop and loop.is_running():
                        future = asyncio.run_coroutine_threadsafe(
                            _download_qq_file(
                                http_session=self._http,
                                file_url=url,
                                media_dir=self._media_dir,
                                filename_hint=file_name,
                            ),
                            loop,
                        )
                        local_path = future.result(timeout=30)
                    else:
                        local_path = url
                except Exception:
                    logger.exception("failed to download attachment")
                    local_path = None
                if local_path:
                    # Map resolved_type to appropriate content type
                    if resolved_type == "image":
                        parts.append(
                            ImageContent(
                                type=ContentType.IMAGE,
                                image_url=local_path,
                            ),
                        )
                    elif resolved_type == "video":
                        parts.append(
                            VideoContent(
                                type=ContentType.VIDEO,
                                video_url=local_path,
                            ),
                        )
                    elif resolved_type == "audio":
                        parts.append(
                            AudioContent(
                                type=ContentType.AUDIO,
                                data=local_path,
                            ),
                        )
                    elif resolved_type == "file":
                        parts.append(
                            FileContent(
                                type=ContentType.FILE,
                                filename=file_name,
                                file_url=local_path,
                            ),
                        )

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

    async def consume_one(self, payload: Any) -> None:
        """Process one AgentRequest from manager queue."""
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
                    "qq event #%s: object=%s status=%s type=%s",
                    event_count,
                    obj,
                    status,
                    ev_type,
                )
                if obj == "message" and status == RunStatus.Completed:
                    parts = self._message_to_content_parts(event)
                    logger.info(
                        "qq completed message: type=%s parts_count=%s",
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
                await self.send_content_parts(
                    to_handle,
                    [
                        TextContent(
                            type=ContentType.TEXT,
                            text=self.bot_prefix
                            + "An error occurred while processing your "
                            "request.",
                        ),
                    ],
                    send_meta,
                )
            if self._on_reply_sent:
                self._on_reply_sent(
                    self.channel,
                    to_handle,
                    request.session_id or f"{self.channel}:{to_handle}",
                )
        except Exception as e:
            logger.exception("qq process/reply failed")
            err_msg = str(e).strip() or "An error occurred while processing."

            # Try to send error message to user
            try:
                fallback_handle = getattr(request, "user_id", "")
                if not fallback_handle and hasattr(request, "sender_id"):
                    fallback_handle = request.sender_id
                if not fallback_handle:
                    # Try to extract from channel_meta
                    meta = getattr(request, "channel_meta", {}) or {}
                    fallback_handle = meta.get("sender_id", "")

                if fallback_handle:
                    error_text = self.bot_prefix + f"Error: {err_msg}"
                    await self.send_content_parts(
                        fallback_handle,
                        [
                            TextContent(
                                type=ContentType.TEXT,
                                text=error_text,
                            ),
                        ],
                        getattr(request, "channel_meta", None) or {},
                    )
                else:
                    logger.warning(
                        "Cannot determine user to send error message to",
                    )
            except Exception:
                logger.exception("send error message failed")

    def _run_ws_forever(self) -> None:
        try:
            import websocket
        except ImportError:
            logger.error(
                "websocket-client not installed. pip install websocket-client",
            )
            return
        reconnect_attempts = 0
        last_connect_time = 0.0
        quick_disconnect_count = 0
        session_id: Optional[str] = None
        last_seq: Optional[int] = None
        identify_fail_count = 0
        should_refresh_token = False

        def connect() -> bool:
            nonlocal session_id, last_seq, reconnect_attempts, last_connect_time, quick_disconnect_count, should_refresh_token, identify_fail_count  # pylint: disable=line-too-long # noqa: E501
            if self._stop_event.is_set():
                return False
            if should_refresh_token:
                self._clear_token_cache()
                should_refresh_token = False
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
            current_ws = ws
            heartbeat_interval: Optional[float] = None
            heartbeat_timer: Optional[threading.Timer] = None

            def stop_heartbeat() -> None:
                if heartbeat_timer:
                    heartbeat_timer.cancel()

            def schedule_heartbeat() -> None:
                nonlocal heartbeat_timer
                if heartbeat_interval is None or self._stop_event.is_set():
                    return

                def send_ping() -> None:
                    if self._stop_event.is_set():
                        return
                    try:
                        if current_ws.connected:
                            current_ws.send(
                                json.dumps(
                                    {"op": OP_HEARTBEAT, "d": last_seq},
                                ),
                            )
                            logger.debug("qq heartbeat sent")
                    except Exception:
                        pass
                    schedule_heartbeat()

                heartbeat_timer = threading.Timer(
                    heartbeat_interval / 1000.0,
                    send_ping,
                )
                heartbeat_timer.daemon = True
                heartbeat_timer.start()

            try:
                while not self._stop_event.is_set():
                    raw = current_ws.recv()
                    if not raw:
                        break
                    payload = json.loads(raw)
                    op = payload.get("op")
                    d = payload.get("d")
                    s = payload.get("s")
                    t = payload.get("t")
                    if s is not None:
                        last_seq = s

                    if op == OP_HELLO:
                        hi = d or {}
                        heartbeat_interval = hi.get(
                            "heartbeat_interval",
                            45000,
                        )
                        if session_id and last_seq is not None:
                            current_ws.send(
                                json.dumps(
                                    {
                                        "op": OP_RESUME,
                                        "d": {
                                            "token": f"QQBot {token}",
                                            "session_id": session_id,
                                            "seq": last_seq,
                                        },
                                    },
                                ),
                            )
                        else:
                            intents = (
                                INTENT_PUBLIC_GUILD_MESSAGES
                                | INTENT_GUILD_MEMBERS
                            )
                            if identify_fail_count < 3:
                                intents |= (
                                    INTENT_DIRECT_MESSAGE
                                    | INTENT_GROUP_AND_C2C
                                )
                            current_ws.send(
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
                        schedule_heartbeat()
                    elif op == OP_DISPATCH:
                        if t == "READY":
                            session_id = (d or {}).get("session_id")
                            identify_fail_count = 0
                            reconnect_attempts = 0
                            last_connect_time = time.time()
                            logger.info("qq ready session_id=%s", session_id)
                        elif t == "RESUMED":
                            logger.info("qq session resumed")
                        elif t == "C2C_MESSAGE_CREATE":
                            author = (d or {}).get("author") or {}
                            text = ((d or {}).get("content") or "").strip()
                            if not text and not (d or {}).get("attachments"):
                                continue
                            if self.bot_prefix and text.startswith(
                                self.bot_prefix,
                            ):
                                continue
                            sender = (
                                author.get("user_openid")
                                or author.get("id")
                                or ""
                            )
                            if not sender:
                                continue
                            msg_id = (d or {}).get("id", "")
                            # ts = (d or {}).get("timestamp", "")
                            att = (d or {}).get("attachments") or []
                            meta = {
                                "message_type": "c2c",
                                "message_id": msg_id,
                                "sender_id": sender,
                                "incoming_raw": d,
                                "attachments": att,
                            }
                            native = {
                                "channel_id": "qq",
                                "sender_id": sender,
                                "content_parts": [
                                    TextContent(
                                        type=ContentType.TEXT,
                                        text=text,
                                    ),
                                ],
                                "meta": meta,
                            }
                            request = self.build_agent_request_from_native(
                                native,
                            )
                            request.channel_meta = meta
                            if self._enqueue is not None:
                                self._enqueue(request)
                            logger.info(
                                "qq recv c2c from=%s text=%r",
                                sender,
                                text[:100],
                            )
                        elif t == "AT_MESSAGE_CREATE":
                            author = (d or {}).get("author") or {}
                            text = ((d or {}).get("content") or "").strip()
                            if not text and not (d or {}).get("attachments"):
                                continue
                            if self.bot_prefix and text.startswith(
                                self.bot_prefix,
                            ):
                                continue
                            sender = (
                                author.get("id")
                                or author.get("username")
                                or ""
                            )
                            if not sender:
                                continue
                            channel_id = (d or {}).get("channel_id", "")
                            guild_id = (d or {}).get("guild_id", "")
                            msg_id = (d or {}).get("id", "")
                            # ts = (d or {}).get("timestamp", "")
                            att = (d or {}).get("attachments") or []
                            meta = {
                                "message_type": "guild",
                                "message_id": msg_id,
                                "sender_id": sender,
                                "channel_id": channel_id,
                                "guild_id": guild_id,
                                "incoming_raw": d,
                                "attachments": att,
                            }
                            native = {
                                "channel_id": "qq",
                                "sender_id": sender,
                                "content_parts": [
                                    TextContent(
                                        type=ContentType.TEXT,
                                        text=text,
                                    ),
                                ],
                                "meta": meta,
                            }
                            request = self.build_agent_request_from_native(
                                native,
                            )
                            request.channel_meta = meta
                            if self._enqueue is not None:
                                self._enqueue(request)
                            logger.info(
                                "qq recv guild from=%s channel=%s text=%r",
                                sender,
                                channel_id,
                                text[:100],
                            )
                        elif t == "DIRECT_MESSAGE_CREATE":
                            author = (d or {}).get("author") or {}
                            text = ((d or {}).get("content") or "").strip()
                            if not text and not (d or {}).get("attachments"):
                                continue
                            if self.bot_prefix and text.startswith(
                                self.bot_prefix,
                            ):
                                continue
                            sender = (
                                author.get("id")
                                or author.get("username")
                                or ""
                            )
                            if not sender:
                                continue
                            channel_id = (d or {}).get("channel_id", "")
                            guild_id = (d or {}).get("guild_id", "")
                            msg_id = (d or {}).get("id", "")
                            att = (d or {}).get("attachments") or []
                            meta = {
                                "message_type": "dm",
                                "message_id": msg_id,
                                "sender_id": sender,
                                "channel_id": channel_id,
                                "guild_id": guild_id,
                                "incoming_raw": d,
                                "attachments": att,
                            }
                            native = {
                                "channel_id": "qq",
                                "sender_id": sender,
                                "content_parts": [
                                    TextContent(
                                        type=ContentType.TEXT,
                                        text=text,
                                    ),
                                ],
                                "meta": meta,
                            }
                            request = self.build_agent_request_from_native(
                                native,
                            )
                            request.channel_meta = meta
                            if self._enqueue is not None:
                                self._enqueue(request)
                            logger.info(
                                "qq recv dm from=%s text=%r",
                                sender,
                                text[:100],
                            )
                        elif t == "GROUP_AT_MESSAGE_CREATE":
                            author = (d or {}).get("author") or {}
                            text = ((d or {}).get("content") or "").strip()
                            if not text and not (d or {}).get("attachments"):
                                continue
                            if self.bot_prefix and text.startswith(
                                self.bot_prefix,
                            ):
                                continue
                            sender = (
                                author.get("member_openid")
                                or author.get("id")
                                or ""
                            )
                            if not sender:
                                continue
                            group_openid = (d or {}).get("group_openid", "")
                            msg_id = (d or {}).get("id", "")
                            att = (d or {}).get("attachments") or []
                            meta = {
                                "message_type": "group",
                                "message_id": msg_id,
                                "sender_id": sender,
                                "group_openid": group_openid,
                                "incoming_raw": d,
                                "attachments": att,
                            }
                            native = {
                                "channel_id": "qq",
                                "sender_id": sender,
                                "content_parts": [
                                    TextContent(
                                        type=ContentType.TEXT,
                                        text=text,
                                    ),
                                ],
                                "meta": meta,
                            }
                            request = self.build_agent_request_from_native(
                                native,
                            )
                            request.channel_meta = meta
                            if self._enqueue is not None:
                                self._enqueue(request)
                            logger.info(
                                "qq recv group from=%s group=%s text=%r",
                                sender,
                                group_openid,
                                text[:100],
                            )
                    elif op == OP_HEARTBEAT_ACK:
                        logger.debug("qq heartbeat ack")
                    elif op == OP_RECONNECT:
                        logger.info("qq server requested reconnect")
                        break
                    elif op == OP_INVALID_SESSION:
                        can_resume = d
                        logger.error(
                            "qq invalid session can_resume=%s",
                            can_resume,
                        )
                        if not can_resume:
                            session_id = None
                            last_seq = None
                            identify_fail_count += 1
                            should_refresh_token = True
                        break
            except websocket.WebSocketConnectionClosedException:
                pass
            except Exception as e:
                logger.exception("qq ws loop: %s", e)
            finally:
                stop_heartbeat()
                try:
                    current_ws.close()
                except Exception:
                    pass
            last_connect_time_val = last_connect_time
            if (
                last_connect_time_val
                and (time.time() - last_connect_time_val)
                < QUICK_DISCONNECT_THRESHOLD
            ):
                quick_disconnect_count += 1
                if quick_disconnect_count >= MAX_QUICK_DISCONNECT_COUNT:
                    session_id = None
                    last_seq = None
                    should_refresh_token = True
                    quick_disconnect_count = 0
                    reconnect_attempts = min(
                        reconnect_attempts,
                        len(RECONNECT_DELAYS) - 1,
                    )
                    delay = RATE_LIMIT_DELAY
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
                logger.error("qq max reconnect attempts reached")
                return False
            logger.info(
                "qq reconnecting in %ss (attempt %s)",
                delay,
                reconnect_attempts,
            )
            self._stop_event.wait(timeout=delay)
            return not self._stop_event.is_set()

        while connect():
            pass
        self._stop_event.set()
        logger.info("qq ws thread stopped")

    async def start(self) -> None:
        if not self.enabled:
            logger.debug("qq channel disabled by QQ_CHANNEL_ENABLED=0")
            return
        if not self.app_id or not self.client_secret:
            raise RuntimeError(
                "QQ_APP_ID and QQ_CLIENT_SECRET are required when "
                "channel is enabled.",
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
        if self._ws_thread:
            self._ws_thread.join(timeout=8)
        if self._http is not None:
            await self._http.close()
            self._http = None
