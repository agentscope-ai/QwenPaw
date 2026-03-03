# -*- coding: utf-8 -*-
# pylint: disable=too-many-statements,too-many-branches
# pylint: disable=too-many-return-statements,unused-argument
"""Feishu (Lark) Channel.

Uses lark-oapi (https://github.com/larksuite/oapi-sdk-python) WebSocket
long connection to receive events (no public IP). Sends via Open API
(tenant_access_token). Supports text, image, file; group chat context:
chat_id and message_id are put in message metadata for downstream
deduplication.
"""

from __future__ import annotations

import base64
import asyncio
import json
import logging
import mimetypes
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import aiohttp

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateImageRequest,
    CreateImageRequestBody,
    CreateMessageRequest,
    CreateMessageRequestBody,
    CreateMessageReactionRequest,
    CreateMessageReactionRequestBody,
    Emoji,
    P2ImMessageReceiveV1,
)
from agentscope_runtime.engine.schemas.agent_schemas import (
    # AudioContent,
    FileContent,
    ImageContent,
    TextContent,
)

from ..utils import file_url_to_local_path
from ....config.config import FeishuConfig as FeishuChannelConfig
from ....config.utils import get_config_path
from ..base import (
    BaseChannel,
    ContentType,
    OnReplySent,
    OutgoingContentPart,
    ProcessHandler,
)

from .constants import (
    FEISHU_AVAILABLE,
    FEISHU_FILE_MAX_BYTES,
    FEISHU_NICKNAME_CACHE_MAX,
    FEISHU_PROCESSED_IDS_MAX,
    FEISHU_TOKEN_REFRESH_BEFORE_SECONDS,
    FEISHU_USER_NAME_FETCH_TIMEOUT,
)
from .utils import (
    extract_json_key,
    normalize_feishu_md,
    sender_display_string,
    short_session_id_from_full_id,
)

if TYPE_CHECKING:
    from agentscope_runtime.engine.schemas.agent_schemas import AgentRequest

