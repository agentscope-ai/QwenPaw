# -*- coding: utf-8 -*-
# pylint: disable=too-many-statements,too-many-branches,protected-access
# pylint: disable=too-many-return-statements,unused-argument
"""Feishu (Lark) Channel.

Uses lark-oapi (https://github.com/larksuite/oapi-sdk-python) WebSocket
long connection to receive events (no public IP). Sends via Open API
(tenant_access_token). Supports text, image, file; group chat context:
chat_id and message_id are put in message metadata for downstream
deduplication.
"""

from __future__ import annotations

import os
import base64
import asyncio
import json
import logging
import re
import sys
import threading
import time
from email.utils import parsedate_to_datetime
import types
from collections import OrderedDict
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import httpx
from agentscope_runtime.engine.schemas.agent_schemas import (
    AudioContent,
    FileContent,
    ImageContent,
    RunStatus,
    TextContent,
)

from ....config.config import FeishuConfig as FeishuChannelConfig
from ....config.utils import get_config_path
from ....constant import DEFAULT_MEDIA_DIR
from ..base import (
    BaseChannel,
    ContentType,
    OnReplySent,
    OutgoingContentPart,
    ProcessHandler,
)
from ..utils import file_url_to_local_path
from .constants import (
    FEISHU_FILE_MAX_BYTES,
    FEISHU_NICKNAME_CACHE_MAX,
    FEISHU_PROCESSED_IDS_MAX,
    FEISHU_STALE_MSG_THRESHOLD_MS,
    FEISHU_WS_BACKOFF_FACTOR,
    FEISHU_WS_INITIAL_RETRY_DELAY,
    FEISHU_WS_MAX_RETRY_DELAY,
)
from .utils import (
    build_interactive_content_chunks,
    detect_file_ext,
    extract_json_key,
    extract_post_image_keys,
    extract_post_media_file_keys,
    extract_post_text,
    normalize_feishu_md,
    sender_display_string,
    short_session_id_from_full_id,
)


# Compatibility for setuptools>=82 where pkg_resources may be absent.
# lark-oapi imports pkg_resources.declare_namespace from its vendored protobuf
# package init; install a minimal shim only while importing lark-oapi.
def _declare_namespace_shim(_name: str) -> None:
    return None


_PKG_RESOURCES_MISSING = object()
_original_pkg_resources: Any = sys.modules.get(
    "pkg_resources",
    _PKG_RESOURCES_MISSING,
)
_pkg_resources_shim: Optional[types.ModuleType] = None
_pkg_resources_module: Any = None
_declare_namespace_patched = False

try:
    import pkg_resources as _pkg_resources_module  # type: ignore
except ImportError:  # pragma: no cover - pkg_resources absent (setuptools>=82)
    _pkg_resources_shim = types.ModuleType("pkg_resources")
    _pkg_resources_shim.declare_namespace = (  # type: ignore[attr-defined]
        _declare_namespace_shim
    )
    sys.modules["pkg_resources"] = _pkg_resources_shim
else:
    if not hasattr(_pkg_resources_module, "declare_namespace"):
        setattr(
            _pkg_resources_module,
            "declare_namespace",
            _declare_namespace_shim,
        )
        _declare_namespace_patched = True

try:
    import lark_oapi as lark
    from lark_oapi.api.contact.v3 import GetUserRequest
    from lark_oapi.api.im.v1 import (
        CreateFileRequest,
        CreateFileRequestBody,
        CreateImageRequest,
        CreateImageRequestBody,
        CreateMessageRequest,
        CreateMessageRequestBody,
        CreateMessageReactionRequest,
        CreateMessageReactionRequestBody,
        Emoji,
        GetMessageResourceRequest,
        P2ImMessageReceiveV1,
    )
except ImportError:  # pragma: no cover - optional dependency may be missing
    lark = None  # type: ignore[assignment]
    GetUserRequest = None  # type: ignore[assignment]
    CreateFileRequest = None  # type: ignore[assignment]
    CreateFileRequestBody = None  # type: ignore[assignment]
    CreateImageRequest = None  # type: ignore[assignment]
    CreateImageRequestBody = None  # type: ignore[assignment]
    CreateMessageRequest = None  # type: ignore[assignment]
    CreateMessageRequestBody = None  # type: ignore[assignment]
    CreateMessageReactionRequest = None  # type: ignore[assignment]
    CreateMessageReactionRequestBody = None  # type: ignore[assignment]
    Emoji = None  # type: ignore[assignment]
    GetMessageResourceRequest = None  # type: ignore[assignment]
    P2ImMessageReceiveV1 = None  # type: ignore[assignment]
finally:
    if (
        _pkg_resources_shim is not None
        and sys.modules.get("pkg_resources") is _pkg_resources_shim
    ):
        if _original_pkg_resources is _PKG_RESOURCES_MISSING:
            del sys.modules["pkg_resources"]
        else:
            sys.modules["pkg_resources"] = _original_pkg_resources
    if _declare_namespace_patched and _pkg_resources_module is not None:
        if (
            getattr(_pkg_resources_module, "declare_namespace", None)
            is _declare_namespace_shim
        ):
            delattr(_pkg_resources_module, "declare_namespace")

if TYPE_CHECKING:
    from agentscope_runtime.engine.schemas.agent_schemas import AgentRequest

logger = logging.getLogger(__name__)

# Serialise multi-instance WebSocket start-up: lark_oapi.ws.client.loop is a

# Streaming card constants
_STREAMING_ELEMENT_ID = "content"
_STREAMING_UPDATE_INTERVAL_SEC = 0.06
_STREAMING_ENV_KEY = "FEISHU_STREAMING_ENABLED"
# module-level variable that concurrent start() calls would overwrite.
_WS_START_LOCK: threading.Lock = threading.Lock()


