# -*- coding: utf-8 -*-
# pylint: disable=too-many-statements,too-many-branches
# pylint: disable=too-many-return-statements,too-many-instance-attributes
# pylint: disable=too-many-nested-blocks
# pylint: disable=protected-access  # bypass SDK MessageHandler filter
# pylint: disable=broad-exception-caught
"""WeCom (Enterprise WeChat) Channel.

Uses the aibot WebSocket SDK to receive messages from WeCom AI Bot.
Sends replies via the same WebSocket channel using stream mode
(reply_stream). Supports text, image, voice, file, and mixed messages.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
import sys
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional

from agentscope_runtime.engine.schemas.agent_schemas import (
    AgentRequest,
    FileContent,
    ImageContent,
    TextContent,
    VideoContent,
)
from aibot import WSClient, WSClientOptions, generate_req_id

from ....constant import DEFAULT_MEDIA_DIR
from ....exceptions import ChannelError
from ..base import (
    BaseChannel,
    ContentType,
    OnReplySent,
    OutgoingContentPart,
    ProcessHandler,
)
from .utils import compress_image_for_wecom, format_markdown_tables
from ..utils import split_text

logger = logging.getLogger(__name__)

# Max number of processed message_ids to keep for dedup.
_WECOM_PROCESSED_IDS_MAX = 2000

# Media upload via WebSocket long-connection.
_UPLOAD_CHUNK_SIZE = 512 * 1024  # 512 KB of raw data per chunk
_UPLOAD_CMD_INIT = "aibot_upload_media_init"
_UPLOAD_CMD_CHUNK = "aibot_upload_media_chunk"
_UPLOAD_CMD_FINISH = "aibot_upload_media_finish"
_UPLOAD_CMDS = (_UPLOAD_CMD_INIT, _UPLOAD_CMD_CHUNK, _UPLOAD_CMD_FINISH)
_UPLOAD_ACK_TIMEOUT = 30.0  # seconds to wait for each upload ack

# Map ContentType → wecom msgtype used in send_message.
_MEDIA_MSGTYPE: Dict[str, str] = {
    "image": "image",
    "voice": "voice",
    "video": "video",
    "file": "file",
}

# Mapping for quoted media types: msgtype → (filename_hint, ContentClass,
# content_kwargs, url_field_name).  Used by _on_message to build content
# parts from quoted image / file / video items.
_QUOTE_MEDIA_MAP = {
    "image": (
        "image.jpg",
        ImageContent,
        {"type": ContentType.IMAGE},
        "image_url",
    ),
    "file": (None, FileContent, {"type": ContentType.FILE}, "file_url"),
    "video": (
        "video.mp4",
        VideoContent,
        {"type": ContentType.VIDEO},
        "video_url",
    ),
}


class WecomChannel(BaseChannel):
    """WeCom AI Bot channel: WebSocket receive and send.

    Session: for single-chat session_id = wecom:<userid>, for group-chat
    wecom:group:<chatid>. The frame from the SDK is stored in meta so
    we can call reply_stream back through the same connection.
    """

    channel = "wecom"

    def __init__(
        self,
        process: ProcessHandler,
        enabled: bool,
        bot_id: str,
        secret: str,
        bot_prefix: str = "",
        media_dir: str = "",
        welcome_text: str = "",
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
        dm_policy: str = "open",
        group_policy: str = "open",
        allow_from: Optional[List[str]] = None,
        deny_message: str = "",
        max_reconnect_attempts: int = -1,
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
        self.bot_id = bot_id
        self.secret = secret
        self.bot_prefix = bot_prefix
        self.welcome_text = welcome_text
        # Store media_dir config, will be resolved in set_workspace()
        self._media_dir_config = (
            Path(media_dir).expanduser() if media_dir else None
        )
        # Default to config or global default until set_workspace is called
        self._media_dir = self._media_dir_config or DEFAULT_MEDIA_DIR
        self._max_reconnect_attempts = max_reconnect_attempts

        self._client: Any = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ws_loop: Optional[asyncio.AbstractEventLoop] = None
        self._ws_thread: Optional[threading.Thread] = None

        # message_id dedup (ordered dict, trimmed when over limit)
        self._processed_message_ids: OrderedDict[str, None] = OrderedDict()
        self._processed_ids_lock = threading.Lock()

        # pending upload-ack futures: req_id -> Future[WsFrame]
        self._upload_ack_futures: Dict[str, "asyncio.Future[Any]"] = {}
        self._upload_lock: Optional[asyncio.Lock] = None  # init in start()

    @classmethod
    def from_env(
        cls,
        process: ProcessHandler,
        on_reply_sent: OnReplySent = None,
    ) -> "WecomChannel":
        allow_from_env = os.getenv("WECOM_ALLOW_FROM", "")
        allow_from = (
            [s.strip() for s in allow_from_env.split(",") if s.strip()]
            if allow_from_env
            else []
        )
        return cls(
            process=process,
            enabled=os.getenv("WECOM_CHANNEL_ENABLED", "0") == "1",
            bot_id=os.getenv("WECOM_BOT_ID", ""),
            secret=os.getenv("WECOM_SECRET", ""),
            bot_prefix=os.getenv("WECOM_BOT_PREFIX", ""),
            media_dir=os.getenv("WECOM_MEDIA_DIR", ""),
            on_reply_sent=on_reply_sent,
            dm_policy=os.getenv("WECOM_DM_POLICY", "open"),
            group_policy=os.getenv("WECOM_GROUP_POLICY", "open"),
            allow_from=allow_from,
            deny_message=os.getenv("WECOM_DENY_MESSAGE", ""),
            max_reconnect_attempts=int(
                os.getenv("WECOM_MAX_RECONNECT_ATTEMPTS", "-1"),
            ),
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
    ) -> "WecomChannel":
        return cls(
            process=process,
            enabled=getattr(config, "enabled", False),
            bot_id=getattr(config, "bot_id", "") or "",
            secret=getattr(config, "secret", "") or "",
            bot_prefix=getattr(config, "bot_prefix", "") or "",
            media_dir=getattr(config, "media_dir", None) or "",
            welcome_text=getattr(config, "welcome_text", "") or "",
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            filter_thinking=filter_thinking,
            dm_policy=getattr(config, "dm_policy", "open") or "open",
            group_policy=getattr(config, "group_policy", "open") or "open",
            allow_from=getattr(config, "allow_from", []) or [],
            deny_message=getattr(config, "deny_message", "") or "",
            max_reconnect_attempts=int(
                (
                    -1
                    if getattr(config, "max_reconnect_attempts", None) is None
                    else getattr(config, "max_reconnect_attempts")
                ),
            ),
        )

    # ------------------------------------------------------------------
    # Session / handle helpers
    # ------------------------------------------------------------------

    def resolve_session_id(
        self,
        sender_id: str,
        channel_meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Build session_id from meta or sender_id."""
        meta = channel_meta or {}
        chatid = (meta.get("wecom_chatid") or "").strip()
        chat_type = (meta.get("wecom_chat_type") or "single").strip()
        if chat_type == "group" and chatid:
            return f"wecom:group:{chatid}"
        if sender_id:
            return f"wecom:{sender_id}"
        return f"wecom:{chatid or 'unknown'}"

    @staticmethod
    def _parse_chatid_from_handle(to_handle: str) -> str:
        """Extract chatid/userid from a to_handle string.

        - ``wecom:group:<chatid>`` → ``<chatid>``
        - ``wecom:<userid>``       → ``<userid>``
        """
        h = (to_handle or "").strip()
        if h.startswith("wecom:group:"):
            return h.removeprefix("wecom:group:")
        if h.startswith("wecom:"):
            return h.removeprefix("wecom:")
        return h

    def to_handle_from_target(self, *, user_id: str, session_id: str) -> str:
        """Return send handle; session_id takes priority."""
        return session_id or f"wecom:{user_id}"

    def get_to_handle_from_request(self, request: Any) -> str:
        session_id = getattr(request, "session_id", "") or ""
        user_id = getattr(request, "user_id", "") or ""
        return session_id or f"wecom:{user_id}"

    def get_on_reply_sent_args(
        self,
        request: Any,
        to_handle: str,
    ) -> tuple:
        return (
            getattr(request, "user_id", "") or "",
            getattr(request, "session_id", "") or "",
        )

    def build_agent_request_from_native(
        self,
        native_payload: Any,
    ) -> "AgentRequest":
        """Build AgentRequest from a wecom native dict."""
        payload = native_payload if isinstance(native_payload, dict) else {}
        channel_id = payload.get("channel_id") or self.channel
        sender_id = payload.get("sender_id") or ""
        content_parts = payload.get("content_parts") or []
        meta = payload.get("meta") or {}
        session_id = payload.get("session_id") or self.resolve_session_id(
            sender_id,
            meta,
        )
        user_id = payload["user_id"] if "user_id" in payload else sender_id
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
        """Merge same-session native payloads: concat content_parts."""
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
            "sender_id": last.get(
                "sender_id",
                first.get("sender_id", ""),
            ),
            "user_id": last.get("user_id", first.get("user_id", "")),
            "session_id": last.get(
                "session_id",
                first.get("session_id", ""),
            ),
            "content_parts": merged_parts,
            "meta": dict(last.get("meta") or {}),
        }

    # ------------------------------------------------------------------
    # Message dedup helper
    # ------------------------------------------------------------------

    def _is_duplicate(self, msg_id: str) -> bool:
        """Return True if msg_id was already seen; record it."""
        with self._processed_ids_lock:
            if msg_id in self._processed_message_ids:
                return True
            self._processed_message_ids[msg_id] = None
            while len(self._processed_message_ids) > _WECOM_PROCESSED_IDS_MAX:
                self._processed_message_ids.popitem(last=False)
        return False

    # ------------------------------------------------------------------
    # Incoming message handlers (called from WS thread, dispatch to loop)
    # ------------------------------------------------------------------

    def _on_message_sync(self, frame: Any) -> None:
        """Sync handler called from SDK event; dispatches to async loop."""
        if not self._loop or not self._loop.is_running():
            logger.warning("wecom: main loop not set/running, drop message")
            return
        asyncio.run_coroutine_threadsafe(
            self._on_message(frame),
            self._loop,
        )

    async def _on_message(self, frame: Any) -> None:
        """Parse and enqueue one incoming message."""
        try:
            body = frame.get("body") or {}
            msgtype = body.get("msgtype") or ""
            sender_id = (body.get("from") or {}).get("userid", "")
            chatid = body.get("chatid", "")
            chat_type = body.get("chattype", "single")

            # Build unique message id for dedup
            msg_id = (
                body.get("msgid") or ""
            ) or f"{sender_id}_{body.get('send_time', '')}"
            if msg_id and self._is_duplicate(msg_id):
                return

            content_parts: List[Any] = []
            text_parts: List[str] = []

            if msgtype == "text":
                text = (body.get("text") or {}).get("content", "").strip()
                if text:
                    text_parts.append(text)

            elif msgtype == "image":
                img_info = body.get("image") or {}
                url = img_info.get("url") or ""
                aes_key = img_info.get("aeskey") or ""
                if url:
                    path = await self._download_media(
                        url,
                        aes_key=aes_key,
                        filename_hint="image.jpg",
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

            elif msgtype == "voice":
                voice_info = body.get("voice") or {}
                # Use ASR text from WeCom; no need to download audio
                asr_text = voice_info.get("content", "").strip()
                if asr_text:
                    text_parts.append(asr_text)
                else:
                    text_parts.append("[voice: no text]")

            elif msgtype == "file":
                file_info = body.get("file") or {}
                url = file_info.get("url") or ""
                aes_key = file_info.get("aeskey") or ""
                filename = file_info.get("filename") or "file.bin"
                if url:
                    path = await self._download_media(
                        url,
                        aes_key=aes_key,
                        filename_hint=filename,
                    )
                    if path:
                        content_parts.append(
                            FileContent(
                                type=ContentType.FILE,
                                file_url=path,
                                filename=filename,
                            ),
                        )
                    else:
                        text_parts.append("[file: download failed]")
                else:
                    text_parts.append("[file: no url]")

            elif msgtype == "video":
                video_info = body.get("video") or {}
                url = video_info.get("url") or ""
                aes_key = video_info.get("aeskey") or ""
                if url:
                    path = await self._download_media(
                        url,
                        aes_key=aes_key,
                        filename_hint="video.mp4",
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

            elif msgtype == "mixed":
                # Mixed: list of items, each has msgtype, text or image
                mixed_items = body.get("mixed", {}).get("msg_item", [])
                for item in mixed_items:
                    itype = item.get("msgtype") or ""
                    if itype == "text":
                        t = item.get("text", {}).get("content", "").strip()
                        if t:
                            text_parts.append(t)
                    elif itype == "image":
                        img = item.get("image") or {}
                        url = img.get("url") or ""
                        aes_key = img.get("aeskey") or ""
                        if url:
                            path = await self._download_media(
                                url,
                                aes_key=aes_key,
                                filename_hint="image.jpg",
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
                    elif itype == "file":
                        file_info = item.get("file") or {}
                        url = file_info.get("url") or ""
                        aes_key = file_info.get("aeskey") or ""
                        filename = file_info.get("filename") or "file.bin"
                        if url:
                            path = await self._download_media(
                                url,
                                aes_key=aes_key,
                                filename_hint=filename,
                            )
                            if path:
                                content_parts.append(
                                    FileContent(
                                        type=ContentType.FILE,
                                        file_url=path,
                                        filename=filename,
                                    ),
                                )
                            else:
                                text_parts.append("[file: download failed]")
                        else:
                            text_parts.append("[file: no url]")
            else:
                text_parts.append(f"[{msgtype}]")

            # Handle quoted (replied-to) message if present
            quote = body.get("quote")
            if quote:
                quote_type = quote.get("msgtype") or ""
                # Flatten quote into a list of items for unified processing.
                # Single-type quotes become a one-element list; mixed quotes
                # already contain a list of items.
                if quote_type == "mixed":
                    quoted_items = quote.get("mixed", {}).get("msg_item", [])
                elif quote_type:
                    quoted_items = [quote]
                else:
                    quoted_items = []

                for q_item in quoted_items:
                    q_type = q_item.get("msgtype") or ""
                    if q_type == "text":
                        quoted_text = (
                            (q_item.get("text") or {})
                            .get("content", "")
                            .strip()
                        )
                        if quoted_text:
                            text_parts.insert(
                                0,
                                f"[quoted message: {quoted_text}]",
                            )
                    elif q_type in _QUOTE_MEDIA_MAP:
                        (
                            hint_default,
                            content_cls,
                            content_kwargs,
                            url_field,
                        ) = _QUOTE_MEDIA_MAP[q_type]
                        q_data = q_item.get(q_type) or {}
                        q_url = q_data.get("url") or ""
                        q_aes_key = q_data.get("aeskey") or ""
                        hint = (
                            hint_default
                            or q_data.get("filename")
                            or "file.bin"
                        )
                        if q_url:
                            q_path = await self._download_media(
                                q_url,
                                aes_key=q_aes_key,
                                filename_hint=hint,
                            )
                            if q_path:
                                content_parts.append(
                                    content_cls(
                                        **content_kwargs,
                                        **{url_field: q_path},
                                    ),
                                )
                            else:
                                text_parts.insert(
                                    0,
                                    f"[quoted {q_type}: download failed]",
                                )
                    else:
                        text_parts.insert(
                            0,
                            f"[quoted {q_type} message]",
                        )

            text = "\n".join(text_parts).strip()
            if text:
                content_parts.insert(
                    0,
                    TextContent(type=ContentType.TEXT, text=text),
                )
            if not content_parts:
                return

            is_group = chat_type == "group"
            meta: Dict[str, Any] = {
                "wecom_sender_id": sender_id,
                "wecom_chatid": chatid,
                "wecom_chat_type": chat_type,
                "wecom_frame": frame,
                "is_group": is_group,
            }

            allowed, error_msg = self._check_allowlist(sender_id, is_group)
            if not allowed:
                logger.info(
                    "wecom allowlist blocked: sender=%s is_group=%s",
                    sender_id,
                    is_group,
                )
                await self._send_text_via_frame(
                    frame,
                    error_msg or "Access denied.",
                )
                return

            # Send "processing" indicator only if message has text content
            processing_stream_id = ""
            if text_parts and self._client:
                processing_stream_id = generate_req_id("stream")
                try:
                    await self._client.reply_stream(
                        frame,
                        stream_id=processing_stream_id,
                        content="🤔 Thinking...",
                        finish=False,
                    )
                except Exception:
                    logger.debug("wecom failed to send processing indicator")

            session_id = self.resolve_session_id(sender_id, meta)
            if processing_stream_id:
                meta["wecom_processing_stream_id"] = processing_stream_id
            native = {
                "channel_id": self.channel,
                "sender_id": sender_id,
                # Group chats share one session; omit user_id so the
                # session file is keyed by session_id only.
                "user_id": "" if is_group else sender_id,
                "session_id": session_id,
                "content_parts": content_parts,
                "meta": meta,
            }
            logger.info(
                "wecom recv: sender=%s chatid=%s msgtype=%s text_len=%s",
                sender_id[:20],
                (chatid or "")[:20],
                msgtype,
                len(text),
            )
            if self._enqueue is not None:
                self._enqueue(native)
        except Exception:
            logger.exception("wecom _on_message failed")

    def _on_enter_chat_sync(self, frame: Any) -> None:
        """Sync handler called from SDK event; dispatches to async loop."""
        if not self._loop or not self._loop.is_running():
            logger.warning("wecom: main loop not set/running, drop enter_chat")
            return
        asyncio.run_coroutine_threadsafe(
            self._on_enter_chat(frame),
            self._loop,
        )

    async def _on_enter_chat(self, frame: Any) -> None:
        """Handle enter_chat event; send welcome reply if configured."""
        logger.info("wecom enter_chat event")
        if not self.welcome_text or not self._client:
            return
        await self._client.reply_welcome(
            frame,
            {"msgtype": "text", "text": {"content": self.welcome_text}},
        )

    # ------------------------------------------------------------------
    # File download helper
    # ------------------------------------------------------------------

    async def _download_media(
        self,
        url: str,
        aes_key: str = "",
        filename_hint: str = "file.bin",
    ) -> Optional[str]:
        """Download (and optionally decrypt) media; return local path."""
        if not self._client:
            return None
        try:
            data, filename = await self._client.download_file(
                url,
                aes_key or None,
            )
            fn = filename or filename_hint
            # Determine extension from hint if file has none
            hint_ext = Path(filename_hint).suffix
            if hint_ext and Path(fn).suffix in ("", ".bin", ".file"):
                fn = (Path(fn).stem or "file") + hint_ext
            self._media_dir.mkdir(parents=True, exist_ok=True)
            safe_name = (
                "".join(c for c in fn if c.isalnum() or c in "-_.") or "media"
            )
            url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
            path = self._media_dir / f"wecom_{url_hash}_{safe_name}"
            path.write_bytes(data)
            return str(path)
        except Exception:
            logger.exception("wecom _download_media failed url=%s", url[:60])
            return None

    # ------------------------------------------------------------------
    # Send helpers
    # ------------------------------------------------------------------

    async def _send_ws_cmd(
        self,
        cmd: str,
        body: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Send a raw WebSocket command frame and await the ack.

        Returns the ack frame body dict, or raises on timeout / error.
        """
        req_id = generate_req_id(cmd)
        loop = asyncio.get_event_loop()
        fut: asyncio.Future[Any] = loop.create_future()
        self._upload_ack_futures[req_id] = fut
        try:
            await self._client._ws_manager.send(
                {"cmd": cmd, "headers": {"req_id": req_id}, "body": body},
            )
            ack = await asyncio.wait_for(
                asyncio.shield(fut),
                timeout=_UPLOAD_ACK_TIMEOUT,
            )
        finally:
            self._upload_ack_futures.pop(req_id, None)
        errcode = ack.get("errcode", -1)
        if errcode != 0:
            raise ChannelError(
                channel_name="wecom",
                message=(
                    f"wecom upload cmd={cmd} failed: "
                    f"errcode={errcode} errmsg={ack.get('errmsg')}"
                ),
            )
        return ack.get("body") or {}

    async def _upload_media(  # pylint: disable=too-many-locals
        self,
        path: str,
        media_type: str,
    ) -> Optional[str]:
        """Upload a local file via WebSocket chunks; return media_id.

        Args:
            path: Local file path (may have file:// prefix).
            media_type: One of image / voice / video / file.
        Returns:
            media_id string, or None on failure.
        """
        if not self._client or not self._upload_lock:
            return None
        # Strip file:// prefix
        local = path.removeprefix("file://")
        p = Path(local)
        if not p.is_file():
            logger.warning("wecom upload: file not found: %s", local[:80])
            return None

        # Compress image if needed (WeCom has 2MB limit)
        if media_type == "image":
            data, filename = compress_image_for_wecom(local)
        else:
            data = p.read_bytes()
            filename = p.name

        total_size = len(data)
        md5 = hashlib.md5(data).hexdigest()

        # Split into chunks
        chunks: List[bytes] = [
            data[i : i + _UPLOAD_CHUNK_SIZE]
            for i in range(0, total_size, _UPLOAD_CHUNK_SIZE)
        ]
        total_chunks = len(chunks)

        async with self._upload_lock:
            try:
                # Step 1: init
                init_body = await self._send_ws_cmd(
                    _UPLOAD_CMD_INIT,
                    {
                        "type": media_type,
                        "filename": filename,
                        "total_size": total_size,
                        "total_chunks": total_chunks,
                        "md5": md5,
                    },
                )
                upload_id = init_body.get("upload_id", "")
                if not upload_id:
                    raise ChannelError(
                        channel_name="wecom",
                        message="wecom upload: empty upload_id",
                    )
                logger.debug(
                    "wecom upload init: upload_id=%s chunks=%d",
                    upload_id[:20],
                    total_chunks,
                )

                # Step 2: chunks
                for idx, chunk in enumerate(chunks):
                    await self._send_ws_cmd(
                        _UPLOAD_CMD_CHUNK,
                        {
                            "upload_id": upload_id,
                            "chunk_index": idx,
                            "base64_data": base64.b64encode(chunk).decode(),
                        },
                    )

                # Step 3: finish
                finish_body = await self._send_ws_cmd(
                    _UPLOAD_CMD_FINISH,
                    {"upload_id": upload_id},
                )
                media_id = finish_body.get("media_id", "")
                if not media_id:
                    raise ChannelError(
                        channel_name="wecom",
                        message="wecom upload: empty media_id",
                    )
                logger.info(
                    "wecom upload done: media_id=%s type=%s",
                    media_id[:20],
                    media_type,
                )
                return media_id
            except Exception:
                logger.exception(
                    "wecom _upload_media failed path=%s",
                    local[:60],
                )
                return None

    async def _send_media_part(
        self,
        chatid: str,
        part: OutgoingContentPart,
        frame: Any,
    ) -> None:
        """Upload a media part and send it via send_message."""
        pt = getattr(part, "type", None)
        if pt == ContentType.IMAGE:
            raw_path = getattr(part, "image_url", "") or ""
            media_type = "image"
        elif pt == ContentType.AUDIO:
            # AudioContent stores path/URL in .data (not .file_url)
            raw_path = (
                getattr(part, "data", "")
                or getattr(part, "file_url", "")
                or ""
            )
            # WeCom voice only supports AMR; send other formats as file.
            _local = raw_path.removeprefix("file://")
            media_type = (
                "voice" if Path(_local).suffix.lower() == ".amr" else "file"
            )
        elif pt == ContentType.VIDEO:
            raw_path = getattr(part, "video_url", "") or ""
            media_type = "video"
        elif pt == ContentType.FILE:
            raw_path = getattr(part, "file_url", "") or ""
            media_type = "file"
        else:
            return

        if not raw_path:
            return

        media_id = await self._upload_media(raw_path, media_type)
        if not media_id:
            logger.warning("wecom: upload failed, skipping media part")
            return

        msgtype = _MEDIA_MSGTYPE.get(media_type, "file")
        msg_body: Dict[str, Any] = {
            "msgtype": msgtype,
            msgtype: {"media_id": media_id},
        }

        if frame:
            try:
                await self._client.reply(
                    frame,
                    {"msgtype": msgtype, msgtype: {"media_id": media_id}},
                )
            except Exception:
                logger.exception("wecom send media via reply failed")
        elif chatid and self._client:
            try:
                await self._client.send_message(chatid, msg_body)
            except Exception:
                logger.exception(
                    "wecom send media via send_message failed chatid=%s",
                    chatid[:20],
                )

    async def _send_text_via_frame(
        self,
        frame: Any,
        text: str,
        stream_id: str = "",
    ) -> None:
        """Send a text reply using the SDK reply method (stream finish).

        Args:
            frame: WebSocket frame from the incoming message.
            text: Content to send.
            stream_id: Optional stream ID to overwrite existing message.
                       If empty, a new UUID is generated.
        """
        if not self._client or not text:
            return
        try:
            sid = stream_id or generate_req_id("stream")
            await self._client.reply_stream(
                frame,
                stream_id=sid,
                content=text,
                finish=True,
            )
        except Exception:
            logger.exception("wecom _send_text_via_frame failed")

    async def send_content_parts(  # pylint: disable=too-many-locals
        self,
        to_handle: str,
        parts: List[OutgoingContentPart],
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send text (stream) and media parts back to WeCom."""
        if not self.enabled:
            return
        m = meta or {}
        frame = m.get("wecom_frame")
        chatid = (
            m.get("wecom_chatid")
            or self._parse_chatid_from_handle(to_handle)
            or ""
        )

        prefix = m.get("bot_prefix", "") or self.bot_prefix or ""
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
                text_parts.append(text_val)
            elif t == ContentType.REFUSAL and refusal_val:
                text_parts.append(refusal_val)
            elif t in (
                ContentType.IMAGE,
                ContentType.FILE,
                ContentType.VIDEO,
                ContentType.AUDIO,
            ):
                media_parts.append(p)

        body = "\n".join(text_parts).strip()
        if prefix and body:
            body = prefix + "  " + body

        # Format markdown tables for WeCom compatibility
        body = format_markdown_tables(body)

        # Use processing stream_id to overwrite "thinking..." indicator
        # Only first reply uses it; subsequent replies get new stream_id
        processing_sid = m.pop("wecom_processing_stream_id", "")

        first_chunk = True
        for chunk in split_text(body) if body else []:
            sid = processing_sid if first_chunk else ""
            first_chunk = False
            if frame:
                await self._send_text_via_frame(frame, chunk, sid)
            elif chatid:
                try:
                    await self._client.send_message(
                        chatid,
                        {
                            "msgtype": "markdown",
                            "markdown": {"content": chunk},
                        },
                    )
                except Exception:
                    logger.exception(
                        "wecom send_content_parts proactive failed",
                    )

        # If processing indicator was not consumed by text (media-only reply),
        # clear it with an empty finish before sending media.
        if processing_sid and first_chunk and frame:
            try:
                await self._client.reply_stream(
                    frame,
                    stream_id=processing_sid,
                    content="✅ Done",
                    finish=True,
                )
            except Exception:
                logger.debug("wecom: failed to clear processing indicator")

        for part in media_parts:
            await self._send_media_part(chatid, part, frame)

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Proactive send: use send_message with markdown body."""
        if not self.enabled:
            return
        m = meta or {}
        chatid = (
            m.get("wecom_chatid")
            or self._parse_chatid_from_handle(to_handle)
            or ""
        )
        frame = m.get("wecom_frame")
        prefix = m.get("bot_prefix", "") or self.bot_prefix or ""
        body = (prefix + text) if text else prefix

        if not body:
            return

        for chunk in split_text(body):
            if frame:
                await self._send_text_via_frame(frame, chunk)
            elif chatid and self._client:
                try:
                    await self._client.send_message(
                        chatid,
                        {
                            "msgtype": "markdown",
                            "markdown": {"content": chunk},
                        },
                    )
                except Exception:
                    logger.exception(
                        "wecom send proactive failed chatid=%s",
                        chatid,
                    )
            else:
                logger.warning(
                    "wecom send: no frame/chatid for to_handle=%s",
                    (to_handle or "")[:40],
                )
                break

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_stdio() -> None:
        """Redirect broken stdout/stderr to devnull (Windows daemon)."""
        for name in ("stdout", "stderr"):
            stream = getattr(sys, name, None)
            needs_fix = stream is None
            if not needs_fix:
                try:
                    stream.write("")
                    stream.flush()
                except (
                    OSError,
                    ValueError,
                    AttributeError,
                    TypeError,
                ):
                    needs_fix = True
            if needs_fix:
                setattr(
                    sys,
                    name,
                    open(  # noqa: SIM115  pylint: disable=consider-using-with
                        os.devnull,
                        "w",
                        encoding="utf-8",
                    ),
                )

    def _run_ws_forever(self) -> None:
        """Background thread: run SDK event loop forever."""
        # Windows daemon fix: aibot SDK logger calls print() which
        # crashes when stdout is detached.  Ensure streams are valid.
        self._ensure_stdio()

        # macOS/Python 3.12+ fix: use SelectorEventLoop explicitly
        if sys.platform == "darwin":
            ws_loop = asyncio.SelectorEventLoop()
        else:
            ws_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(ws_loop)
        self._ws_loop = ws_loop

        # Set thread name for debugging
        threading.current_thread().name = "wecom-ws"

        try:
            # Run connection in the new loop
            ws_loop.run_until_complete(self._client.connect())
            ws_loop.run_forever()
        except Exception:
            logger.exception("wecom WebSocket thread failed")
        finally:
            try:
                # Cancel all pending tasks
                pending = asyncio.all_tasks(ws_loop)
                for task in pending:
                    task.cancel()
                if pending:
                    ws_loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True),
                    )
                ws_loop.run_until_complete(ws_loop.shutdown_asyncgens())
                ws_loop.close()
            except Exception:
                pass
            self._ws_loop = None

    async def start(self) -> None:
        if not self.enabled:
            logger.debug("wecom channel disabled")
            return

        if not self.bot_id or not self.secret:
            raise ChannelError(
                channel_name="wecom",
                message=(
                    "WECOM_BOT_ID and WECOM_SECRET are required "
                    "when the wecom channel is enabled"
                ),
            )

        self._loop = asyncio.get_running_loop()
        self._upload_lock = asyncio.Lock()
        options = WSClientOptions(
            bot_id=self.bot_id,
            secret=self.secret,
            max_reconnect_attempts=self._max_reconnect_attempts,
        )
        self._client = WSClient(options)

        # Intercept raw WS frames before MessageHandler so upload acks
        # (which have no msgtype) are routed to the waiting futures.
        _orig_on_message = self._client._ws_manager.on_message

        def _ws_raw_handler(frame: Any) -> None:
            req_id = (frame.get("headers") or {}).get("req_id", "")
            if req_id and req_id.startswith(_UPLOAD_CMDS):
                fut = self._upload_ack_futures.get(req_id)
                if fut and not fut.done() and self._loop:
                    self._loop.call_soon_threadsafe(fut.set_result, frame)
                return
            if _orig_on_message:
                _orig_on_message(frame)

        self._client._ws_manager.on_message = _ws_raw_handler

        # Register event handlers
        self._client.on("message", self._on_message_sync)
        self._client.on("event.enter_chat", self._on_enter_chat_sync)

        # Patch SDK heartbeat to trigger reconnect on pong timeout.
        # Use ensure_future so reconnect survives heartbeat task cancel.
        ws_mgr = self._client._ws_manager
        _original_send_heartbeat = ws_mgr._send_heartbeat

        async def _patched_send_heartbeat() -> None:
            if ws_mgr._missed_pong_count >= ws_mgr._max_missed_pong:
                logger.warning(
                    "wecom heartbeat: no pong for %d pings, "
                    "triggering reconnect",
                    ws_mgr._missed_pong_count,
                )
                # Schedule reconnect BEFORE _stop_heartbeat() because
                # it cancels the current task; any await after that
                # would raise CancelledError.
                asyncio.ensure_future(ws_mgr._schedule_reconnect())
                ws_mgr._stop_heartbeat()
                if ws_mgr._ws:
                    try:
                        await ws_mgr._ws.close()
                    except Exception as close_err:
                        logger.warning(
                            "wecom heartbeat: failed to close ws: %s",
                            close_err,
                        )
                return
            # Normal path: delegate to original SDK implementation.
            await _original_send_heartbeat()

        ws_mgr._send_heartbeat = _patched_send_heartbeat

        # Log reconnect events for observability.
        self._client.on(
            "disconnected",
            lambda reason: logger.info(
                "wecom disconnected: %s",
                reason,
            ),
        )
        self._client.on(
            "reconnecting",
            lambda attempt: logger.info(
                "wecom reconnecting: attempt %d",
                attempt,
            ),
        )
        self._client.on(
            "error",
            lambda error: logger.error(
                "wecom error: %s",
                error,
            ),
        )

        self._ws_thread = threading.Thread(
            target=self._run_ws_forever,
            daemon=True,
            name="wecom-ws",
        )
        self._ws_thread.start()
        logger.info(
            "wecom channel started (bot_id=%s)",
            (self.bot_id or "")[:12],
        )

    def set_workspace(self, workspace, command_registry=None) -> None:
        """Set workspace and resolve media directory.

        This is called by ChannelManager when the channel is registered.
        Priority order:
        1. User-provided config (WECOM_MEDIA_DIR / media_dir param)
        2. {workspace_dir}/media (e.g. ./workspaces/default/media)
        3. Global default (e.g. ~/.copaw/media)
        """
        # Call parent set_workspace to set _workspace and _command_registry
        super().set_workspace(workspace, command_registry)

        # User-provided config takes highest priority
        if self._media_dir_config:
            self._media_dir = self._media_dir_config
            logger.info(
                "wecom media_dir: using user config path=%s",
                self._media_dir,
            )
            return

        if workspace:
            workspace_dir = workspace.workspace_dir
            media_dir = workspace_dir / "media"
            if not media_dir.is_dir():
                try:
                    media_dir.mkdir(parents=True, exist_ok=True)
                    logger.info(
                        "wecom media_dir: created workspace path=%s",
                        media_dir,
                    )
                except Exception as e:
                    logger.warning(
                        "wecom media_dir: failed to create path=%s, err=%s",
                        media_dir,
                        e,
                    )
                    media_dir = DEFAULT_MEDIA_DIR
            self._media_dir = media_dir
            logger.info(
                "wecom media_dir: using workspace path=%s",
                self._media_dir,
            )
        else:
            # No workspace, use global default
            self._media_dir = DEFAULT_MEDIA_DIR
            logger.info(
                "wecom media_dir: using default path=%s",
                self._media_dir,
            )

    async def stop(self) -> None:
        if not self.enabled:
            return
        if self._client:
            try:
                self._client.disconnect()
            except Exception:
                pass
        if self._ws_loop is not None:
            try:
                self._ws_loop.call_soon_threadsafe(self._ws_loop.stop)
            except Exception:
                pass
        if self._ws_thread:
            self._ws_thread.join(timeout=5)
        self._client = None
        logger.info("wecom channel stopped")
