# -*- coding: utf-8 -*-
# pylint: disable=too-many-statements,too-many-branches
# pylint: disable=too-many-return-statements,too-many-instance-attributes
"""WeChat (iLink Bot) Channel.

Uses the official WeChat iLink Bot HTTP API to receive and send messages.
Incoming messages are fetched via long-polling (getupdates); replies are sent
via sendmessage. Supports text, image, voice (ASR text), and file messages.

Authentication:
  - If bot_token is configured, it is used directly.
  - If bot_token is absent, a QR code login is triggered on start(); the
    resulting token is persisted to bot_token_file for future runs.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import sys
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import base64 as _b64

from agentscope_runtime.engine.schemas.agent_schemas import (
    AgentRequest,
    FileContent,
    ImageContent,
    TextContent,
    VideoContent,
)

from ....exceptions import ChannelError
from ....constant import DEFAULT_MEDIA_DIR, WORKING_DIR
from ..base import (
    BaseChannel,
    ContentType,
    OnReplySent,
    OutgoingContentPart,
    ProcessHandler,
)
from ..utils import split_text
from .client import ILinkClient, _DEFAULT_BASE_URL

logger = logging.getLogger(__name__)

# Max dedup set size
_WEIXIN_PROCESSED_IDS_MAX = 2000

# Default token file path
_DEFAULT_TOKEN_FILE = WORKING_DIR / "weixin_bot_token"


class WeixinChannel(BaseChannel):
    """WeChat iLink Bot channel: long-poll receive, HTTP send.

    Session IDs:
        - Private chat:  weixin:<from_user_id>
        - Group chat:    weixin:group:<group_id>
    """

    channel = "wechat"

    def __init__(
        self,
        process: ProcessHandler,
        enabled: bool,
        bot_token: str = "",
        bot_token_file: str = "",
        base_url: str = "",
        bot_prefix: str = "",
        media_dir: str = "",
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
        dm_policy: str = "open",
        group_policy: str = "open",
        allow_from: Optional[List[str]] = None,
        deny_message: str = "",
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
        self.bot_token = bot_token
        self.bot_prefix = bot_prefix
        self._base_url = base_url or _DEFAULT_BASE_URL
        self._bot_token_file = (
            Path(bot_token_file).expanduser()
            if bot_token_file
            else _DEFAULT_TOKEN_FILE
        )
        self._context_tokens_file = (
            self._bot_token_file.parent / "weixin_context_tokens.json"
        )
        self._media_dir = (
            Path(media_dir).expanduser() if media_dir else DEFAULT_MEDIA_DIR
        )

        self._client: Optional[ILinkClient] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._poll_loop: Optional[asyncio.AbstractEventLoop] = None
        self._poll_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Cursor for long-polling (get_updates_buf)
        self._cursor: str = ""

        # Message dedup (context_token or derived id)
        self._processed_ids: OrderedDict[str, None] = OrderedDict()
        self._processed_ids_lock = threading.Lock()

        # Cache last context_token per user for proactive sends
        self._user_context_tokens: Dict[str, str] = {}

        # Cache typing tickets per user (24h TTL)
        self._typing_tickets: Dict[
            str,
            Tuple[str, float],
        ] = {}  # user_id -> (ticket, expiry_time)
        self._typing_lock = threading.Lock()
        # Store stop functions for active typing indicators
        self._typing_stop_funcs: Dict[
            str,
            Callable[[], None],
        ] = {}  # user_id -> stop function
        self._typing_stop_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------

    @classmethod
    def from_env(
        cls,
        process: ProcessHandler,
        on_reply_sent: OnReplySent = None,
    ) -> "WeixinChannel":
        allow_from_env = os.getenv("WEIXIN_ALLOW_FROM", "")
        allow_from = (
            [s.strip() for s in allow_from_env.split(",") if s.strip()]
            if allow_from_env
            else []
        )
        return cls(
            process=process,
            enabled=os.getenv("WEIXIN_CHANNEL_ENABLED", "0") == "1",
            bot_token=os.getenv("WEIXIN_BOT_TOKEN", ""),
            bot_token_file=os.getenv("WEIXIN_BOT_TOKEN_FILE", ""),
            base_url=os.getenv("WEIXIN_BASE_URL", ""),
            bot_prefix=os.getenv("WEIXIN_BOT_PREFIX", ""),
            media_dir=os.getenv("WEIXIN_MEDIA_DIR", ""),
            on_reply_sent=on_reply_sent,
            dm_policy=os.getenv("WEIXIN_DM_POLICY", "open"),
            group_policy=os.getenv("WEIXIN_GROUP_POLICY", "open"),
            allow_from=allow_from,
            deny_message=os.getenv("WEIXIN_DENY_MESSAGE", ""),
        )

    @classmethod
    def from_config(
        cls,
        process: ProcessHandler,
        config: Any,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
    ) -> "WeixinChannel":
        return cls(
            process=process,
            enabled=getattr(config, "enabled", False),
            bot_token=getattr(config, "bot_token", "") or "",
            bot_token_file=getattr(config, "bot_token_file", "") or "",
            base_url=getattr(config, "base_url", "") or "",
            bot_prefix=getattr(config, "bot_prefix", "") or "",
            media_dir=getattr(config, "media_dir", None) or "",
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            filter_thinking=filter_thinking,
            dm_policy=getattr(config, "dm_policy", "open") or "open",
            group_policy=getattr(config, "group_policy", "open") or "open",
            allow_from=getattr(config, "allow_from", []) or [],
            deny_message=getattr(config, "deny_message", "") or "",
        )

    # ------------------------------------------------------------------
    # Session helpers
    # ------------------------------------------------------------------

    def resolve_session_id(
        self,
        sender_id: str,
        channel_meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        meta = channel_meta or {}
        group_id = (meta.get("weixin_group_id") or "").strip()
        if group_id:
            return f"weixin:group:{group_id}"
        return f"weixin:{sender_id}" if sender_id else "weixin:unknown"

    @staticmethod
    def _parse_user_id_from_handle(to_handle: str) -> str:
        h = (to_handle or "").strip()
        if h.startswith("weixin:group:"):
            return h[len("weixin:group:") :]
        if h.startswith("weixin:"):
            return h[len("weixin:") :]
        return h

    def to_handle_from_target(self, *, user_id: str, session_id: str) -> str:
        return session_id or f"weixin:{user_id}"

    def get_to_handle_from_request(self, request: Any) -> str:
        session_id = getattr(request, "session_id", "") or ""
        user_id = getattr(request, "user_id", "") or ""
        return session_id or f"weixin:{user_id}"

    def get_on_reply_sent_args(self, request: Any, to_handle: str) -> tuple:
        return (
            getattr(request, "user_id", "") or "",
            getattr(request, "session_id", "") or "",
        )

    def build_agent_request_from_native(
        self,
        native_payload: Any,
    ) -> "AgentRequest":
        payload = native_payload if isinstance(native_payload, dict) else {}
        channel_id = payload.get("channel_id") or self.channel
        sender_id = payload.get("sender_id") or ""
        content_parts = payload.get("content_parts") or []
        meta = payload.get("meta") or {}
        session_id = payload.get("session_id") or self.resolve_session_id(
            sender_id,
            meta,
        )
        user_id = payload.get("user_id", sender_id)
        request = self.build_agent_request_from_user_content(
            channel_id=channel_id,
            sender_id=user_id,
            session_id=session_id,
            content_parts=content_parts,
            channel_meta=meta,
        )
        setattr(request, "channel_meta", meta)
        return request

    def merge_native_items(self, items: List[Any]) -> Any:
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

    # ------------------------------------------------------------------
    # Token persistence
    # ------------------------------------------------------------------

    def _load_token_from_file(self) -> str:
        """Try to load persisted bot_token from token file."""
        try:
            if self._bot_token_file.exists():
                token = self._bot_token_file.read_text(
                    encoding="utf-8",
                ).strip()
                if token:
                    logger.info(
                        "weixin: loaded bot_token from %s",
                        self._bot_token_file,
                    )
                    return token
        except Exception:
            logger.debug("weixin: failed to read token file", exc_info=True)
        return ""

    def _save_token_to_file(self, token: str) -> None:
        """Persist bot_token to token file."""
        try:
            self._bot_token_file.parent.mkdir(parents=True, exist_ok=True)
            self._bot_token_file.write_text(token, encoding="utf-8")
            logger.info("weixin: bot_token saved to %s", self._bot_token_file)
        except Exception:
            logger.warning("weixin: failed to save token file", exc_info=True)

    def _load_context_tokens(self) -> None:
        """Load persisted context_tokens from file into memory."""
        try:
            if self._context_tokens_file.exists():
                data = json.loads(
                    self._context_tokens_file.read_text(encoding="utf-8"),
                )
                if isinstance(data, dict):
                    self._user_context_tokens = {
                        k: v
                        for k, v in data.items()
                        if isinstance(k, str) and isinstance(v, str)
                    }
                    logger.info(
                        "weixin: loaded %d context_tokens from %s",
                        len(self._user_context_tokens),
                        self._context_tokens_file,
                    )
        except Exception:
            logger.debug(
                "weixin: failed to load context_tokens file",
                exc_info=True,
            )

    def _save_context_tokens(self) -> None:
        """Persist current context_tokens dict to file."""
        try:
            self._context_tokens_file.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            self._context_tokens_file.write_text(
                json.dumps(self._user_context_tokens, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            logger.debug(
                "weixin: failed to save context_tokens file",
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # Message dedup
    # ------------------------------------------------------------------

    def _is_duplicate(self, msg_id: str) -> bool:
        with self._processed_ids_lock:
            if msg_id in self._processed_ids:
                return True
            self._processed_ids[msg_id] = None
            while len(self._processed_ids) > _WEIXIN_PROCESSED_IDS_MAX:
                self._processed_ids.popitem(last=False)
        return False

    # ------------------------------------------------------------------
    # QR code login
    # ------------------------------------------------------------------

    async def _do_qrcode_login(self) -> bool:
        """Perform QR code login and update self.bot_token.

        Prints QR code URL to logger (INFO) for the user to scan.
        Returns True if login succeeded.
        """
        if not self._client:
            return False
        try:
            qr_data = await self._client.get_bot_qrcode()
            qrcode = qr_data.get("qrcode", "")
            qrcode_url = qr_data.get("url") or qr_data.get(
                "qrcode_img_content",
                "",
            )
            logger.info(
                "weixin: Please scan the QR code to log in.\n  QR URL: %s",
                qrcode_url or "(see qrcode_img_content in debug log)",
            )
            if logger.isEnabledFor(logging.DEBUG):
                img_b64 = qr_data.get("qrcode_img_content", "")
                if img_b64:
                    logger.debug(
                        "weixin: QR code base64 PNG: %s",
                        img_b64[:80],
                    )

            logger.info("weixin: waiting for QR code scan (up to 300s)…")
            token, base_url = await self._client.wait_for_login(qrcode)
            self.bot_token = token
            self._client.bot_token = token
            if base_url and base_url != self._client.base_url:
                self._client.base_url = base_url.rstrip("/")
                self._base_url = base_url.rstrip("/")
            self._save_token_to_file(token)
            logger.info("weixin: QR code login succeeded")
            return True
        except Exception:
            logger.exception("weixin: QR code login failed")
            return False

    # ------------------------------------------------------------------
    # Long-poll loop (runs in background thread)
    # ------------------------------------------------------------------

    def _run_poll_forever(self) -> None:
        """Background thread: run long-poll loop in a dedicated event loop."""
        if sys.platform == "darwin":
            poll_loop = asyncio.SelectorEventLoop()
        else:
            poll_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(poll_loop)
        self._poll_loop = poll_loop
        try:
            poll_loop.run_until_complete(self._poll_loop_async())
        except Exception:
            logger.exception("weixin: poll thread failed")
        finally:
            try:
                pending = asyncio.all_tasks(poll_loop)
                for task in pending:
                    task.cancel()
                if pending:
                    poll_loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True),
                    )
                poll_loop.run_until_complete(poll_loop.shutdown_asyncgens())
                poll_loop.close()
            except Exception:
                pass
            self._poll_loop = None

    async def _poll_loop_async(self) -> None:
        """Async long-poll loop: continuously call getupdates."""
        # Create a per-thread HTTP client
        client = ILinkClient(
            bot_token=self.bot_token,
            base_url=self._base_url,
        )
        await client.start()
        cursor = self._cursor
        try:
            while not self._stop_event.is_set():
                try:
                    data = await client.getupdates(cursor)
                    ret = data.get("ret", -1)
                    new_cursor = data.get("get_updates_buf")
                    if new_cursor is not None:
                        cursor = new_cursor
                        self._cursor = cursor
                    msgs: List[Dict[str, Any]] = data.get("msgs") or []
                    for msg in msgs:
                        await self._on_message(msg, client)
                    # ret=-1 is normal long-poll timeout (no new messages)
                    if ret != 0 and not msgs:
                        if ret == -1:
                            logger.debug(
                                "weixin getupdates timeout (ret=-1)"
                                ", continue polling",
                            )
                        else:
                            logger.warning(
                                "weixin getupdates non-zero ret=%s"
                                " (no msgs), retry in 3s",
                                ret,
                            )
                            await asyncio.sleep(3)
                except asyncio.CancelledError:
                    break
                except Exception:
                    logger.exception("weixin poll error, retry in 5s")
                    if not self._stop_event.is_set():
                        await asyncio.sleep(5)
        finally:
            await client.stop()

    # ------------------------------------------------------------------
    # Inbound message handler
    # ------------------------------------------------------------------

    async def _on_message(
        self,
        msg: Dict[str, Any],
        client: ILinkClient,
    ) -> None:
        """Parse one inbound WeixinMessage and enqueue for processing."""
        try:
            from_user_id = msg.get("from_user_id", "")
            to_user_id = msg.get("to_user_id", "")
            context_token = msg.get("context_token", "")
            group_id = msg.get("group_id", "")
            msg_type = msg.get("message_type", 0)

            # Only process user→bot messages (message_type == 1)
            if msg_type != 1:
                return

            # Dedup: use context_token as unique id
            dedup_key = (
                context_token or f"{from_user_id}_{msg.get('msg_id', '')}"
            )
            if dedup_key and self._is_duplicate(dedup_key):
                logger.debug(
                    "weixin: duplicate message skipped: %s",
                    dedup_key[:40],
                )
                return

            content_parts: List[Any] = []
            text_parts: List[str] = []

            item_list: List[Dict[str, Any]] = msg.get("item_list") or []
            for item in item_list:
                item_type = item.get("type", 0)

                if item_type == 1:
                    # Text
                    text = (
                        (item.get("text_item") or {}).get("text", "").strip()
                    )
                    # Filter out empty text or text that looks like a filename
                    # (e.g., "document.pdf", "image.jpg") to avoid triggering
                    # immediate agent replies for file-only messages.
                    # This allows BaseChannel._apply_no_text_debounce to work
                    # correctly for media-only messages.
                    if text:
                        # Check if text looks like a filename (has extension)
                        # Common file extensions to filter out
                        filename_extensions = (
                            ".txt",
                            ".doc",
                            ".docx",
                            ".pdf",
                            ".jpg",
                            ".jpeg",
                            ".png",
                            ".gif",
                            ".mp4",
                            ".avi",
                            ".mov",
                            ".mp3",
                            ".wav",
                            ".zip",
                            ".rar",
                            ".xlsx",
                            ".xls",
                            ".ppt",
                            ".pptx",
                        )
                        is_filename = any(
                            text.lower().endswith(ext)
                            for ext in filename_extensions
                        )
                        # Only add text if it's not just a filename
                        if not is_filename:
                            text_parts.append(text)

                elif item_type == 2:
                    # Image (AES-128-ECB encrypted on CDN)
                    img_item = item.get("image_item") or {}
                    media = img_item.get("media") or {}
                    encrypt_query_param = media.get("encrypt_query_param", "")
                    # Key priority: image_item.aeskey (hex) > media.aes_key
                    # Per official SDK: hex aeskey → base64 for decryption
                    aeskey_hex = img_item.get("aeskey", "")
                    if aeskey_hex:
                        aes_key = _b64.b64encode(
                            bytes.fromhex(aeskey_hex),
                        ).decode()
                    else:
                        aes_key = media.get("aes_key", "")
                    if encrypt_query_param:
                        path = await self._download_media(
                            client,
                            "",
                            aes_key,
                            "image.jpg",
                            encrypt_query_param=encrypt_query_param,
                        )
                        if path:
                            content_parts.append(
                                ImageContent(
                                    type=ContentType.IMAGE,
                                    image_url=path,
                                ),
                            )
                        else:
                            text_parts.append("[image: download failed]")
                    else:
                        text_parts.append("[image: no url]")

                elif item_type == 3:
                    # Voice — use ASR transcription text
                    voice_item = item.get("voice_item") or {}
                    asr_text = (
                        voice_item.get("text_item", {}).get("text", "").strip()
                        if isinstance(voice_item.get("text_item"), dict)
                        else voice_item.get("text", "").strip()
                    )
                    if asr_text:
                        text_parts.append(asr_text)
                    else:
                        text_parts.append("[voice: no transcription]")

                elif item_type == 4:
                    # File attachment
                    file_item = item.get("file_item") or {}
                    filename = (
                        file_item.get("file_name", "file.bin") or "file.bin"
                    )
                    media = file_item.get("media") or {}
                    encrypt_query_param = media.get("encrypt_query_param", "")
                    aes_key = media.get(
                        "aes_key",
                        "",
                    )  # base64(Format A or B), handled by aes_ecb_decrypt
                    if encrypt_query_param:
                        path = await self._download_media(
                            client,
                            "",
                            aes_key,
                            filename,
                            encrypt_query_param=encrypt_query_param,
                        )
                        if path:
                            content_parts.append(
                                FileContent(
                                    type=ContentType.FILE,
                                    file_url=path,
                                ),
                            )
                        else:
                            text_parts.append("[file: download failed]")
                    else:
                        text_parts.append("[file: no url]")

                elif item_type == 5:
                    # Video
                    video_item = item.get("video_item") or {}
                    media = video_item.get("media") or {}
                    encrypt_query_param = media.get("encrypt_query_param", "")
                    aes_key = media.get("aes_key", "")
                    if encrypt_query_param:
                        path = await self._download_media(
                            client,
                            "",
                            aes_key,
                            "video.mp4",
                            encrypt_query_param=encrypt_query_param,
                        )
                        if path:
                            content_parts.append(
                                VideoContent(
                                    type=ContentType.VIDEO,
                                    video_url=path,
                                ),
                            )
                        else:
                            text_parts.append("[video: download failed]")
                    else:
                        text_parts.append("[video: no url]")
                else:
                    text_parts.append(f"[unsupported type: {item_type}]")

            text = "\n".join(text_parts).strip()
            if text:
                content_parts.insert(
                    0,
                    TextContent(type=ContentType.TEXT, text=text),
                )
            if not content_parts:
                return

            is_group = bool(group_id)
            meta: Dict[str, Any] = {
                "weixin_from_user_id": from_user_id,
                "weixin_to_user_id": to_user_id,
                "weixin_context_token": context_token,
                "weixin_group_id": group_id,
                "is_group": is_group,
            }

            allowed, error_msg = self._check_allowlist(from_user_id, is_group)
            if not allowed:
                logger.info(
                    "weixin allowlist blocked: sender=%s is_group=%s",
                    from_user_id,
                    is_group,
                )
                if error_msg and context_token:
                    if self._loop:
                        asyncio.run_coroutine_threadsafe(
                            self._send_text_direct(
                                from_user_id,
                                error_msg,
                                context_token,
                                client,
                            ),
                            self._loop,
                        )
                return

            # Save latest context_token for proactive sends (heartbeat/cron)
            if from_user_id and context_token:
                self._user_context_tokens[from_user_id] = context_token
                self._save_context_tokens()

            # Start typing indicator for this user
            if from_user_id and context_token:

                async def _start_typing_async():
                    # Stop any existing typing indicator to prevent task leak
                    with self._typing_stop_lock:
                        old_stop = self._typing_stop_funcs.pop(
                            from_user_id,
                            None,
                        )
                    if old_stop:
                        old_stop()

                    stop_func = await self.start_typing(
                        from_user_id,
                        context_token,
                    )
                    with self._typing_stop_lock:
                        self._typing_stop_funcs[from_user_id] = stop_func

                if self._loop and self._loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        _start_typing_async(),
                        self._loop,
                    )

            session_id = self.resolve_session_id(from_user_id, meta)
            native = {
                "channel_id": self.channel,
                "sender_id": from_user_id,
                "user_id": "" if is_group else from_user_id,
                "session_id": session_id,
                "content_parts": content_parts,
                "meta": meta,
            }
            logger.info(
                "weixin recv: from=%s group=%s text_len=%s",
                (from_user_id or "")[:20],
                (group_id or "")[:20],
                len(text),
            )
            if self._enqueue is not None:
                self._enqueue(native)

        except Exception:
            logger.exception("weixin _on_message failed")

    # ------------------------------------------------------------------
    # Media download helper
    # ------------------------------------------------------------------

    async def _download_media(
        self,
        client: ILinkClient,
        url: str,
        aes_key: str = "",
        filename_hint: str = "file.bin",
        encrypt_query_param: str = "",
    ) -> Optional[str]:
        """Download and optionally decrypt a CDN media file.

        Returns local file path, or None on failure.
        """
        try:
            data = await client.download_media(
                url,
                aes_key,
                encrypt_query_param,
            )
            self._media_dir.mkdir(parents=True, exist_ok=True)
            safe_name = (
                "".join(c for c in filename_hint if c.isalnum() or c in "-_.")
                or "media"
            )
            url_hash = hashlib.md5(
                (encrypt_query_param or url).encode(),
            ).hexdigest()[:8]
            path = self._media_dir / f"weixin_{url_hash}_{safe_name}"
            path.write_bytes(data)
            return str(path)
        except Exception:
            logger.exception("weixin _download_media failed url=%s", url[:60])
            return None

    # ------------------------------------------------------------------
    # Send helpers
    # ------------------------------------------------------------------

    async def _send_text_direct(
        self,
        to_user_id: str,
        text: str,
        context_token: str,
        client: Optional[ILinkClient] = None,
    ) -> None:
        """Send text using the shared ILinkClient (or create a temp one)."""
        _client = client or self._client
        if not _client or not to_user_id or not text:
            return
        try:
            await _client.send_text(to_user_id, text, context_token)
        except Exception:
            logger.exception("weixin _send_text_direct failed")

    async def _send_media_file(
        self,
        to_user_id: str,
        context_token: str,
        file_path: str,
        content_type: ContentType,
    ) -> None:
        """Send a media file (image/file/video) to WeChat.

        Args:
            to_user_id: Recipient user ID.
            context_token: Context token from inbound message.
            file_path: Local path to the media file.
            content_type: Type of media (IMAGE/FILE/VIDEO).
        """
        if not self._client or not to_user_id or not context_token:
            logger.warning(
                "weixin _send_media_file: missing required parameters",
            )
            return

        try:
            # Convert URL to local path if it's a file:// URL
            if file_path.startswith("file://"):
                file_path = file_path[7:]

            # Check if file exists
            path_obj = Path(file_path)
            if not path_obj.exists():
                logger.warning(
                    "weixin _send_media_file: file not found: %s",
                    file_path,
                )
                return

            # Send based on content type
            if content_type == ContentType.IMAGE:
                await self._client.send_image(
                    to_user_id,
                    str(path_obj),
                    context_token,
                )
            elif content_type == ContentType.FILE:
                filename = path_obj.name
                await self._client.send_file(
                    to_user_id,
                    str(path_obj),
                    filename,
                    context_token,
                )
            elif content_type == ContentType.VIDEO:
                await self._client.send_video(
                    to_user_id,
                    str(path_obj),
                    context_token,
                )
            else:
                logger.warning(
                    "weixin _send_media_file: unsupported content type: %s",
                    content_type,
                )
        except Exception:
            logger.exception(
                "weixin _send_media_file failed type=%s path=%s",
                content_type,
                file_path[:60],
            )

    async def send_content_parts(
        self,
        to_handle: str,
        parts: List[OutgoingContentPart],
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send agent response content back to the WeChat user."""
        if not self.enabled:
            return
        m = meta or {}
        to_user_id = (
            m.get("weixin_from_user_id")
            or self._parse_user_id_from_handle(to_handle)
            or ""
        )
        context_token = m.get("weixin_context_token", "") or (
            self._user_context_tokens.get(to_user_id, "")
        )

        if not to_user_id:
            logger.warning("weixin send_content_parts: no to_user_id")
            return

        # Stop any existing typing indicator before starting a new one
        # (prevents multiple typing loops running simultaneously)
        with self._typing_stop_lock:
            old_stop = self._typing_stop_funcs.pop(to_user_id, None)
        if old_stop:
            old_stop()

        # Start typing indicator for this reply
        # (like Telegram/Mattermost: restart typing for each send)
        stop_typing = None
        if to_user_id and context_token:
            try:
                stop_typing = await self.start_typing(
                    to_user_id,
                    context_token,
                )
                # Store stop function for cleanup
                with self._typing_stop_lock:
                    self._typing_stop_funcs[to_user_id] = stop_typing
            except Exception as e:
                logger.warning(f"weixin start_typing failed: {e}")

        prefix = m.get("bot_prefix", "") or self.bot_prefix or ""
        text_parts: List[str] = []

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
                text_parts.append(text_val)
            elif t == ContentType.REFUSAL and refusal_val:
                text_parts.append(refusal_val)
            elif t == ContentType.IMAGE:
                # Send image
                image_url = getattr(p, "image_url", None) or (
                    p.get("image_url") if isinstance(p, dict) else None
                )
                if image_url:
                    await self._send_media_file(
                        to_user_id,
                        context_token,
                        image_url,
                        ContentType.IMAGE,
                    )
            elif t == ContentType.FILE:
                # Send file
                file_url = getattr(p, "file_url", None) or (
                    p.get("file_url") if isinstance(p, dict) else None
                )
                if file_url:
                    await self._send_media_file(
                        to_user_id,
                        context_token,
                        file_url,
                        ContentType.FILE,
                    )
            elif t == ContentType.VIDEO:
                # Send video
                video_url = getattr(p, "video_url", None) or (
                    p.get("video_url") if isinstance(p, dict) else None
                )
                if video_url:
                    await self._send_media_file(
                        to_user_id,
                        context_token,
                        video_url,
                        ContentType.VIDEO,
                    )

        body = "\n".join(text_parts).strip()
        if prefix and body:
            body = prefix + "  " + body

        if not body:
            if stop_typing:
                stop_typing()
            return

        for chunk in split_text(body):
            await self._send_text_direct(to_user_id, chunk, context_token)

        # Stop typing indicator after sending all messages
        if stop_typing:
            stop_typing()

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Proactive send (e.g. from scheduled jobs)."""
        if not self.enabled:
            return
        m = meta or {}
        to_user_id = (
            m.get("weixin_from_user_id")
            or self._parse_user_id_from_handle(to_handle)
            or ""
        )
        context_token = m.get("weixin_context_token", "") or (
            self._user_context_tokens.get(to_user_id, "")
        )
        prefix = m.get("bot_prefix", "") or self.bot_prefix or ""
        body = (prefix + "  " + text) if prefix and text else text
        if not body or not to_user_id:
            return
        for chunk in split_text(body):
            await self._send_text_direct(to_user_id, chunk, context_token)

    # ------------------------------------------------------------------
    # Typing Indicator
    # ------------------------------------------------------------------

    async def _get_typing_ticket(
        self,
        user_id: str,
        context_token: str,
    ) -> str:
        """Get or fetch typing ticket for a user.

        Args:
            user_id: User ID
            context_token: Context token for the user

        Returns:
            Typing ticket string (empty if failed)
        """
        import time

        now = time.time()
        cache_ttl = 24 * 3600  # 24 hours

        logger.debug(
            "weixin _get_typing_ticket called for user_id="
            f"{user_id}, context_token="
            f"{context_token[:20] if context_token else 'NONE'}...",
        )

        with self._typing_lock:
            # Check cache
            if user_id in self._typing_tickets:
                ticket, expiry = self._typing_tickets[user_id]
                if now < expiry:
                    logger.debug(
                        f"weixin using cached typing_ticket for {user_id}",
                    )
                    return ticket
                # Expired, remove from cache
                del self._typing_tickets[user_id]

        # Fetch new ticket from API
        try:
            logger.info(f"weixin calling getconfig API for {user_id}")
            resp = await self._client.getconfig(
                ilink_user_id=user_id,
                context_token=context_token,
            )
            ret = resp.get("ret", 1)
            errcode = resp.get("errcode") or 0  # Treat None as 0
            logger.info(
                f"weixin getconfig response: ret={ret}, "
                f"errcode={resp.get('errcode')}, "
                f"ticket={'FOUND' if resp.get('typing_ticket') else 'EMPTY'}",
            )
            if ret == 0 and errcode == 0:
                ticket = resp.get("typing_ticket", "").strip()
                if ticket:
                    with self._typing_lock:
                        self._typing_tickets[user_id] = (
                            ticket,
                            now + cache_ttl,
                        )
                    logger.info(
                        f"weixin got typing_ticket for {user_id}: "
                        f"{ticket[:20]}... (length={len(ticket)})",
                    )
                    return ticket
                else:
                    logger.warning(
                        "weixin getconfig returned no typing_ticket",
                    )
            else:
                logger.warning(
                    f"weixin getconfig failed: ret={ret}, "
                    f"errcode={resp.get('errcode')}",
                )
        except Exception as e:
            logger.warning(f"weixin getconfig failed: {e}")

        return ""

    async def start_typing(
        self,
        user_id: str,
        context_token: str,
    ) -> Callable[[], None]:
        """Start typing indicator for a user.

        Args:
            user_id: User ID
            context_token: Context token for the user

        Returns:
            A stop function that cancels the typing indicator
        """
        logger.info(f"weixin start_typing called for user_id={user_id}")
        ticket = await self._get_typing_ticket(user_id, context_token)
        if not ticket:
            logger.warning(f"weixin start_typing: no ticket for {user_id}")
            # Return empty function if no ticket
            return lambda: None

        stop_event = asyncio.Event()
        stop_called = False

        async def refresh_typing():
            """Refresh typing indicator every 5 seconds."""
            logger.info(f"weixin refresh_typing task started for {user_id}")
            while not stop_event.is_set():
                try:
                    await self._client.sendtyping(user_id, ticket, status=1)
                    logger.info(
                        "weixin refresh_typing: sent typing status "
                        f"for {user_id}",
                    )
                except Exception as e:
                    logger.warning(f"weixin sendtyping refresh failed: {e}")
                # Wait for 5 seconds or until stop
                try:
                    await asyncio.wait_for(
                        stop_event.wait(),
                        timeout=5.0,
                    )
                except asyncio.TimeoutError:
                    pass  # Timeout, continue refreshing
                # If wait_for completes without timeout, stop_event was set,
                # so loop will exit
            logger.info(f"weixin refresh_typing task stopped for {user_id}")

        # Start refresh task in background
        task = None
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = self._loop

        logger.info(
            f"weixin start_typing: loop={loop}, "
            f"is_running={loop.is_running() if loop else False}",
        )
        if loop and loop.is_running():
            task = asyncio.create_task(refresh_typing())
            logger.info(f"weixin start_typing: refresh task created: {task}")
        else:
            logger.warning(
                "weixin start_typing: no event loop "
                "available for refresh task",
            )

        # Send initial typing status
        try:
            logger.info(
                f"weixin sending initial typing status for {user_id} "
                f"with ticket={ticket[:20]}...",
            )
            await self._client.sendtyping(user_id, ticket, status=1)
            logger.info(
                "weixin initial typing status sent successfully "
                f"for {user_id}",
            )
        except Exception as e:
            logger.warning(f"weixin sendtyping initial failed: {e}")

        def stop(send_cancel: bool = True):
            """Stop typing indicator.

            Args:
                send_cancel: If True, send explicit cancel (status=2) to
                    immediately hide typing indicator. Set to False to let
                    it timeout naturally.
            """
            nonlocal stop_called
            if stop_called:
                return
            stop_called = True
            stop_event.set()

            # Send cancel status to immediately hide typing indicator
            if send_cancel:

                async def _cancel():
                    try:
                        await self._client.sendtyping(
                            user_id,
                            ticket,
                            status=2,
                        )
                    except Exception as e:
                        logger.debug(f"weixin sendtyping cancel failed: {e}")

                # Run cancel in background
                if loop and loop.is_running():
                    asyncio.create_task(_cancel())

        return stop

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if not self.enabled:
            logger.debug("weixin channel disabled")
            return

        # Resolve token: config > token file
        if not self.bot_token:
            self.bot_token = self._load_token_from_file()

        # Load persisted context_tokens for proactive sends
        self._load_context_tokens()

        # If still no token, do QR code login with a temporary client
        if not self.bot_token:
            login_client = ILinkClient(base_url=self._base_url)
            await login_client.start()
            try:
                self._client = login_client
                ok = await self._do_qrcode_login()
                if not ok:
                    raise ChannelError(
                        channel_name="weixin",
                        message=(
                            "WeChat QR code login failed. "
                            "Please provide a valid bot_token in config"
                        ),
                    )
                # Login succeeded; login_client becomes the long-lived client
            except Exception:
                await login_client.stop()
                self._client = None
                raise
        else:
            # Token already known — create the long-lived client now
            self._client = ILinkClient(
                bot_token=self.bot_token,
                base_url=self._base_url,
            )
            await self._client.start()

        self._loop = asyncio.get_running_loop()
        self._stop_event.clear()

        # Launch background long-poll thread
        self._poll_thread = threading.Thread(
            target=self._run_poll_forever,
            daemon=True,
            name="weixin-poll",
        )
        self._poll_thread.start()
        logger.info(
            "weixin channel started (token=%s…)",
            (self.bot_token or "")[:12],
        )

    async def stop(self) -> None:
        if not self.enabled:
            return
        self._stop_event.set()
        if self._poll_loop is not None:
            try:
                self._poll_loop.call_soon_threadsafe(self._poll_loop.stop)
            except Exception:
                pass
        if self._poll_thread:
            self._poll_thread.join(timeout=10)
        self._poll_thread = None
        if self._client:
            await self._client.stop()
        self._client = None
        logger.info("weixin channel stopped")