class FeishuChannel(BaseChannel):
    """Feishu/Lark channel: WebSocket receive, Open API send.

    Session: for group chat session_id = feishu:chat_id:<chat_id>, for p2p
    feishu:open_id:<open_id>. We store (receive_id, receive_id_type) so
    proactive send and reply work. Chat ID and message ID are set on
    the first message metadata for downstream deduplication.
    """

    channel = "feishu"

    def __init__(
        self,
        process: ProcessHandler,
        enabled: bool,
        app_id: str,
        app_secret: str,
        bot_prefix: str,
        encrypt_key: str = "",
        verification_token: str = "",
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
        require_mention: bool = False,
        domain: str = "feishu",
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
        self.app_id = app_id
        self.app_secret = app_secret
        self.bot_prefix = bot_prefix
        self.encrypt_key = encrypt_key or ""
        self.verification_token = verification_token or ""
        self.domain = domain if domain in ("feishu", "lark") else "feishu"
        self._workspace_dir = (
            Path(workspace_dir).expanduser() if workspace_dir else None
        )
        # Use workspace-specific media dir if workspace_dir is provided
        if not media_dir and self._workspace_dir:
            self._media_dir = self._workspace_dir / "media"
        elif media_dir:
            self._media_dir = Path(media_dir).expanduser()
        else:
            self._media_dir = DEFAULT_MEDIA_DIR
        self._media_dir.mkdir(parents=True, exist_ok=True)

        self._client: Any = None
        self._ws_client: Any = None
        self._ws_thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ws_loop: Optional[asyncio.AbstractEventLoop] = None
        self._closed = False
        self._stop_event = threading.Event()
        self._http_client: Any = None
        # Clock offset (ms) = server_time - local_time
        self._clock_offset: int = 0

        self._bot_open_id: Optional[str] = None

        # message_id dedup (ordered, trim when over limit)
        self._processed_message_ids: OrderedDict[str, None] = OrderedDict()
        # session_id -> (receive_id, receive_id_type) for send
        self._receive_id_store: Dict[str, Tuple[str, str]] = {}
        self._receive_id_lock = asyncio.Lock()
        # open_id -> nickname (from Contact API) for sender display
        self._nickname_cache: Dict[str, str] = {}
        self._nickname_cache_lock = asyncio.Lock()

    @classmethod
    def from_env(
        cls,
        process: ProcessHandler,
        on_reply_sent: OnReplySent = None,
    ) -> "FeishuChannel":
        allow_from_env = os.getenv("FEISHU_ALLOW_FROM", "")
        allow_from = (
            [s.strip() for s in allow_from_env.split(",") if s.strip()]
            if allow_from_env
            else []
        )
        return cls(
            process=process,
            enabled=os.getenv("FEISHU_CHANNEL_ENABLED", "0") == "1",
            app_id=os.getenv("FEISHU_APP_ID", ""),
            app_secret=os.getenv("FEISHU_APP_SECRET", ""),
            bot_prefix=os.getenv("FEISHU_BOT_PREFIX", ""),
            encrypt_key=os.getenv("FEISHU_ENCRYPT_KEY", ""),
            verification_token=os.getenv("FEISHU_VERIFICATION_TOKEN", ""),
            media_dir=os.getenv("FEISHU_MEDIA_DIR", ""),
            on_reply_sent=on_reply_sent,
            dm_policy=os.getenv("FEISHU_DM_POLICY", "open"),
            group_policy=os.getenv("FEISHU_GROUP_POLICY", "open"),
            allow_from=allow_from,
            deny_message=os.getenv("FEISHU_DENY_MESSAGE", ""),
            require_mention=os.getenv("FEISHU_REQUIRE_MENTION", "0") == "1",
            domain=os.getenv("FEISHU_DOMAIN", "feishu"),
        )

    @classmethod
    def from_config(
        cls,
        process: ProcessHandler,
        config: FeishuChannelConfig,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
        workspace_dir: Path | None = None,
    ) -> "FeishuChannel":
        return cls(
            process=process,
            enabled=config.enabled,
            app_id=config.app_id or "",
            app_secret=config.app_secret or "",
            bot_prefix=config.bot_prefix or "",
            encrypt_key=config.encrypt_key or "",
            verification_token=config.verification_token or "",
            media_dir=config.media_dir or "",
            workspace_dir=workspace_dir,
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            filter_thinking=filter_thinking,
            dm_policy=config.dm_policy or "open",
            group_policy=config.group_policy or "open",
            allow_from=config.allow_from or [],
            deny_message=config.deny_message or "",
            require_mention=config.require_mention,
            domain=config.domain or "feishu",
        )

    def resolve_session_id(
        self,
        sender_id: str,
        channel_meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Session_id = short suffix of chat_id or open_id for cron lookup."""
        meta = channel_meta or {}
        chat_id = (meta.get("feishu_chat_id") or "").strip()
        chat_type = (meta.get("feishu_chat_type") or "p2p").strip()
        if chat_type == "group" and chat_id:
            # Include app_id suffix to distinguish multiple bots in same group
            app_suffix = (
                self.app_id[-4:] if len(self.app_id) >= 4 else self.app_id
            )
            return f"{app_suffix}_{short_session_id_from_full_id(chat_id)}"
        if sender_id:
            return short_session_id_from_full_id(sender_id)
        if chat_id:
            return short_session_id_from_full_id(chat_id)
        return f"{self.channel}:{sender_id}"

    def build_agent_request_from_native(
        self,
        native_payload: Any,
    ) -> "AgentRequest":
        """Build AgentRequest from Feishu native dict (content_parts)."""
        from agentscope_runtime.engine.schemas.agent_schemas import (
            AgentRequest,
        )

        payload = native_payload if isinstance(native_payload, dict) else {}
        channel_id = payload.get("channel_id") or self.channel
        sender_id = payload.get("sender_id") or ""
        content_parts = payload.get("content_parts") or []
        meta = payload.get("meta") or {}
        # Use payload.session_id when present (e.g. merged native) so we do
        # not recompute from sender_display (e.g. "949#1d1a") which would
        # produce wrong short id and break to_handle -> receive_id resolution.
        session_id = payload.get("session_id") or self.resolve_session_id(
            sender_id,
            meta,
        )
        # Prefer real open_id from meta for user_id so to_handle is
        # feishu:sw:{session_id}; fallback to sender_id for display.
        user_id = (
            meta.get("feishu_sender_id") or payload.get("user_id") or sender_id
        )
        request = self.build_agent_request_from_user_content(
            channel_id=channel_id,
            sender_id=user_id,
            session_id=session_id,
            content_parts=content_parts,
            channel_meta=meta,
        )
        # Ensure channel_meta is on request for _before_consume_process
        # (AgentRequest may not have the field; base also sets from payload).
        setattr(request, "channel_meta", meta)
        return request

    def merge_native_items(self, items: List[Any]) -> Any:
        """
        Merge same-session native payloads: concat content_parts, last meta.
        """
        if not items:
            return None
        first = items[0] if isinstance(items[0], dict) else {}
        merged_parts: List[Any] = []
        for it in items:
            p = it if isinstance(it, dict) else {}
            merged_parts.extend(p.get("content_parts") or [])
        last = items[-1] if isinstance(items[-1], dict) else {}
        return {
            "channel_id": first.get("channel_id") or self.channel,
            "sender_id": last.get("sender_id", first.get("sender_id", "")),
            "user_id": last.get("user_id", first.get("user_id", "")),
            "session_id": last.get("session_id", first.get("session_id", "")),
            "content_parts": merged_parts,
            "meta": dict(last.get("meta") or {}),
        }

    def to_handle_from_target(self, *, user_id: str, session_id: str) -> str:
        # Key by short session_id so cron/job can use same id to look up.
        if session_id:
            return f"feishu:sw:{session_id}"
        return f"feishu:open_id:{user_id}"

    def _route_from_handle(self, to_handle: str) -> Dict[str, str]:
        """Parse to_handle -> receive_id_type, receive_id (or session_key for
        feishu:sw:<short_id>; caller uses _load_receive_id for that).
        """
        s = (to_handle or "").strip()
        if s.startswith("feishu:sw:"):
            return {"session_key": s.replace("feishu:sw:", "", 1)}
        if s.startswith("feishu:chat_id:"):
            return {
                "receive_id_type": "chat_id",
                "receive_id": s.replace("feishu:chat_id:", "", 1),
            }
        if s.startswith("feishu:open_id:"):
            return {
                "receive_id_type": "open_id",
                "receive_id": s.replace("feishu:open_id:", "", 1),
            }
        if s.startswith("oc_"):
            return {"receive_id_type": "chat_id", "receive_id": s}
        if s.startswith("ou_"):
            return {"receive_id_type": "open_id", "receive_id": s}
        return {"receive_id_type": "open_id", "receive_id": s}

    async def _fetch_bot_open_id(self) -> Optional[str]:
        """Get this bot's open_id via raw HTTP request.

        No SDK API available for bot info.
        """
        if not self._http_client:
            logger.warning("feishu: http client not initialized")
            return None
        try:
            # Get access token via SDK TokenManager
            from lark_oapi.core.token import TokenManager

            token = TokenManager.get_self_tenant_token(self._client._config)
            if not token:
                logger.warning("feishu: failed to get access token")
                return None
            base_url = (
                "https://open.larksuite.com"
                if self.domain == "lark"
                else "https://open.feishu.cn"
            )
            url = f"{base_url}/open-apis/bot/v3/info"
            response = await self._http_client.get(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                timeout=10.0,
            )
            # Compute clock offset from server Date header
            date_str = response.headers.get("Date")
            if date_str:
                try:
                    server_ms = int(
                        parsedate_to_datetime(date_str).timestamp() * 1000,
                    )
                    self._clock_offset = server_ms - int(time.time() * 1000)
                    logger.debug(
                        "feishu clock offset: %dms",
                        self._clock_offset,
                    )
                except (ValueError, TypeError) as e:
                    logger.debug("feishu failed to parse Date header: %s", e)
            data = response.json()
            if data.get("code", -1) != 0:
                logger.warning(
                    "feishu bot/v3/info error: code=%s msg=%s",
                    data.get("code"),
                    data.get("msg"),
                )
                return None
            return (data.get("bot") or {}).get("open_id")
        except Exception as e:
            logger.warning("feishu bot info failed: %s", e)
            return None

    async def _get_user_name_by_open_id(self, open_id: str) -> Optional[str]:
        """Fetch user name (nickname) from Feishu Contact API by open_id.

        Uses SDK contact.v3.user.get with user_id_type=open_id.
        Result is cached. Returns None on failure or missing permission.
        """
        if not open_id or open_id.startswith("unknown_"):
            return None
        async with self._nickname_cache_lock:
            if open_id in self._nickname_cache:
                return self._nickname_cache[open_id]
        try:
            req = (
                GetUserRequest.builder()
                .user_id(open_id)
                .user_id_type("open_id")
                .build()
            )
            resp = self._client.contact.v3.user.get(req)
            if not resp.success():
                logger.info(
                    "feishu get user name api error: open_id=%s code=%s "
                    "msg=%s",
                    open_id[:20],
                    getattr(resp, "code", ""),
                    getattr(resp, "msg", ""),
                )
                return None
            # Extract name from SDK response
            user = getattr(resp.data, "user", None) if resp.data else None
            name = None
            if user:
                # Try different name fields
                for attr in ("name", "en_name", "nickname"):
                    raw_name = getattr(user, attr, None)
                    if isinstance(raw_name, str) and raw_name.strip():
                        name = raw_name.strip()
                        break
            if not name:
                logger.info(
                    "feishu get user name: no name in response (open_id"
                    "=%s). app likely missing contact name permission.",
                    (open_id or "")[:20],
                )

            if name:
                async with self._nickname_cache_lock:
                    if len(self._nickname_cache) >= FEISHU_NICKNAME_CACHE_MAX:
                        # Drop oldest: dict has no order, drop arbitrary
                        self._nickname_cache.pop(
                            next(iter(self._nickname_cache)),
                        )
                    self._nickname_cache[open_id] = name
                return name
        except asyncio.TimeoutError:
            logger.debug(
                "feishu get user name timeout: open_id=%s",
                open_id[:16],
            )
        except Exception:
            logger.debug(
                "feishu get user name failed: open_id=%s",
                open_id[:16],
                exc_info=True,
            )
        return None

    def _emit_request_threadsafe(self, request: Any) -> None:
        """Enqueue request via manager (thread-safe)."""
        if self._enqueue is not None:
            self._enqueue(request)

    def _on_message_sync(self, data: "P2ImMessageReceiveV1") -> None:
        """Sync handler (called from WebSocket thread)."""
        if self._closed:
            return
        # Guard against cross-instance dispatch: lark_oapi ws.Client uses a
        # module-level event loop variable that can be overwritten by another
        # FeishuChannel instance in the same process.  Verify the event's
        # app_id matches this instance before dispatching to avoid handling
        # messages intended for a different workspace.
        header = getattr(data, "header", None)
        event_app_id = getattr(header, "app_id", None)
        if event_app_id and event_app_id != self.app_id:
            logger.debug(
                "feishu: drop misrouted event app_id=%s (expected %s)",
                event_app_id,
                self.app_id,
            )
            return

        # Drop stale messages from Feishu retry mechanism.
        # Feishu retries failed deliveries at 5s, 5min, 1h, 6h intervals.
        # Messages older than 20 seconds are likely stale retries.
        # Use clock_offset to correct local clock skew against server time.
        create_time = getattr(header, "create_time", None)
        if create_time:
            now_ms = int(time.time() * 1000) + self._clock_offset
            age_ms = now_ms - int(create_time)
            if age_ms > FEISHU_STALE_MSG_THRESHOLD_MS:
                logger.debug(
                    "feishu: drop stale message age=%.1fs (retry)",
                    age_ms / 1000,
                )
                return

        if not self._loop:
            logger.warning("feishu: main loop not set, drop message")
            return
        if not self._loop.is_running():
            logger.warning("feishu: main loop not running, drop message")
            return
        asyncio.run_coroutine_threadsafe(
            self._on_message(data),
            self._loop,
        )

    async def _on_message(self, data: "P2ImMessageReceiveV1") -> None:
        """Handle one Feishu message: dedup, parse, download media, enqueue."""
        if not data or not getattr(data, "event", None):
            return
        try:
            event = data.event
            message = getattr(event, "message", None)
            sender = getattr(event, "sender", None)
            if not message or not sender:
                return

            message_id = getattr(message, "message_id", None) or ""
            message_id = str(message_id).strip()
            if message_id in self._processed_message_ids:
                return
            self._processed_message_ids[message_id] = None
            while len(self._processed_message_ids) > FEISHU_PROCESSED_IDS_MAX:
                self._processed_message_ids.popitem(last=False)

            sender_type = getattr(sender, "sender_type", "") or ""
            if sender_type == "bot":
                return

            sender_id_obj = getattr(sender, "sender_id", None)
            sender_id = ""
            if sender_id_obj and getattr(sender_id_obj, "open_id", None):
                sender_id = str(getattr(sender_id_obj, "open_id", "")).strip()
            if not sender_id:
                sender_id = f"unknown_{message_id[:8]}"

            nickname = (
                getattr(sender, "name", None)
                or getattr(sender, "nickname", None)
                or ""
            )
            nickname = nickname.strip() if isinstance(nickname, str) else ""
            if not nickname:
                nickname = await self._get_user_name_by_open_id(sender_id)
            sender_display = sender_display_string(nickname, sender_id)

            chat_id = str(getattr(message, "chat_id", "") or "").strip()
            chat_type = str(
                getattr(message, "chat_type", "p2p") or "p2p",
            ).strip()
            msg_type = str(
                getattr(message, "message_type", "text") or "text",
            ).strip()
            content_raw = getattr(message, "content", None) or ""

            mentions_raw = getattr(message, "mentions", None) or []
            is_bot_mentioned = False
            bot_mention_keys: List[str] = []
            if "@_all" in content_raw:
                is_bot_mentioned = True
            if self._bot_open_id and mentions_raw:
                for m in mentions_raw:
                    m_id = getattr(m, "id", None)
                    if not m_id:
                        continue
                    m_open_id = getattr(m_id, "open_id", None) or ""
                    if m_open_id == self._bot_open_id:
                        is_bot_mentioned = True
                        key = getattr(m, "key", None) or ""
                        if key:
                            bot_mention_keys.append(key)

            content_parts: List[Any] = []
            text_parts: List[str] = []

            if msg_type == "text":
                text = extract_json_key(content_raw, "text")
                if text:
                    for key in bot_mention_keys:
                        text = text.replace(key, "")
                    text = text.strip()
                if text:
                    text_parts.append(text)
            elif msg_type == "post":
                text = extract_post_text(content_raw)
                if text:
                    text_parts.append(text)
                # Download images in post message
                for img_key in extract_post_image_keys(content_raw):
                    url_or_path = await self._download_image_resource(
                        message_id,
                        img_key,
                    )
                    if url_or_path:
                        content_parts.append(
                            ImageContent(
                                type=ContentType.IMAGE,
                                image_url=url_or_path,
                            ),
                        )
                    else:
                        text_parts.append("[image: download failed]")
                # Download media files in post message
                for file_key in extract_post_media_file_keys(content_raw):
                    url_or_path = await self._download_file_resource(
                        message_id,
                        file_key,
                    )
                    if url_or_path:
                        content_parts.append(
                            FileContent(
                                type=ContentType.FILE,
                                file_url=url_or_path,
                            ),
                        )
                    else:
                        text_parts.append("[media: download failed]")
            elif msg_type == "image":
                image_key = extract_json_key(
                    content_raw,
                    "image_key",
                    "file_key",
                    "imageKey",
                    "fileKey",
                )
                if image_key:
                    url_or_path = await self._download_image_resource(
                        message_id,
                        image_key,
                    )
                    if url_or_path:
                        content_parts.append(
                            ImageContent(
                                type=ContentType.IMAGE,
                                image_url=url_or_path,
                            ),
                        )
                    else:
                        text_parts.append("[image: download failed]")
                else:
                    text_parts.append("[image: missing key]")
            elif msg_type == "file":
                file_key = extract_json_key(
                    content_raw,
                    "file_key",
                    "fileKey",
                )
                file_name = extract_json_key(
                    content_raw,
                    "file_name",
                    "fileName",
                )
                if file_key:
                    url_or_path = await self._download_file_resource(
                        message_id,
                        file_key,
                        filename_hint=file_name or "file.bin",
                    )
                    if url_or_path:
                        content_parts.append(
                            FileContent(
                                type=ContentType.FILE,
                                file_url=url_or_path,
                            ),
                        )
                    else:
                        text_parts.append("[file: download failed]")
                else:
                    text_parts.append("[file: missing key]")
            elif msg_type == "media":
                # Video message type
                file_key = extract_json_key(
                    content_raw,
                    "file_key",
                    "fileKey",
                )
                file_name = extract_json_key(
                    content_raw,
                    "file_name",
                    "fileName",
                )
                if file_key:
                    url_or_path = await self._download_file_resource(
                        message_id,
                        file_key,
                        filename_hint=file_name or "video.mp4",
                    )
                    if url_or_path:
                        content_parts.append(
                            FileContent(
                                type=ContentType.FILE,
                                file_url=url_or_path,
                            ),
                        )
                    else:
                        text_parts.append("[video: download failed]")
                else:
                    text_parts.append("[video: missing key]")
            elif msg_type == "audio":
                file_key = extract_json_key(
                    content_raw,
                    "file_key",
                    "fileKey",
                )
                if file_key:
                    url_or_path = await self._download_file_resource(
                        message_id,
                        file_key,
                        filename_hint="audio.opus",
                    )
                    if url_or_path:
                        content_parts.append(
                            AudioContent(
                                type=ContentType.AUDIO,
                                data=url_or_path,
                            ),
                        )
                    else:
                        text_parts.append("[audio: download failed]")
                else:
                    text_parts.append("[audio: missing key]")
            else:
                text_parts.append(f"[{msg_type}]")

            text = "\n".join(text_parts).strip() if text_parts else ""
            if text:
                content_parts.insert(
                    0,
                    TextContent(type=ContentType.TEXT, text=text),
                )
            if not content_parts:
                return

            is_group = chat_type == "group"
            meta: Dict[str, Any] = {
                "feishu_message_id": message_id,
                "feishu_chat_id": chat_id,
                "feishu_chat_type": chat_type,
                "feishu_sender_id": sender_id,
                "is_group": is_group,
            }
            receive_id = chat_id if is_group else sender_id
            receive_id_type = "chat_id" if is_group else "open_id"
            meta["feishu_receive_id"] = receive_id
            meta["feishu_receive_id_type"] = receive_id_type
            if is_bot_mentioned:
                meta["bot_mentioned"] = True

            allowed, error_msg = self._check_allowlist(
                sender_id,
                is_group,
            )
            if not allowed:
                logger.info(
                    "feishu allowlist blocked: sender=%s is_group=%s",
                    sender_id,
                    is_group,
                )
                await self._send_text(
                    receive_id_type,
                    receive_id,
                    error_msg or "",
                )
                return

            if not self._check_group_mention(is_group, meta):
                return

            await self._add_reaction(message_id, "Typing")

            session_id = self.resolve_session_id(sender_id, meta)
            native = {
                "channel_id": self.channel,
                "sender_id": sender_display,
                "user_id": sender_display,
                "session_id": session_id,
                "content_parts": content_parts,
                "meta": meta,
            }
            logger.info(
                "feishu recv from=%s chat=%s msg_id=%s type=%s text_len=%s",
                sender_display[:40],
                chat_id[:20] if chat_id else "",
                message_id[:16] if message_id else "",
                msg_type,
                len(text),
            )
            if self._enqueue is not None:
                self._enqueue(native)
        except Exception:
            logger.exception("feishu _on_message failed")

    async def _add_reaction(
        self,
        message_id: str,
        emoji_type: str = "THUMBSUP",
    ) -> None:
        """Add reaction to message (non-blocking)."""
        if not self._client:
            return
        try:
            req = (
                CreateMessageReactionRequest.builder()
                .message_id(message_id)
                .request_body(
                    CreateMessageReactionRequestBody.builder()
                    .reaction_type(
                        Emoji.builder().emoji_type(emoji_type).build(),
                    )
                    .build(),
                )
                .build()
            )
            resp = await self._client.im.v1.message_reaction.acreate(req)
            if not resp.success():
                logger.debug(
                    "feishu reaction failed code=%s msg=%s",
                    getattr(resp, "code", ""),
                    getattr(resp, "msg", ""),
                )
        except Exception as e:
            logger.debug("feishu reaction error: %s", e)

    async def _download_image_resource(
        self,
        message_id: str,
        image_key: str,
    ) -> Optional[str]:
        """Download image to media_dir using SDK; return local path or None."""
        try:
            req = (
                GetMessageResourceRequest.builder()
                .message_id(message_id)
                .file_key(image_key)
                .type("image")
                .build()
            )
            resp = await self._client.im.v1.message_resource.aget(req)
            if not resp.success():
                logger.warning(
                    "feishu image download failed code=%s msg=%s",
                    getattr(resp, "code", ""),
                    getattr(resp, "msg", ""),
                )
                return None
            # resp.file is a file-like object
            data = resp.file.read() if resp.file else b""
            if not data:
                logger.warning("feishu image download: empty response")
                return None
            ext = detect_file_ext(data, default="jpg")
            safe_key = (
                "".join(c for c in image_key if c.isalnum() or c in "-_.")
                or "img"
            )
            self._media_dir.mkdir(parents=True, exist_ok=True)
            path = self._media_dir / f"{message_id}_{safe_key}.{ext}"
            await asyncio.to_thread(path.write_bytes, data)
            return str(path)
        except Exception:
            logger.exception("feishu _download_image_resource failed")
            return None

    async def _download_file_resource(
        self,
        message_id: str,
        file_key: str,
        filename_hint: str = "file.bin",
    ) -> Optional[str]:
        """Download file to media_dir using SDK; return local path or None."""
        try:
            req = (
                GetMessageResourceRequest.builder()
                .message_id(message_id)
                .file_key(file_key)
                .type("file")
                .build()
            )
            resp = await self._client.im.v1.message_resource.aget(req)
            if not resp.success():
                logger.warning(
                    "feishu file download failed code=%s msg=%s",
                    getattr(resp, "code", ""),
                    getattr(resp, "msg", ""),
                )
                return None
            data = resp.file.read() if resp.file else b""
            if not data:
                logger.warning("feishu file download: empty response")
                return None

            # Use original filename if provided, otherwise detect from content
            filename = Path(filename_hint).name
            if not filename.strip() or filename in ("file.bin", "video.mp4"):
                ext = detect_file_ext(data, default="bin")
                filename = f"file.{ext}"
            self._media_dir.mkdir(parents=True, exist_ok=True)
            path = self._media_dir / f"{message_id}_{filename}"
            await asyncio.to_thread(path.write_bytes, data)
            return str(path)
        except Exception:
            logger.exception("feishu _download_file_resource failed")
            return None

    def _receive_id_store_path(self) -> Path:
        """
        Path to persist receive_id mapping (for cron to resolve after restart).

        Uses agent workspace directory if available, otherwise falls back
        to global config directory for backward compatibility.
        """
        if self._workspace_dir:
            return self._workspace_dir / "feishu_receive_ids.json"
        return get_config_path().parent / "feishu_receive_ids.json"

    def _load_receive_id_store_from_disk(self) -> None:
        """
        Load receive_id mapping from disk into memory
        (call at start or on miss).
        """
        path = self._receive_id_store_path()
        if not path.is_file():
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for k, v in data.items():
                    if isinstance(v, (list, tuple)) and len(v) >= 2:
                        a, b = str(v[0]), str(v[1])
                        # Store as (receive_id_type, receive_id).
                        # Backward compat: old file has
                        # [receive_id, receive_id_type]
                        if b in ("open_id", "chat_id"):
                            self._receive_id_store[k] = (b, a)
                        else:
                            self._receive_id_store[k] = (a, b)
        except Exception:
            logger.debug(
                "feishu load receive_id store from %s failed",
                path,
                exc_info=True,
            )

    def _save_receive_id_store_to_disk(self) -> None:
        """Persist in-memory receive_id store to disk."""
        path = self._receive_id_store_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # v is (receive_id_type, receive_id)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        k: [v[0], v[1]]  # [receive_id_type, receive_id]
                        for k, v in self._receive_id_store.items()
                    },
                    f,
                    indent=2,
                    ensure_ascii=False,
                )
        except Exception:
            logger.debug(
                "feishu save receive_id store to %s failed",
                path,
                exc_info=True,
            )

    async def _save_receive_id(
        self,
        session_id: str,
        receive_id: str,
        receive_id_type: str,
    ) -> None:
        if not session_id or not receive_id:
            return
        async with self._receive_id_lock:
            # Store (receive_id_type, receive_id) to match unpack elsewhere
            self._receive_id_store[session_id] = (receive_id_type, receive_id)
            # Also key by open_id so cron can resolve when session_id is full
            # open_id or when lookup uses open_id as key
            if (
                receive_id_type == "open_id"
                and receive_id
                and receive_id != session_id
            ):
                self._receive_id_store[receive_id] = (
                    receive_id_type,
                    receive_id,
                )
            self._save_receive_id_store_to_disk()

    async def _load_receive_id(
        self,
        session_id: str,
    ) -> Optional[Tuple[str, str]]:
        if not session_id:
            return None
        async with self._receive_id_lock:
            out = self._receive_id_store.get(session_id)
            if out is not None:
                return out
            self._load_receive_id_store_from_disk()
            return self._receive_id_store.get(session_id)

    def _build_post_content(
        self,
        text: str,
        image_keys: List[str],
    ) -> Dict[str, Any]:
        content_rows: List[List[Dict[str, Any]]] = []
        if text:
            content_rows.append(
                [{"tag": "md", "text": normalize_feishu_md(text)}],
            )
        for image_key in image_keys:
            content_rows.append([{"tag": "img", "image_key": image_key}])
        if not content_rows:
            content_rows = [[{"tag": "md", "text": "[empty]"}]]
        return {
            "zh_cn": {
                "content": content_rows,
            },
        }

    async def _upload_image(
        self,
        data: bytes,
        filename: str,
    ) -> Optional[str]:
        """Upload image via lark client; return image_key."""
        if not self._client:
            return None
        logger.info(
            "feishu _upload_image: size=%s filename=%s",
            len(data),
            filename,
        )
        try:
            import io

            req = (
                CreateImageRequest.builder()
                .request_body(
                    CreateImageRequestBody.builder()
                    .image_type("message")
                    .image(io.BytesIO(data))
                    .build(),
                )
                .build()
            )
            resp = await self._client.im.v1.image.acreate(req)
            if not resp.success():
                logger.warning(
                    "feishu image upload failed code=%s msg=%s",
                    getattr(resp, "code", ""),
                    getattr(resp, "msg", ""),
                )
                return None
            key = getattr(resp.data, "image_key", None) if resp.data else None
            logger.info(
                "feishu _upload_image ok: image_key=%s",
                key[:24] if key else "None",
            )
            return key
        except Exception:
            logger.exception("feishu _upload_image failed")
            return None

    async def _upload_file(self, path_or_url: str) -> Optional[str]:
        """Upload file to Feishu using SDK; return file_key."""
        path = Path(path_or_url)
        if not path.exists():
            if path_or_url.startswith(("http://", "https://")):
                data = await self._fetch_bytes_from_url(path_or_url)
                if not data:
                    return None
                path = self._media_dir / "upload_temp"
                path.parent.mkdir(parents=True, exist_ok=True)
                await asyncio.to_thread(path.write_bytes, data)
            else:
                return None
        size = await asyncio.to_thread(lambda: path.stat().st_size)
        if size > FEISHU_FILE_MAX_BYTES:
            logger.warning("feishu file too large size=%s", size)
            return None
        ext = path.suffix.lower().lstrip(".")
        file_type = "stream"
        if ext in (
            "pdf",
            "doc",
            "docx",
            "xls",
            "xlsx",
            "ppt",
            "pptx",
        ):
            file_type = "doc" if ext == "docx" else ext
            file_type = "xls" if ext == "xlsx" else file_type
            file_type = "ppt" if ext == "pptx" else file_type
        file_obj = None
        try:
            file_obj = await asyncio.to_thread(path.open, "rb")
            req = (
                CreateFileRequest.builder()
                .request_body(
                    CreateFileRequestBody.builder()
                    .file_type(file_type)
                    .file_name(path.name)
                    .file(file_obj)
                    .build(),
                )
                .build()
            )
            resp = await self._client.im.v1.file.acreate(req)
            if not resp.success():
                logger.warning(
                    "feishu file upload failed code=%s msg=%s",
                    getattr(resp, "code", ""),
                    getattr(resp, "msg", ""),
                )
                return None
            fk = getattr(resp.data, "file_key", None) if resp.data else None
            logger.info(
                "feishu _upload_file ok: file_key=%s",
                fk[:24] if fk else "None",
            )
            return fk
        except Exception:
            logger.exception("feishu _upload_file failed")
            return None
        finally:
            if file_obj is not None:
                try:
                    await asyncio.to_thread(file_obj.close)
                except Exception:
                    logger.debug("feishu _upload_file: file close failed")

    async def _fetch_bytes_from_url(self, url: str) -> Optional[bytes]:
        """Download binary from URL. Supports http(s):// and file://."""
        if not self._http_client:
            logger.warning("feishu: http client not initialized")
            return None
        try:
            path = file_url_to_local_path(url)
            if path is not None:
                return await asyncio.to_thread(Path(path).read_bytes)
            if url.strip().lower().startswith("file:"):
                return None
            response = await self._http_client.get(url)
            if response.status_code >= 400:
                return None
            return response.content
        except Exception:
            logger.exception("feishu _fetch_bytes_from_url failed")
            return None

    async def _send_message(
        self,
        receive_id_type: str,
        receive_id: str,
        msg_type: str,
        content: str,
    ) -> Optional[str]:
        """Send one message (post, image, or file) via lark client.

        Returns the message_id on success, None on failure.
        """
        if not self._client:
            return None
        logger.info(
            "feishu _send_message: msg_type=%s receive_id_type=%s "
            "content_len=%s",
            msg_type,
            receive_id_type,
            len(content),
        )
        try:
            req = (
                CreateMessageRequest.builder()
                .receive_id_type(receive_id_type)
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(receive_id)
                    .msg_type(msg_type)
                    .content(content)
                    .build(),
                )
                .build()
            )
            resp = await self._client.im.v1.message.acreate(req)
            if not resp.success():
                logger.warning(
                    "feishu send failed code=%s msg=%s",
                    getattr(resp, "code", ""),
                    getattr(resp, "msg", ""),
                )
                return None
            msg_id = (
                getattr(resp.data, "message_id", None) if resp.data else None
            )
            logger.info(
                "feishu _send_message ok: msg_type=%s msg_id=%s",
                msg_type,
                (msg_id or "")[:24],
            )
            return msg_id
        except Exception:
            logger.exception("feishu _send_message failed")
            return None

    async def _send_text(
        self,
        receive_id_type: str,
        receive_id: str,
        body: str,
    ) -> Optional[str]:
        """Send text as post (md) or interactive card (when body has tables).

        Returns the message_id on success, None on failure.
        Body already has bot_prefix if needed.
        When the body contains more than _MAX_TABLES_PER_CARD tables, it
        is split into multiple cards sent sequentially.
        """
        has_table = bool(re.search(r"^\s*\|", body, re.MULTILINE))
        if has_table:
            chunks = build_interactive_content_chunks(body)
            last_msg_id: Optional[str] = None
            for chunk in chunks:
                msg_id = await self._send_message(
                    receive_id_type,
                    receive_id,
                    "interactive",
                    chunk,
                )
                if msg_id is not None:
                    last_msg_id = msg_id
            return last_msg_id
        post = self._build_post_content(body, [])
        content = json.dumps(post, ensure_ascii=False)
        return await self._send_message(
            receive_id_type,
            receive_id,
            "post",
            content,
        )

    async def _part_to_image_bytes(
        self,
        part: OutgoingContentPart,
    ) -> Tuple[Optional[bytes], str]:
        """
        Get image bytes from part (url, path, or base64). Return (data, fn).
        """
        image_url = getattr(part, "image_url", None) or ""
        url = (image_url if isinstance(image_url, str) else "").strip()
        filename = getattr(part, "filename", None) or "image.png"
        if url.startswith("data:") and "base64," in url:
            b64 = url
            url = ""
        else:
            b64 = None
        if b64:
            raw = (
                b64.split("base64,", 1)[-1].strip()
                if isinstance(b64, str)
                else b64
            )
            try:
                data = base64.b64decode(raw)
                return (data, filename)
            except Exception as e:
                logger.warning(
                    "feishu _part_to_image_bytes base64 decode failed: %s",
                    e,
                )
                return (None, filename)
        if not url and not b64:
            logger.info(
                "feishu _send_image: part has no image_url/base64",
            )
            return (None, filename)
        if url.startswith(("http://", "https://", "file://")):
            data = await self._fetch_bytes_from_url(url)
            return (data, filename)
        path = Path(url)
        if path.exists():
            return (path.read_bytes(), filename)
        logger.info(
            "feishu _send_image: path not found url=%s",
            url[:80] if url else "",
        )
        return (None, filename)

    async def _send_image(
        self,
        receive_id_type: str,
        receive_id: str,
        part: OutgoingContentPart,
    ) -> Optional[str]:
        """Upload image and send as msg_type=image (image_key) per API.

        Returns the message_id on success, None on failure.
        """
        logger.info(
            "feishu _send_image: part type=%s",
            getattr(part, "type", None),
        )
        data, filename = await self._part_to_image_bytes(part)
        if not data:
            logger.info(
                "feishu _send_image: no image data, skip (url/base64/path)",
            )
            return None
        image_key = await self._upload_image(data, filename)
        if not image_key:
            logger.info(
                "feishu _send_image: upload failed, no image_key",
            )
            return None
        logger.info(
            "feishu _send_image: upload ok image_key=%s",
            image_key[:24] if image_key else "",
        )
        content = json.dumps({"image_key": image_key}, ensure_ascii=False)
        return await self._send_message(
            receive_id_type,
            receive_id,
            "image",
            content,
        )

    async def _part_to_file_path_or_url(
        self,
        part: OutgoingContentPart,
    ) -> Optional[str]:
        """Resolve part to local path or URL for file upload."""
        url = (
            getattr(part, "file_url", None)
            or getattr(part, "image_url", None)
            or getattr(part, "video_url", None)
            or getattr(part, "data", None)
            or ""
        )
        url = (url or "").strip() if isinstance(url, str) else ""
        filename = getattr(part, "filename", None) or "file.bin"
        b64 = None
        if (
            isinstance(url, str)
            and url.startswith("data:")
            and "base64," in url
        ):
            b64 = url
            url = ""
        if b64:
            raw = (
                b64.split("base64,", 1)[-1].strip()
                if isinstance(b64, str)
                else b64
            )
            try:
                data = base64.b64decode(raw)
            except Exception as e:
                logger.warning(
                    "feishu _part_to_file_path_or_url base64 decode: %s",
                    e,
                )
                return None
            self._media_dir.mkdir(parents=True, exist_ok=True)
            path = self._media_dir / f"upload_{id(part)}_{filename}"
            path.write_bytes(data)
            return str(path)
        if url:
            if url.startswith("file://"):
                local_path = file_url_to_local_path(url)
                if local_path:
                    path = Path(local_path)
                    if path.exists():
                        return str(path)
            else:
                path = Path(url)
                if path.exists():
                    return url
                if url.startswith(("http://", "https://")):
                    return url
        logger.info(
            "feishu _send_file: part has no file_url/url/base64",
        )
        return None

    async def _send_file(
        self,
        receive_id_type: str,
        receive_id: str,
        part: OutgoingContentPart,
    ) -> Optional[str]:
        """Upload file and send file message (msg_type=file, file_key).

        Returns the message_id on success, None on failure.
        """
        logger.info(
            "feishu _send_file: part type=%s",
            getattr(part, "type", None),
        )
        path_or_url = await self._part_to_file_path_or_url(part)
        if not path_or_url:
            logger.info(
                "feishu _send_file: no path/url/base64, skip",
            )
            return None
        file_key = await self._upload_file(path_or_url)
        if not file_key:
            logger.info(
                "feishu _send_file: upload failed, no file_key",
            )
            return None
        logger.info(
            "feishu _send_file: upload ok file_key=%s",
            file_key[:24] if file_key else "",
        )
        content = json.dumps({"file_key": file_key}, ensure_ascii=False)
        return await self._send_message(
            receive_id_type,
            receive_id,
            "file",
            content,
        )

    async def _get_receive_for_send(
        self,
        to_handle: str,
        meta: Optional[Dict[str, Any]],
    ) -> Optional[Tuple[str, str]]:
        """Resolve (receive_id_type, receive_id) from to_handle or meta."""
        m = meta or {}
        rid = m.get("feishu_receive_id")
        rtype = m.get("feishu_receive_id_type", "open_id")
        if rid:
            logger.info(
                "feishu _get_receive_for_send: from meta receive_id_type=%s",
                rtype,
            )
            return (rtype, rid)
        route = self._route_from_handle(to_handle)
        session_key = route.get("session_key")
        logger.info(
            "feishu _get_receive_for_send: to_handle=%s route=%s "
            "session_key=%s",
            (to_handle or "")[:60],
            list(route.keys()) if route else [],
            (session_key or "")[:40] if session_key else None,
        )
        if session_key:
            recv = await self._load_receive_id(session_key)
            if recv is not None:
                logger.info(
                    "feishu _get_receive_for_send: loaded from store "
                    "receive_id_type=%s",
                    recv[0],
                )
                return recv
            # Fallback: session_key may be old-format "feishu:open_id:ou_xxx"
            if session_key.startswith("feishu:open_id:"):
                rid = session_key.replace("feishu:open_id:", "", 1).strip()
                if rid:
                    logger.info(
                        "feishu _get_receive_for_send: fallback open_id",
                    )
                    return ("open_id", rid)
            # Fallback: session_key may be display "nickname#last4" (e.g. from
            # cron target.user_id); try match by open_id ending with last4
            if "#" in session_key:
                suffix = session_key.split("#", 1)[-1].strip()
                if len(suffix) >= 4:
                    async with self._receive_id_lock:
                        for _, v in self._receive_id_store.items():
                            # v is (receive_id_type, receive_id)
                            if v[1] and str(v[1]).endswith(suffix):
                                logger.info(
                                    "feishu _get_receive_for_send: "
                                    "fallback match by suffix %s",
                                    suffix,
                                )
                                return v
            logger.warning(
                "feishu _get_receive_for_send: no store entry for "
                "session_key=%s (user must have chatted first or add "
                "feishu_receive_id in dispatch.meta)",
                (session_key or "")[:40],
            )
        rid = route.get("receive_id")
        rtype = route.get("receive_id_type", "open_id")
        if rid:
            return (rtype, rid)
        recv = await self._load_receive_id(to_handle)
        if recv is None:
            logger.warning(
                "feishu _get_receive_for_send: _load_receive_id(%s) returned "
                "None",
                (to_handle or "")[:40],
            )
        return recv

    async def send_content_parts(  # type: ignore[override]
        self,
        to_handle: str,
        parts: List[OutgoingContentPart],
        meta: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Send text as post (md), then images, then files.

        Returns the message_id of the last successfully sent message,
        or None if nothing was sent.
        """
        if not self.enabled:
            return None
        recv = await self._get_receive_for_send(to_handle, meta)
        if not recv:
            logger.warning(
                "feishu send_content_parts: no receive_id for to_handle=%s "
                "(cron will not send; ensure user chatted once or set "
                "dispatch.meta.feishu_receive_id)",
                to_handle[:50] if to_handle else "",
            )
            return None
        receive_id_type, receive_id = recv
        logger.info(
            "feishu send_content_parts: resolved receive_id_type=%s "
            "receive_id=%s...",
            receive_id_type,
            (receive_id or "")[:20],
        )
        prefix = (meta or {}).get("bot_prefix", "") or self.bot_prefix or ""
        text_parts: List[str] = []
        media_parts: List[OutgoingContentPart] = []
        for p in parts:
            t = getattr(p, "type", None) or (
                p.get("type") if isinstance(p, dict) else None
            )
            text_val = getattr(p, "text", None) or (
                p.get("text") if isinstance(p, dict) else None
            )
            refusal_val = getattr(p, "refusal", None) or (
                p.get("refusal") if isinstance(p, dict) else None
            )
            if t == ContentType.TEXT and text_val:
                text_parts.append(text_val or "")
            elif t == ContentType.REFUSAL and refusal_val:
                text_parts.append(refusal_val or "")
            elif t in (
                ContentType.IMAGE,
                ContentType.FILE,
                ContentType.VIDEO,
                ContentType.AUDIO,
            ):
                media_parts.append(p)
        body = "\n".join(text_parts).strip()
        logger.info(
            "feishu send_content_parts: to_handle=%s text_parts=%s "
            "media_count=%s media_types=%s",
            to_handle[:40] if to_handle else "",
            len(text_parts),
            len(media_parts),
            [getattr(m, "type", None) for m in media_parts],
        )
        if prefix and body:
            body = prefix + "  " + body
        last_message_id: Optional[str] = None
        if body:
            last_message_id = await self._send_text(
                receive_id_type,
                receive_id,
                body,
            )
        for part in media_parts:
            pt = getattr(part, "type", None)
            if pt == ContentType.IMAGE:
                msg_id = await self._send_image(
                    receive_id_type,
                    receive_id,
                    part,
                )
                logger.info(
                    "feishu send_content_parts: image sent ok=%s",
                    bool(msg_id),
                )
                if msg_id:
                    last_message_id = msg_id
            elif pt in (
                ContentType.FILE,
                ContentType.VIDEO,
                ContentType.AUDIO,
            ):
                msg_id = await self._send_file(
                    receive_id_type,
                    receive_id,
                    part,
                )
                logger.info(
                    "feishu send_content_parts: file sent ok=%s type=%s",
                    bool(msg_id),
                    pt,
                )
                if msg_id:
                    last_message_id = msg_id
        return last_message_id

    # ----- streaming card helpers

    def _is_streaming_enabled(self) -> bool:
        """Check if streaming card output is enabled via env var."""
        val = os.environ.get(_STREAMING_ENV_KEY, "").lower()
        return val in ("1", "true", "yes")

    def _next_stream_seq(self) -> int:
        """Monotonic sequence counter for streaming card updates."""
        if not hasattr(self, "_stream_seq"):
            self._stream_seq = 0
        self._stream_seq += 1
        return self._stream_seq

    def _feishu_base_url(self) -> str:
        """Resolve API base URL from domain."""
        return (
            "https://open.larksuite.com"
            if self.domain == "lark"
            else "https://open.feishu.cn"
        )

    def _streaming_auth_headers(self) -> dict:
        """Build auth headers for streaming card API calls."""
        from lark_oapi.core.token import TokenManager

        token = TokenManager.get_self_tenant_token(self._client._config)
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def _card_create(self) -> Optional[str]:
        """Step 1: create an empty streaming card. Returns card_id or None."""
        card_json = {
            "schema": "2.0",
            "config": {
                "streaming_mode": True,
                "streaming_config": {
                    "print_frequency_ms": {"default": 50},
                    "print_step": {"default": 1},
                },
            },
            "header": {
                "title": {"tag": "plain_text", "content": ""},
                "template": "invisible",
            },
            "body": {
                "elements": [
                    {
                        "tag": "markdown",
                        "element_id": _STREAMING_ELEMENT_ID,
                        "content": "⏳ 思考中...",
                    },
                ],
            },
        }
        try:
            resp = await self._http_client.post(
                f"{self._feishu_base_url()}/open-apis/cardkit/v1/cards",
                headers=self._streaming_auth_headers(),
                json={
                    "type": "card_json",
                    "data": json.dumps(card_json, ensure_ascii=False),
                },
                timeout=10.0,
            )
            if resp.status_code >= 400:
                logger.warning(
                    "card create failed: status=%d body=%s",
                    resp.status_code,
                    resp.text[:200],
                )
                return None
            data = resp.json()
            if data.get("code") != 0:
                logger.warning(
                    "card create failed: code=%s msg=%s",
                    data.get("code"),
                    data.get("msg", ""),
                )
                return None
            return data["data"]["card_id"]
        except Exception:
            logger.exception("card create error")
            return None

    async def _card_send(
        self,
        card_id: str,
        receive_id: str,
        receive_id_type: str,
    ) -> Optional[str]:
        """Step 2: send card as message. Returns message_id or None."""
        try:
            resp = await self._http_client.post(
                f"{self._feishu_base_url()}/open-apis/im/v1/messages"
                f"?receive_id_type={receive_id_type}",
                headers=self._streaming_auth_headers(),
                json={
                    "receive_id": receive_id,
                    "msg_type": "interactive",
                    "content": json.dumps(
                        {
                            "type": "card",
                            "data": {"card_id": card_id},
                        },
                    ),
                },
                timeout=10.0,
            )
            if resp.status_code >= 400:
                logger.warning(
                    "card send failed: status=%d body=%s",
                    resp.status_code,
                    resp.text[:200],
                )
                return None
            data = resp.json()
            if data.get("code") != 0:
                logger.warning(
                    "card send failed: code=%s msg=%s",
                    data.get("code"),
                    data.get("msg", ""),
                )
                return None
            return data["data"]["message_id"]
        except Exception:
            logger.exception("card send error")
            return None

    async def _card_update_text(self, card_id: str, text: str) -> bool:
        """Step 3: update streaming text element (PUT)."""
        seq = self._next_stream_seq()
        try:
            base = self._feishu_base_url()
            url = (
                f"{base}/open-apis/cardkit/v1/cards"
                f"/{card_id}/elements/{_STREAMING_ELEMENT_ID}/content"
            )
            resp = await self._http_client.put(
                url,
                headers=self._streaming_auth_headers(),
                json={
                    "content": text,
                    "sequence": seq,
                    "uuid": f"s_{card_id}_{seq}",
                },
                timeout=5.0,
            )
            if resp.status_code >= 400:
                logger.warning(
                    "card update failed: status=%d body=%s",
                    resp.status_code,
                    resp.text[:200],
                )
                return False
            return resp.json().get("code") == 0
        except Exception:
            logger.exception("card update error")
            return False

    async def _card_close(self, card_id: str) -> None:
        """Step 4: turn off streaming mode (finalize card)."""
        try:
            seq = self._next_stream_seq()
            base = self._feishu_base_url()
            url = f"{base}/open-apis/cardkit/v1/cards" f"/{card_id}/settings"
            resp = await self._http_client.patch(
                url,
                headers=self._streaming_auth_headers(),
                json={
                    "settings": json.dumps(
                        {
                            "config": {"streaming_mode": False},
                        },
                    ),
                    "sequence": seq,
                    "uuid": f"c_{card_id}_{seq}",
                },
                timeout=5.0,
            )
            if resp.status_code >= 400:
                logger.warning(
                    "card close failed: status=%d body=%s",
                    resp.status_code,
                    resp.text[:200],
                )
        except Exception:
            logger.exception("card close error")

    # ----- _stream_with_tracker override (CoPaw post-1.0 architecture)

    async def _stream_with_tracker(
        self,
        payload: Any,
    ) -> AsyncGenerator[str, None]:
        """Override for CoPaw versions that use _stream_with_tracker.

        In post-1.0 CoPaw the message path changed from
        _consume_one_request -> _run_process_loop to
        _consume_with_tracker -> _stream_with_tracker.
        This override mirrors the streaming card logic from
        _run_process_loop_streaming but adapted to the new async-generator
        architecture that yields SSE events.

        Falls back to super() if streaming is disabled.
        """
        if not self._is_streaming_enabled():
            async for chunk in super()._stream_with_tracker(
                payload,
            ):  # type: ignore[misc]
                yield chunk
            return

        # Build request and meta (mirror BaseChannel._stream_with_tracker)
        request = self._payload_to_request(payload)

        if isinstance(payload, dict):
            send_meta = dict(payload.get("meta") or {})
            if payload.get("session_webhook"):
                send_meta["session_webhook"] = payload["session_webhook"]
        else:
            send_meta = getattr(request, "channel_meta", None) or {}

        bot_prefix = getattr(self, "bot_prefix", None) or getattr(
            self,
            "_bot_prefix",
            "",
        )
        if bot_prefix and "bot_prefix" not in send_meta:
            send_meta = {**send_meta, "bot_prefix": bot_prefix}

        to_handle = self.get_to_handle_from_request(request)
        await self._before_consume_process(request)

        # --- Streaming card state ---
        card_id: Optional[str] = None  # None=not attempted, ""=failed
        text_acc = ""
        last_msg_id: Optional[str] = None
        last_response = None
        _updater_task: Optional[asyncio.Task] = None

        async def _card_updater() -> None:
            nonlocal card_id, text_acc
            while card_id and card_id != "":
                await asyncio.sleep(_STREAMING_UPDATE_INTERVAL_SEC)
                if not card_id or card_id == "":
                    break
                if text_acc:
                    ok = await self._card_update_text(card_id, text_acc)
                    if not ok:
                        card_id = ""
                        return

        async def _stop_updater() -> None:
            nonlocal _updater_task
            if _updater_task and not _updater_task.done():
                _updater_task.cancel()
                try:
                    await _updater_task
                except asyncio.CancelledError:
                    pass
                _updater_task = None

        async def _close_card(final_text: str) -> None:
            nonlocal card_id, text_acc
            await _stop_updater()
            if card_id and card_id != "":
                if final_text:
                    await self._card_update_text(card_id, final_text)
                await self._card_close(card_id)
            card_id = None
            text_acc = ""

        async def _send_others(parts: list) -> None:
            nonlocal last_msg_id
            try:
                mid = await self.send_content_parts(
                    to_handle,
                    parts,
                    send_meta,
                )
                if mid:
                    last_msg_id = mid
            except Exception:
                pass

        async def _create_card() -> bool:
            nonlocal card_id, last_msg_id, _updater_task
            try:
                recv = await self._get_receive_for_send(to_handle, send_meta)
                if not recv:
                    card_id = ""
                    return False
                rid_type, rid = recv
                cid = await self._card_create()
                if not cid:
                    card_id = ""
                    return False
                mid = await self._card_send(cid, rid, rid_type)
                if not mid:
                    card_id = ""
                    return False
                card_id = cid
                last_msg_id = mid
                _updater_task = asyncio.create_task(_card_updater())
                return True
            except Exception:
                logger.warning(
                    "streaming card create failed, falling back",
                    exc_info=True,
                )
                card_id = ""
                return False

        # --- Main event loop ---
        process_iterator = None
        try:
            process_iterator = self._process(request)
            async for event in process_iterator:
                # Yield SSE event
                if hasattr(event, "model_dump_json"):
                    data = event.model_dump_json()
                elif hasattr(event, "json"):
                    data = event.json()
                else:
                    data = json.dumps({"text": str(event)})
                yield f"data: {data}\n\n"

                obj = getattr(event, "object", None)
                st = getattr(event, "status", None)

                # --- response event ---
                if obj == "response":
                    last_response = event
                    await self.on_event_response(request, event)
                    continue

                # --- message Completed: finalize ---
                if obj == "message" and st == RunStatus.Completed:
                    parts = self._message_to_content_parts(event)
                    if not parts:
                        continue

                    texts = [
                        p
                        for p in parts
                        if getattr(p, "type", None) in ("text", "markdown")
                    ]
                    others = [
                        p
                        for p in parts
                        if getattr(p, "type", None) not in ("text", "markdown")
                    ]
                    new_text = "".join(getattr(t, "text", "") for t in texts)

                    if card_id == "":
                        # Streaming failed, normal send
                        await _send_others(parts)
                        continue

                    if card_id and card_id != "":
                        final = new_text or text_acc
                        await _close_card(final)
                        if others:
                            await _send_others(others)
                        continue

                    # No card yet: quick create + close
                    if new_text:
                        if await _create_card():
                            await self._card_update_text(
                                card_id,  # type: ignore[arg-type]
                                new_text,
                            )
                            await _close_card(new_text)
                            if others:
                                await _send_others(others)
                        else:
                            await _send_others(parts)
                    else:
                        if others:
                            await _send_others(others)
                    continue

                # --- InProgress streaming deltas ---
                if st == RunStatus.InProgress:
                    text = self._extract_streaming_text(
                        event,
                        is_streaming=True,
                    )
                    if not text:
                        continue
                    text_acc = text
                    if card_id is None:
                        await _create_card()
                    continue

        except asyncio.CancelledError:
            if process_iterator is not None:
                await process_iterator.aclose()
            if card_id and card_id != "":
                await self._card_close(card_id)
            raise

        except Exception:
            logger.exception("streaming _stream_with_tracker error")
            if card_id and card_id != "":
                await self._card_close(card_id)
            return

        # --- Post-processing ---
        if card_id and card_id != "":
            await _close_card(text_acc)

        err = self._get_response_error_message(last_response)
        if err:
            try:
                await self._on_consume_error(
                    request,
                    to_handle,
                    f"Error: {err}",
                )
            except Exception:
                pass
        elif last_msg_id:
            try:
                await self._add_reaction(last_msg_id, "DONE")
            except Exception:
                pass

        if self._on_reply_sent:
            try:
                args = self.get_on_reply_sent_args(request, to_handle)
                self._on_reply_sent(self.channel, *args)
            except Exception:
                pass

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Proactive send: resolve receive_id and send text as post."""
        if not self.enabled:
            return
        recv = await self._get_receive_for_send(to_handle, meta)
        if not recv:
            logger.warning(
                "feishu send: no receive_id for to_handle=%s",
                to_handle[:50] if to_handle else "",
            )
            return
        receive_id_type, receive_id = recv
        prefix = (meta or {}).get("bot_prefix", "") or self.bot_prefix or ""
        body = (prefix + text) if text else prefix
        if body:
            await self._send_text(receive_id_type, receive_id, body)

    def get_to_handle_from_request(self, request: Any) -> str:
        """Feishu sends by session_id; return feishu:sw: or feishu:open_id:
        so _route_from_handle resolves session_key and we load full receive_id.
        """
        session_id = getattr(request, "session_id", "") or ""
        user_id = getattr(request, "user_id", "") or ""
        if session_id:
            return f"feishu:sw:{session_id}"
        if user_id:
            return f"feishu:open_id:{user_id}"
        return ""

    def get_on_reply_sent_args(
        self,
        request: Any,
        to_handle: str,
    ) -> tuple:
        """Feishu callback expects (user_id, session_id)."""
        return (
            getattr(request, "user_id", "") or "",
            getattr(request, "session_id", "") or "",
        )

    async def _before_consume_process(self, request: Any) -> None:
        """Save receive_id from webhook meta for later send."""
        meta = getattr(request, "channel_meta", None) or {}
        receive_id = meta.get("feishu_receive_id")
        receive_id_type = meta.get("feishu_receive_id_type", "open_id")
        if receive_id and getattr(request, "session_id", None):
            await self._save_receive_id(
                request.session_id,
                receive_id,
                receive_id_type,
            )

    def _run_ws_forever(self) -> None:
        """Run WebSocket with automatic reconnection.

        Implements exponential backoff reconnection:
        - Initial delay: 1 second
        - Max delay: 60 seconds
        - Backoff factor: 2x

        Reconnection stops when:
        - _stop_event is set (explicit stop)
        - _closed is True (channel closed)
        """
        # Reconnection settings
        retry_delay = FEISHU_WS_INITIAL_RETRY_DELAY

        while not self._stop_event.is_set() and not self._closed:
            self._ws_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._ws_loop)
            old_ws_client_loop = None
            _ws_mod: types.ModuleType = types.ModuleType("_ws_mod_placeholder")
            _orig_select = None
            # Hold the lock until _connect() finishes so concurrent instances
            # don't overwrite each other's ws_client.loop.
            _WS_START_LOCK.acquire()  # pylint: disable=consider-using-with
            lock_released = False
            connection_started = False
            try:
                try:
                    import lark_oapi.ws.client as _lark_ws_mod

                    _ws_mod = _lark_ws_mod
                    old_ws_client_loop = getattr(_ws_mod, "loop", None)
                    _ws_mod.loop = self._ws_loop
                    # Patch _select to release lock after _connect().
                    _orig_select = _ws_mod._select
                except ImportError:
                    pass

                async def _patched_select() -> None:
                    nonlocal lock_released, connection_started
                    if not lock_released:
                        _WS_START_LOCK.release()
                        lock_released = True
                        connection_started = True
                    if _orig_select is not None:
                        await _orig_select()

                async def _monitor_connection_health() -> None:
                    """Force reconnect if SDK's internal reconnect gives up."""
                    while not self._stop_event.is_set() and not self._closed:
                        await asyncio.sleep(30)
                        if self._stop_event.is_set() or self._closed:
                            break
                        if not connection_started:
                            continue
                        ws = self._ws_client
                        if (
                            ws is not None
                            and getattr(ws, "_conn", True) is None
                        ):
                            logger.warning(
                                "feishu WebSocket conn lost, "
                                "forcing reconnect...",
                            )
                            if self._ws_loop and not self._ws_loop.is_closed():
                                self._ws_loop.stop()
                            break

                _ws_mod._select = _patched_select
                try:
                    if self._ws_client and not self._stop_event.is_set():
                        self._ws_loop.create_task(
                            _monitor_connection_health(),
                        )
                        logger.info(
                            "feishu WebSocket connecting (long connection)...",
                        )
                        self._ws_client.start()
                        # If start() returns normally, connection was closed
                        # by server; reset retry delay and reconnect
                        if not self._stop_event.is_set() and not self._closed:
                            logger.info(
                                "feishu WebSocket disconnected, "
                                "reconnecting immediately...",
                            )
                except RuntimeError as e:
                    # Normal shutdown: loop.stop() causes run_until_complete
                    # to raise "Event loop stopped before Future completed."
                    if "Event loop stopped" in str(e):
                        logger.debug(
                            "feishu WebSocket stopped normally: %s",
                            e,
                        )
                        # Check if this was an intentional stop
                        if self._stop_event.is_set() or self._closed:
                            break
                        # Otherwise, treat as disconnection and reconnect
                        logger.info(
                            "feishu WebSocket event loop stopped, "
                            "will attempt to reconnect",
                        )
                    else:
                        logger.exception(
                            "feishu WebSocket thread failed, "
                            "will attempt to reconnect",
                        )
                except Exception:
                    if self._stop_event.is_set() or self._closed:
                        logger.debug(
                            "feishu WebSocket stopped during reconnect",
                        )
                    else:
                        logger.exception(
                            "feishu WebSocket thread failed, "
                            "will attempt to reconnect",
                        )
            finally:
                # Ensure lock is released (covers KeyboardInterrupt).
                if not lock_released:
                    try:
                        _WS_START_LOCK.release()
                    except RuntimeError:
                        pass
                try:
                    _ws_mod._select = _orig_select
                except Exception:
                    pass
                if self._ws_loop and not self._ws_loop.is_closed():
                    try:
                        if self._ws_client and hasattr(
                            self._ws_client,
                            "_disconnect",
                        ):
                            try:
                                self._ws_loop.run_until_complete(
                                    self._ws_client._disconnect(),
                                )
                                logger.debug(
                                    "feishu WebSocket disconnected gracefully",
                                )
                            except Exception:
                                logger.debug(
                                    "feishu ws disconnect failed",
                                    exc_info=True,
                                )
                        pending = [
                            t
                            for t in asyncio.all_tasks(self._ws_loop)
                            if not t.done()
                        ]
                        for task in pending:
                            task.cancel()
                        if pending:
                            self._ws_loop.run_until_complete(
                                asyncio.gather(
                                    *pending,
                                    return_exceptions=True,
                                ),
                            )
                            logger.debug(
                                f"feishu cancelled {len(pending)} tasks",
                            )
                    except Exception:
                        logger.debug("feishu ws cleanup failed", exc_info=True)
                try:
                    if (
                        _ws_mod
                        and getattr(_ws_mod, "loop", None) is self._ws_loop
                    ):
                        _ws_mod.loop = old_ws_client_loop
                except Exception:
                    pass
                try:
                    if self._ws_loop and not self._ws_loop.is_closed():
                        self._ws_loop.close()
                except Exception:
                    logger.debug("feishu ws loop close failed", exc_info=True)
                self._ws_loop = None

            # Wait before reconnecting (if not stopped)
            if not self._stop_event.is_set() and not self._closed:
                if connection_started:
                    # Connection was established, reset retry delay
                    retry_delay = FEISHU_WS_INITIAL_RETRY_DELAY
                else:
                    # Connection failed to establish, use exponential backoff
                    logger.info(
                        "feishu WebSocket reconnecting in %.1fs...",
                        retry_delay,
                    )
                    # Use wait with timeout to allow early exit on stop
                    self._stop_event.wait(timeout=retry_delay)
                    # Increase delay for next attempt
                    retry_delay = min(
                        retry_delay * FEISHU_WS_BACKOFF_FACTOR,
                        FEISHU_WS_MAX_RETRY_DELAY,
                    )

        # Final cleanup signal
        self._stop_event.set()

    async def start(self) -> None:
        if not self.enabled:
            logger.debug("feishu channel disabled")
            return
        self._closed = False
        self._load_receive_id_store_from_disk()
        if lark is None:
            raise RuntimeError(
                "Feishu channel enabled but lark-oapi is not installed. "
                "Run: pip install lark-oapi",
            )
        if not self.app_id or not self.app_secret:
            raise RuntimeError(
                "FEISHU_APP_ID and FEISHU_APP_SECRET are required when "
                "feishu channel is enabled.",
            )
        self._loop = asyncio.get_running_loop()
        self._http_client = httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": "CoPaw/1.0"},
        )
        sdk_domain = (
            lark.LARK_DOMAIN if self.domain == "lark" else lark.FEISHU_DOMAIN
        )
        self._client = (
            lark.Client.builder()
            .app_id(self.app_id)
            .app_secret(self.app_secret)
            .domain(sdk_domain)
            .log_level(lark.LogLevel.INFO)
            .build()
        )
        event_handler = (
            lark.EventDispatcherHandler.builder(
                self.encrypt_key,
                self.verification_token,
            )
            .register_p2_im_message_receive_v1(self._on_message_sync)
            .build()
        )
        self._ws_client = lark.ws.Client(
            self.app_id,
            self.app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.INFO,
            domain=(
                "https://open.larksuite.com"
                if self.domain == "lark"
                else "https://open.feishu.cn"
            ),
        )
        self._stop_event.clear()
        self._ws_thread = threading.Thread(
            target=self._run_ws_forever,
            daemon=True,
        )
        self._ws_thread.start()
        try:
            self._bot_open_id = await self._fetch_bot_open_id()
            logger.info(
                "feishu: bot open_id=%s",
                self._bot_open_id[:12] if self._bot_open_id else "?",
            )
        except Exception:
            logger.warning(
                "feishu: failed to fetch bot open_id (non-fatal)",
            )
        logger.info("feishu channel started (app_id=%s)", self.app_id[:12])

    async def stop(self) -> None:
        if not self.enabled:
            return

        self._closed = True
        self._stop_event.set()

        # Stop the WebSocket event loop - cleanup happens in _run_ws_forever
        # finally block (disconnect, cancel tasks, close loop)
        if self._ws_loop and not self._ws_loop.is_closed():
            try:
                self._ws_loop.call_soon_threadsafe(self._ws_loop.stop)
            except Exception:
                logger.debug("feishu ws_loop.stop failed", exc_info=True)

        if self._ws_thread:
            self._ws_thread.join(timeout=5)
            if self._ws_thread.is_alive():
                logger.warning("feishu ws thread did not stop within timeout")

        if self._http_client:
            try:
                await self._http_client.aclose()
            except Exception:
                logger.debug("feishu http_client close failed", exc_info=True)

        self._client = None
        self._ws_client = None
        self._ws_thread = None
        self._ws_loop = None
        self._http_client = None
        logger.info("feishu channel stopped")