logger = logging.getLogger(__name__)


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
        media_dir: str = "~/.copaw/media",
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
    ):
        super().__init__(
            process,
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
        )
        self.enabled = enabled
        self.app_id = app_id
        self.app_secret = app_secret
        self.bot_prefix = bot_prefix
        self.encrypt_key = encrypt_key or ""
        self.verification_token = verification_token or ""
        self._media_dir = Path(media_dir).expanduser()

        self._client: Any = None
        self._ws_client: Any = None
        self._ws_thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_event = threading.Event()

        self._tenant_access_token: Optional[str] = None
        self._tenant_access_token_expire_at: float = 0.0
        self._token_lock = asyncio.Lock()
        self._http: Optional[aiohttp.ClientSession] = None

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
        import os

        return cls(
            process=process,
            enabled=os.getenv("FEISHU_CHANNEL_ENABLED", "0") == "1",
            app_id=os.getenv("FEISHU_APP_ID", ""),
            app_secret=os.getenv("FEISHU_APP_SECRET", ""),
            bot_prefix=os.getenv("FEISHU_BOT_PREFIX", "[BOT] "),
            encrypt_key=os.getenv("FEISHU_ENCRYPT_KEY", ""),
            verification_token=os.getenv("FEISHU_VERIFICATION_TOKEN", ""),
            media_dir=os.getenv("FEISHU_MEDIA_DIR", "~/.copaw/media"),
            on_reply_sent=on_reply_sent,
        )

    @classmethod
    def from_config(
        cls,
        process: ProcessHandler,
        config: FeishuChannelConfig,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
    ) -> "FeishuChannel":
        return cls(
            process=process,
            enabled=config.enabled,
            app_id=config.app_id or "",
            app_secret=config.app_secret or "",
            bot_prefix=config.bot_prefix or "[BOT] ",
            encrypt_key=config.encrypt_key or "",
            verification_token=config.verification_token or "",
            media_dir=config.media_dir or "~/.copaw/media",
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
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
            return short_session_id_from_full_id(chat_id)
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

    async def _get_tenant_access_token(self) -> str:
        """Fetch and cache tenant_access_token."""
        now = time.time()
        if (
            self._tenant_access_token
            and now
            < self._tenant_access_token_expire_at
            - FEISHU_TOKEN_REFRESH_BEFORE_SECONDS
        ):
            return self._tenant_access_token

        async with self._token_lock:
            now = time.time()
            if (
                self._tenant_access_token
                and now
                < self._tenant_access_token_expire_at
                - FEISHU_TOKEN_REFRESH_BEFORE_SECONDS
            ):
                return self._tenant_access_token

            url = (
                "https://open.feishu.cn/open-apis/auth/v3/"
                "tenant_access_token/internal"
            )
            payload = {
                "app_id": self.app_id,
                "app_secret": self.app_secret,
            }
            async with self._http.post(url, json=payload) as resp:
                data = await resp.json(content_type=None)
                if resp.status >= 400:
                    raise RuntimeError(
                        f"Feishu token failed status={resp.status} "
                        f"body={data}",
                    )
            if data.get("code") != 0:
                raise RuntimeError(
                    f"Feishu token error code={data.get('code')} msg"
                    f"={data.get('msg')}",
                )
            token = data.get("tenant_access_token")
            if not token:
                raise RuntimeError("Feishu token missing in response")
            expire = int(data.get("expire", 3600))
            self._tenant_access_token = token
            self._tenant_access_token_expire_at = now + expire
            return token

    async def _get_user_name_by_open_id(self, open_id: str) -> Optional[str]:
        """Fetch user name (nickname) from Feishu Contact API by open_id.

        Uses Contact v3 GET /open-apis/contact/v3/users/{user_id} with
        user_id_type=open_id (see Feishu user identity doc:
        https://open.feishu.cn/document/platform-overveiw/basic-concepts/
        user-identity-introduction/open-id).
        Result is cached. Returns None on failure or missing permission.
        """
        if not open_id or open_id.startswith("unknown_"):
            return None
        async with self._nickname_cache_lock:
            if open_id in self._nickname_cache:
                return self._nickname_cache[open_id]
        url = (
            "https://open.feishu.cn/open-apis/contact/v3/users/"
            f"{open_id}?user_id_type=open_id"
        )
        try:
            token = await self._get_tenant_access_token()
            timeout = aiohttp.ClientTimeout(
                total=FEISHU_USER_NAME_FETCH_TIMEOUT,
            )
            async with self._http.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=timeout,
            ) as resp:
                body = await resp.text()
                if resp.status >= 400:
                    logger.info(
                        "feishu get user name failed: open_id=%s status=%s",
                        open_id[:20],
                        resp.status,
                    )
                    return None
                try:
                    data = json.loads(body) if body else {}
                except json.JSONDecodeError:
                    data = {}
            if data.get("code") != 0:
                logger.info(
                    "feishu get user name api error: open_id=%s code=%s "
                    "msg=%s",
                    open_id[:20],
                    data.get("code"),
                    data.get("msg", ""),
                )
                return None
            # Response per Feishu doc: GET contact/v3/users/{user_id}
            # https://open.feishu.cn/document/server-docs/contact-v3/user/get
            # Body: { "code": 0, "data": { "user": { "name": ... } } }
            # "name" can be string or i18n object { "zh_cn": "中文", "en": "en" }
            user = data.get("data") or {}
            inner = user.get("user") or {}
            name = None
            for obj in (inner, user):
                if not isinstance(obj, dict):
                    continue
                raw_name = (
                    obj.get("name")
                    or obj.get("real_name")
                    or obj.get(
                        "nickname",
                    )
                    or obj.get("name_cn")
                    or obj.get("name_en")
                    or obj.get(
                        "en_name",
                    )
                )
                if isinstance(raw_name, str) and raw_name.strip():
                    name = raw_name.strip()
                    break
                if isinstance(raw_name, dict):
                    name = (
                        raw_name.get("zh_cn")
                        or raw_name.get("zh_CN")
                        or raw_name.get("zh-Cn")
                        or raw_name.get("zh-CN")
                        or raw_name.get("en")
                        or (list(raw_name.values()) or [None])[0]
                    )
                    if name and isinstance(name, str):
                        name = name.strip()
                        break
                    first_val = (list(raw_name.values()) or [None])[0]
                    if isinstance(first_val, str) and first_val.strip():
                        name = first_val.strip()
                        break
            if not name:
                logger.info(
                    f"feishu get user name: no name in response (open_id"
                    f"={(open_id or '')[:20]}). inner_keys"
                    f"={list(inner.keys()) if inner else []} - app likely "
                    f"missing contact name permission. Add scope e.g. "
                    f"contact:user.base:readonly in Feishu console.",
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
        if (
            not FEISHU_AVAILABLE
            or not data
            or not getattr(data, "event", None)
        ):
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

            await self._add_reaction(message_id, "Typing")

            content_parts: List[Any] = []
            text_parts: List[str] = []

            if msg_type == "text":
                text = extract_json_key(content_raw, "text")
                if text:
                    text_parts.append(text)
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
                if file_key:
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
                        text_parts.append("[file: download failed]")
                else:
                    text_parts.append("[file: missing key]")
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
                        # TODO: change to audio block when as support opus
                        content_parts.append(
                            FileContent(
                                type=ContentType.FILE,
                                file_url=url_or_path,
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

            meta: Dict[str, Any] = {
                "feishu_message_id": message_id,
                "feishu_chat_id": chat_id,
                "feishu_chat_type": chat_type,
                "feishu_sender_id": sender_id,
            }
            receive_id = chat_id if chat_type == "group" else sender_id
            receive_id_type = "chat_id" if chat_type == "group" else "open_id"
            meta["feishu_receive_id"] = receive_id
            meta["feishu_receive_id_type"] = receive_id_type

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
        if not FEISHU_AVAILABLE or not self._client or not Emoji:
            return
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                self._add_reaction_sync,
                message_id,
                emoji_type,
            )
        except Exception:
            logger.debug(
                "feishu add_reaction failed message_id=%s",
                message_id[:16],
            )

    def _add_reaction_sync(self, message_id: str, emoji_type: str) -> None:
        try:
            req = (
                CreateMessageReactionRequest.builder()
                .message_id(
                    message_id,
                )
                .request_body(
                    CreateMessageReactionRequestBody.builder()
                    .reaction_type(
                        Emoji.builder().emoji_type(emoji_type).build(),
                    )
                    .build(),
                )
                .build()
            )
            resp = self._client.im.v1.message_reaction.create(req)
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
        """Download image to media_dir; return local path or None."""
        token = await self._get_tenant_access_token()
        url = (
            f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}"
            f"/resources/{image_key}"
        )
        headers = {"Authorization": f"Bearer {token}"}
        try:
            async with self._http.get(
                url,
                params={"type": "image"},
                headers=headers,
            ) as resp:
                if resp.status >= 400:
                    logger.warning(
                        "feishu image download failed status=%s",
                        resp.status,
                    )
                    return None
                data = await resp.read()
                content_type = (
                    resp.headers.get("Content-Type", "").split(";")[0].strip()
                )
            ext = (mimetypes.guess_extension(content_type) or ".jpg").lstrip(
                ".",
            )
            safe_key = (
                "".join(c for c in image_key if c.isalnum() or c in "-_.")
                or "img"
            )
            self._media_dir.mkdir(parents=True, exist_ok=True)
            path = self._media_dir / f"{message_id}_{safe_key}.{ext}"
            path.write_bytes(data)
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
        """Download file to media_dir; return local path or None.
        Uses message resources API (user-sent files); /im/v1/files only
        allows app-sent files.
        """
        token = await self._get_tenant_access_token()
        url = (
            f"https://open.feishu.cn/open-apis/im/v1/messages/"
            f"{message_id}/resources/{file_key}?type=file"
        )
        headers = {"Authorization": f"Bearer {token}"}
        try:
            async with self._http.get(url, headers=headers) as resp:
                if resp.status >= 400:
                    logger.warning(
                        "feishu file download failed status=%s",
                        resp.status,
                    )
                    return None
                data = await resp.read()
                disposition = resp.headers.get(
                    "Content-Disposition",
                    "",
                )
                content_type = (
                    resp.headers.get("Content-Type", "").split(";")[0].strip()
                )
            filename = filename_hint
            if "filename=" in disposition:
                part = (
                    disposition.split("filename=", 1)[-1].strip().strip("'\"")
                )
                if part:
                    part = Path(part).name
                    if part.strip():
                        filename = part
            # Prevent path traversal: keep only the base name.
            filename = Path(filename).name
            if not filename.strip():
                filename = filename_hint
            # If hint has an extension but chosen filename has none or
            # .bin/.file, force the hint extension so e.g. audio.opus is kept.
            hint_ext = Path(filename_hint).suffix
            if hint_ext and Path(filename).suffix in ("", ".bin", ".file"):
                filename = (Path(filename).stem or "file") + hint_ext
            safe_key = (
                "".join(c for c in file_key if c.isalnum() or c in "-_.")
                or "file"
            )
            self._media_dir.mkdir(parents=True, exist_ok=True)
            path = self._media_dir / f"{message_id}_{safe_key}_{filename}"
            path.write_bytes(data)
            if path.suffix in (".bin", ".file") and content_type:
                ext = mimetypes.guess_extension(content_type)
                if ext:
                    new_path = path.with_suffix(ext)
                    path.rename(new_path)
                    path = new_path
            return str(path)
        except Exception:
            logger.exception("feishu _download_file_resource failed")
            return None

    def _receive_id_store_path(self) -> Path:
        """
        Path to persist receive_id mapping (for cron to resolve after restart).
        """
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

    def _upload_image_sync(self, data: bytes, filename: str) -> Optional[str]:
        """Upload image via lark client; return image_key."""
        if not FEISHU_AVAILABLE or not self._client:
            return None
        logger.info(
            "feishu _upload_image_sync: size=%s filename=%s",
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
            resp = self._client.im.v1.image.create(req)
            if not resp.success():
                logger.warning(
                    "feishu image upload failed code=%s msg=%s",
                    getattr(resp, "code", ""),
                    getattr(resp, "msg", ""),
                )
                return None
            key = getattr(resp.data, "image_key", None) if resp.data else None
            logger.info(
                "feishu _upload_image_sync ok: image_key=%s",
                key[:24] if key else "None",
            )
            return key
        except Exception:
            logger.exception("feishu _upload_image_sync failed")
            return None

    async def _upload_file(self, path_or_url: str) -> Optional[str]:
        """Upload file to Feishu; return file_key. path_or_url can be path."""
        token = await self._get_tenant_access_token()
        path = Path(path_or_url)
        if not path.exists():
            if path_or_url.startswith(("http://", "https://")):
                data = await self._fetch_bytes_from_url(path_or_url)
                if not data:
                    return None
                path = self._media_dir / "upload_temp"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            else:
                return None
        size = path.stat().st_size
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
            "mp4",
        ):
            file_type = "doc" if ext == "docx" else ext
            file_type = "xls" if ext == "xlsx" else file_type
            file_type = "ppt" if ext == "pptx" else file_type
        mime = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        url = "https://open.feishu.cn/open-apis/im/v1/files"
        form = aiohttp.FormData()
        form.add_field("file_type", file_type)
        form.add_field("file_name", path.name)
        form.add_field(
            "file",
            path.read_bytes(),
            filename=path.name,
            content_type=mime,
        )
        try:
            async with self._http.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                data=form,
            ) as resp:
                data = await resp.json(content_type=None)
                if resp.status >= 400:
                    logger.warning(
                        "feishu file upload failed status=%s body=%s",
                        resp.status,
                        data,
                    )
                    return None
                if data.get("code") != 0:
                    logger.info(
                        "feishu _upload_file api code=%s msg=%s",
                        data.get("code"),
                        data.get("msg"),
                    )
                    return None
                fk = (data.get("data") or {}).get("file_key")
                logger.info(
                    "feishu _upload_file ok: file_key=%s",
                    fk[:24] if fk else "None",
                )
                return fk
        except Exception:
            logger.exception("feishu _upload_file failed")
            return None

    async def _fetch_bytes_from_url(self, url: str) -> Optional[bytes]:
        """Download binary from URL. Supports http(s):// and file://."""
        try:
            path = file_url_to_local_path(url)
            if path is not None:
                return await asyncio.to_thread(Path(path).read_bytes)
            if url.strip().lower().startswith("file:"):
                return None
            async with self._http.get(url) as resp:
                if resp.status >= 400:
                    return None
                return await resp.read()
        except Exception:
            logger.exception("feishu _fetch_bytes_from_url failed")
            return None

    def _send_message_sync(
        self,
        receive_id_type: str,
        receive_id: str,
        msg_type: str,
        content: str,
    ) -> bool:
        """Send one message (post, image, or file) via lark client."""
        if not FEISHU_AVAILABLE or not self._client:
            return False
        logger.info(
            "feishu _send_message_sync: msg_type=%s receive_id_type=%s "
            "content_len=%s",
            msg_type,
            receive_id_type,
            len(content),
        )
        try:
            req = (
                CreateMessageRequest.builder()
                .receive_id_type(
                    receive_id_type,
                )
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(receive_id)
                    .msg_type(msg_type)
                    .content(content)
                    .build(),
                )
                .build()
            )
            resp = self._client.im.v1.message.create(req)
            if not resp.success():
                logger.warning(
                    "feishu send failed code=%s msg=%s",
                    getattr(resp, "code", ""),
                    getattr(resp, "msg", ""),
                )
                return False
            logger.info(
                "feishu _send_message_sync ok: msg_type=%s",
                msg_type,
            )
            return True
        except Exception:
            logger.exception("feishu _send_message_sync failed")
            return False

    async def _send_text(
        self,
        receive_id_type: str,
        receive_id: str,
        body: str,
    ) -> bool:
        """Send text as post (md). Body already has bot_prefix if needed."""
        post = self._build_post_content(body, [])
        content = json.dumps(post, ensure_ascii=False)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._send_message_sync(
                receive_id_type,
                receive_id,
                "post",
                content,
            ),
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
    ) -> bool:
        """Upload image and send as msg_type=image (image_key) per API."""
        logger.info(
            "feishu _send_image: part type=%s",
            getattr(part, "type", None),
        )
        data, filename = await self._part_to_image_bytes(part)
        if not data:
            logger.info(
                "feishu _send_image: no image data, skip (url/base64/path)",
            )
            return False
        loop = asyncio.get_running_loop()
        image_key = await loop.run_in_executor(
            None,
            lambda: self._upload_image_sync(data, filename),
        )
        if not image_key:
            logger.info(
                "feishu _send_image: upload failed, no image_key",
            )
            return False
        logger.info(
            "feishu _send_image: upload ok image_key=%s",
            image_key[:24] if image_key else "",
        )
        content = json.dumps({"image_key": image_key}, ensure_ascii=False)
        return await loop.run_in_executor(
            None,
            lambda: self._send_message_sync(
                receive_id_type,
                receive_id,
                "image",
                content,
            ),
        )

    async def _part_to_file_path_or_url(
        self,
        part: OutgoingContentPart,
    ) -> Optional[str]:
        """Resolve part to local path or URL for file upload."""
        url = (
            getattr(part, "file_url", None)
            or getattr(part, "image_url", None)
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
    ) -> bool:
        """Upload file and send file message (msg_type=file, file_key)."""
        logger.info(
            "feishu _send_file: part type=%s",
            getattr(part, "type", None),
        )
        path_or_url = await self._part_to_file_path_or_url(part)
        if not path_or_url:
            logger.info(
                "feishu _send_file: no path/url/base64, skip",
            )
            return False
        file_key = await self._upload_file(path_or_url)
        if not file_key:
            logger.info(
                "feishu _send_file: upload failed, no file_key",
            )
            return False
        logger.info(
            "feishu _send_file: upload ok file_key=%s",
            file_key[:24] if file_key else "",
        )
        content = json.dumps({"file_key": file_key}, ensure_ascii=False)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._send_message_sync(
                receive_id_type,
                receive_id,
                "file",
                content,
            ),
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
                            if v[0] and str(v[0]).endswith(suffix):
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

    async def send_content_parts(
        self,
        to_handle: str,
        parts: List[OutgoingContentPart],
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send text as post (md), then images, then files."""
        if not self.enabled or not FEISHU_AVAILABLE:
            return
        recv = await self._get_receive_for_send(to_handle, meta)
        if not recv:
            logger.warning(
                "feishu send_content_parts: no receive_id for to_handle=%s "
                "(cron will not send; ensure user chatted once or set "
                "dispatch.meta.feishu_receive_id)",
                to_handle[:50] if to_handle else "",
            )
            return
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
            t = getattr(p, "type", None)
            if t == ContentType.TEXT and getattr(p, "text", None):
                text_parts.append(p.text or "")
            elif t == ContentType.REFUSAL and getattr(p, "refusal", None):
                text_parts.append(p.refusal or "")
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
            body = prefix + body
        if body:
            await self._send_text(receive_id_type, receive_id, body)
        for part in media_parts:
            pt = getattr(part, "type", None)
            if pt == ContentType.IMAGE:
                ok = await self._send_image(
                    receive_id_type,
                    receive_id,
                    part,
                )
                logger.info(
                    "feishu send_content_parts: image sent ok=%s",
                    ok,
                )
            elif pt in (
                ContentType.FILE,
                ContentType.VIDEO,
                ContentType.AUDIO,
            ):
                ok = await self._send_file(
                    receive_id_type,
                    receive_id,
                    part,
                )
                logger.info(
                    "feishu send_content_parts: file sent ok=%s type=%s",
                    ok,
                    pt,
                )

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Proactive send: resolve receive_id and send text as post."""
        if not self.enabled or not FEISHU_AVAILABLE:
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
        # lark-oapi ws.Client uses a module-level event loop; when start() runs
        # in this thread it must use this thread's loop, not the main thread's.
        ws_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(ws_loop)
        try:
            import lark_oapi.ws.client as ws_client

            ws_client.loop = ws_loop
        except ImportError:
            pass
        try:
            if self._ws_client:
                logger.info("feishu WebSocket connecting (long connection)...")
                self._ws_client.start()
        except Exception:
            logger.exception("feishu WebSocket thread failed")
        finally:
            self._stop_event.set()

    async def start(self) -> None:
        if not self.enabled:
            logger.debug("feishu channel disabled")
            return
        self._load_receive_id_store_from_disk()
        if not FEISHU_AVAILABLE:
            raise RuntimeError(
                "Feishu channel enabled but lark-oapi not installed. "
                "Run: pip install lark-oapi",
            )
        if not self.app_id or not self.app_secret:
            raise RuntimeError(
                "FEISHU_APP_ID and FEISHU_APP_SECRET are required when "
                "feishu channel is enabled.",
            )
        self._loop = asyncio.get_running_loop()
        self._client = (
            lark.Client.builder()
            .app_id(self.app_id)
            .app_secret(
                self.app_secret,
            )
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
        )
        self._stop_event.clear()
        self._ws_thread = threading.Thread(
            target=self._run_ws_forever,
            daemon=True,
        )
        self._ws_thread.start()
        if self._http is None:
            self._http = aiohttp.ClientSession()
        logger.info("feishu channel started (app_id=%s)", self.app_id[:12])

    async def stop(self) -> None:
        if not self.enabled:
            return
        self._stop_event.set()
        if self._ws_client:
            try:
                self._ws_client.stop()
            except Exception:
                pass
        if self._ws_thread:
            self._ws_thread.join(timeout=5)
        if self._http is not None:
            await self._http.close()
            self._http = None
        self._client = None
        self._ws_client = None
        logger.info("feishu channel stopped")
