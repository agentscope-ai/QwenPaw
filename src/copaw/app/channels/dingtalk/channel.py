# -*- coding: utf-8 -*-
# pylint: disable=too-many-statements,too-many-branches
# pylint: disable=too-many-return-statements
"""DingTalk Channel.

Why only one reply by default: DingTalk Stream callback is request-reply.
The handler process() is awaited until reply_future is set once,
then reply_text() is called once.
So we merge all streamed content into one reply. When sessionWebhook is
present we can send multiple messages via that webhook (one POST per
completed message), then set the future to a sentinel so process() skips the
single reply_text.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import mimetypes
import os
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from urllib.parse import urlparse

import aiohttp
import dingtalk_stream
from dingtalk_stream import ChatbotMessage
from agentscope_runtime.engine.schemas.agent_schemas import RunStatus

from ..utils import file_url_to_local_path
from ....config.config import DingTalkConfig as DingTalkChannelConfig
from ....config.utils import get_config_path

from ..base import (
    BaseChannel,
    ContentType,
    OnReplySent,
    OutgoingContentPart,
    ProcessHandler,
)

from .constants import (
    DINGTALK_TOKEN_TTL_SECONDS,
    SENT_VIA_WEBHOOK,
)
from .content_utils import (
    parse_data_url,
    session_param_from_webhook_url,
    short_session_id_from_conversation_id,
)
from .handler import DingTalkChannelHandler
from . import markdown as dingtalk_markdown
from .utils import guess_suffix_from_file_content

if TYPE_CHECKING:
    from agentscope_runtime.engine.schemas.agent_schemas import AgentRequest

logger = logging.getLogger(__name__)


class DingTalkChannel(BaseChannel):
    """DingTalk Channel: DingTalk Stream -> Incoming -> to_agent_request ->
    process -> send_response -> DingTalk reply.

    Proactive send (stored sessionWebhook):
    - We store sessionWebhook from incoming messages in memory; send() uses it.
    - Key uses short suffix of conversation_id so request and cron stay short.
    - to_handle "dingtalk:sw:<session_id>" (session_id = last N of conv id).
    - Note: sessionWebhook has an expiry (sessionWebhookExpiredTime);
      push only works for users who have chatted recently. For cron to
      users who may not
      have spoken, consider Open API (corp_id + batchSend) instead.
    """

    channel = "dingtalk"

    def __init__(
        self,
        process: ProcessHandler,
        enabled: bool,
        client_id: str,
        client_secret: str,
        bot_prefix: str,
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
        self.client_id = client_id
        self.client_secret = client_secret
        self.bot_prefix = bot_prefix
        self._media_dir = Path(media_dir).expanduser()

        self._client: Optional[dingtalk_stream.DingTalkStreamClient] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stream_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._http: Optional[aiohttp.ClientSession] = None

        # Store sessionWebhook for proactive send (in-memory).
        # Key is a handle string, e.g. "dingtalk:sw:<sender>"
        self._session_webhook_store: Dict[str, str] = {}
        self._session_webhook_lock = asyncio.Lock()

        # Time debounce disabled: manager drains same-session from queue
        # and merges before calling us.
        self._debounce_seconds = 0.0

        # Token cache (instance-level for multi-instance / tests)
        self._token_lock = asyncio.Lock()
        self._token_value: Optional[str] = None
        self._token_expires_at: float = 0.0

    @classmethod
    def from_env(
        cls,
        process: ProcessHandler,
        on_reply_sent: OnReplySent = None,
    ) -> "DingTalkChannel":
        return cls(
            process=process,
            enabled=os.getenv("DINGTALK_CHANNEL_ENABLED", "1") == "1",
            client_id=os.getenv("DINGTALK_CLIENT_ID", ""),
            client_secret=os.getenv("DINGTALK_CLIENT_SECRET", ""),
            bot_prefix=os.getenv("DINGTALK_BOT_PREFIX", "[BOT] "),
            media_dir=os.getenv("DINGTALK_MEDIA_DIR", "~/.copaw/media"),
            on_reply_sent=on_reply_sent,
        )

    @classmethod
    def from_config(
        cls,
        process: ProcessHandler,
        config: DingTalkChannelConfig,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
    ) -> "DingTalkChannel":
        return cls(
            process=process,
            enabled=config.enabled,
            client_id=config.client_id or "",
            client_secret=config.client_secret or "",
            bot_prefix=config.bot_prefix or "[BOT] ",
            media_dir=config.media_dir or "~/.copaw/media",
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
        )

    # ---------------------------
    # Proactive send: webhook store
    # ---------------------------

    def resolve_session_id(
        self,
        sender_id: str,
        channel_meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Session_id = short suffix of conversation_id for cron lookup."""
        meta = channel_meta or {}
        cid = meta.get("conversation_id")
        if cid:
            return short_session_id_from_conversation_id(cid)
        return f"{self.channel}:{sender_id}"

    def build_agent_request_from_native(
        self,
        native_payload: Any,
    ) -> "AgentRequest":
        """Build AgentRequest from DingTalk native dict (runtime content)."""
        payload = native_payload if isinstance(native_payload, dict) else {}
        channel_id = payload.get("channel_id") or self.channel
        sender_id = payload.get("sender_id") or ""
        content_parts = payload.get("content_parts") or []
        meta = dict(payload.get("meta") or {})
        if payload.get("session_webhook"):
            meta["session_webhook"] = payload["session_webhook"]
        session_id = self.resolve_session_id(sender_id, meta)
        request = self.build_agent_request_from_user_content(
            channel_id=channel_id,
            sender_id=sender_id,
            session_id=session_id,
            content_parts=content_parts,
            channel_meta=meta,
        )
        if hasattr(request, "channel_meta"):
            request.channel_meta = meta
        return request

    def to_handle_from_target(self, *, user_id: str, session_id: str) -> str:
        # Key by session_id (short suffix of conversation_id) so cron can
        # use the same session_id to look up stored sessionWebhook.
        return f"dingtalk:sw:{session_id}"

    def _route_from_handle(self, to_handle: str) -> dict:
        # to_handle:
        # - "dingtalk:sw:<sender>" -> use stored webhook by key
        # - "dingtalk:webhook:<url>" -> direct webhook URL
        # - "<url>" (starts with http/https) -> direct webhook URL
        s = (to_handle or "").strip()
        if s.startswith("http://") or s.startswith("https://"):
            return {"session_webhook": s}

        parts = s.split(":", 2)
        if len(parts) == 3 and parts[0] == "dingtalk":
            kind, ident = parts[1], parts[2]
            if kind == "sw":
                return {"webhook_key": f"dingtalk:sw:{ident}"}
            if kind == "webhook":
                return {"session_webhook": ident}
        return {"webhook_key": s} if s else {}

    def _session_webhook_store_path(self) -> Path:
        """Path to persist session webhook mapping (for cron after restart)."""
        return get_config_path().parent / "dingtalk_session_webhooks.json"

    def _load_session_webhook_store_from_disk(self) -> None:
        """Load session webhook mapping from disk into memory."""
        path = self._session_webhook_store_path()
        if not path.is_file():
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for k, v in data.items():
                    if isinstance(v, str) and v:
                        self._session_webhook_store[k] = v
        except Exception:
            logger.debug(
                "dingtalk load session_webhook store from %s failed",
                path,
                exc_info=True,
            )

    def _save_session_webhook_store_to_disk(self) -> None:
        """Persist in-memory session webhook store to disk."""
        path = self._session_webhook_store_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(
                    self._session_webhook_store,
                    f,
                    indent=2,
                    ensure_ascii=False,
                )
        except Exception:
            logger.debug(
                "dingtalk save session_webhook store to %s failed",
                path,
                exc_info=True,
            )

    async def _save_session_webhook(
        self,
        webhook_key: str,
        session_webhook: str,
    ) -> None:
        if not webhook_key or not session_webhook:
            logger.debug(
                "dingtalk _save_session_webhook skip: key=%s has_url=%s",
                bool(webhook_key),
                bool(session_webhook),
            )
            return
        session_in_url = session_param_from_webhook_url(session_webhook)
        logger.info(
            "dingtalk _save_session_webhook: "
            "webhook_key=%s session_from_url=%s",
            webhook_key,
            session_in_url,
        )
        async with self._session_webhook_lock:
            self._session_webhook_store[webhook_key] = session_webhook
            self._save_session_webhook_store_to_disk()

    async def _load_session_webhook(self, webhook_key: str) -> Optional[str]:
        if not webhook_key:
            logger.debug("dingtalk _load_session_webhook: empty webhook_key")
            return None
        async with self._session_webhook_lock:
            out = self._session_webhook_store.get(webhook_key)
            if out is not None:
                logger.info(
                    "dingtalk _load_session_webhook hit: webhook_key=%s "
                    "session_from_url=%s",
                    webhook_key,
                    session_param_from_webhook_url(out),
                )
                return out
            self._load_session_webhook_store_from_disk()
            out = self._session_webhook_store.get(webhook_key)
            if out is not None:
                logger.info(
                    "dingtalk _load_session_webhook hit(disk): webhook_key=%s "
                    "session_from_url=%s",
                    webhook_key,
                    session_param_from_webhook_url(out),
                )
                return out
            logger.info(
                "dingtalk _load_session_webhook miss: webhook_key=%s",
                webhook_key,
            )
            return None

    # ---------------------------
    # Reply via stream thread
    # ---------------------------

    def _reply_sync(self, meta: Dict[str, Any], text: str) -> None:
        """Resolve reply_future on the stream thread's loop so process()
        can continue and reply.
        """
        reply_loop = meta.get("reply_loop")
        reply_future = meta.get("reply_future")
        if reply_loop is None or reply_future is None:
            return
        reply_loop.call_soon_threadsafe(reply_future.set_result, text)

    def _reply_sync_batch(self, meta: Dict[str, Any], text: str) -> None:
        """
        Resolve all reply_futures (merged batch) so every waiter unblocks.
        """
        lst = meta.get("_reply_futures_list") or []
        if lst:
            for reply_loop, reply_future in lst:
                if reply_loop and reply_future:
                    reply_loop.call_soon_threadsafe(
                        reply_future.set_result,
                        text,
                    )
        else:
            self._reply_sync(meta, text)

    def _get_session_webhook(
        self,
        meta: Optional[Dict[str, Any]],
    ) -> Optional[str]:
        """Get sessionWebhook from meta (persisted) or incoming_message."""
        if not meta:
            return None
        out = meta.get("session_webhook") or meta.get("sessionWebhook")
        if out:
            return out
        inc = meta.get("incoming_message")
        if inc is None:
            return None
        return getattr(inc, "sessionWebhook", None) or getattr(
            inc,
            "session_webhook",
            None,
        )

    def _parts_to_single_text(
        self,
        parts: List[OutgoingContentPart],
        bot_prefix: str = "",
    ) -> str:
        """Build one reply text from parts
        (same logic as send_content_parts body).
        """
        text_parts: List[str] = []
        for p in parts:
            t = getattr(p, "type", None)
            if t == ContentType.TEXT and getattr(p, "text", None):
                text_parts.append(p.text or "")
            elif t == ContentType.REFUSAL and getattr(p, "refusal", None):
                text_parts.append(p.refusal or "")
            elif t == ContentType.IMAGE and getattr(p, "image_url", None):
                text_parts.append(f"[Image: {p.image_url}]")
            elif t == ContentType.VIDEO and getattr(p, "video_url", None):
                text_parts.append(f"[Video: {p.video_url}]")
            elif t == ContentType.FILE and (
                getattr(p, "file_url", None) or getattr(p, "file_id", None)
            ):
                url_or_id = getattr(p, "file_url", None) or getattr(
                    p,
                    "file_id",
                    None,
                )
                text_parts.append(f"[File: {url_or_id}]")
            elif t == ContentType.AUDIO and getattr(p, "data", None):
                text_parts.append("[Audio]")
        body = "\n".join(text_parts) if text_parts else ""
        if bot_prefix and body:
            body = bot_prefix + body
        return body

    async def _send_payload_via_session_webhook(
        self,
        session_webhook: str,
        payload: Dict[str, Any],
    ) -> bool:
        """Send one message via DingTalk sessionWebhook with given JSON
        payload (e.g. msgtype text, markdown, image, file). Returns True
        on success.
        """
        msgtype = payload.get("msgtype", "?")
        session_in_url = session_param_from_webhook_url(session_webhook)
        wh = (
            session_webhook[:60] + "..."
            if len(session_webhook) > 60
            else session_webhook
        )
        logger.info(
            "dingtalk sessionWebhook send: msgtype=%s webhook_host=%s "
            "session_from_url=%s",
            msgtype,
            wh,
            session_in_url,
        )
        logger.debug("dingtalk sessionWebhook send: payload=%s", payload)
        try:
            async with self._http.post(
                session_webhook,
                json=payload,
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                },
            ) as resp:
                body_text = await resp.text()
                if resp.status >= 400:
                    logger.warning(
                        "dingtalk sessionWebhook POST failed: msgtype=%s "
                        "status=%s body=%s",
                        msgtype,
                        resp.status,
                        body_text[:500],
                    )
                    return False
                try:
                    body_json = json.loads(body_text) if body_text else {}
                except json.JSONDecodeError:
                    body_json = {}
                errcode = body_json.get("errcode", 0)
                errmsg = body_json.get("errmsg", "")
                if errcode != 0:
                    logger.warning(
                        "dingtalk sessionWebhook POST API error: msgtype=%s "
                        "session_from_url=%s errcode=%s errmsg=%s body=%s",
                        msgtype,
                        session_in_url,
                        errcode,
                        errmsg,
                        body_text[:300],
                    )
                    return False
                logger.info(
                    "dingtalk sessionWebhook POST ok: msgtype=%s status=%s "
                    "errcode=%s",
                    msgtype,
                    resp.status,
                    errcode,
                )
                return True
        except Exception:
            logger.exception(
                f"dingtalk sessionWebhook POST failed: msgtype={msgtype}",
            )
            return False

    async def _send_via_session_webhook(
        self,
        session_webhook: str,
        body: str,
        bot_prefix: str = "",
    ) -> bool:
        """Send one text message via DingTalk sessionWebhook. Returns True
        on success."""
        text = (bot_prefix + body) if body else bot_prefix
        if len(text) > 3500:
            payload = {"msgtype": "text", "text": {"content": text}}
        else:
            norm = dingtalk_markdown.normalize_dingtalk_markdown(text)
            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "title": f"💬{norm[:10]}...",
                    "text": norm,
                },
            }
        return await self._send_payload_via_session_webhook(
            session_webhook,
            payload,
        )

    async def _upload_media(
        self,
        data: bytes,
        media_type: str,
        filename: Optional[str] = None,
        content_type: Optional[str] = None,
    ) -> Optional[str]:
        """Upload media via DingTalk Open API and return media_id."""
        logger.info(
            "dingtalk upload_media: type=%s size=%s filename=%s",
            media_type,
            len(data),
            filename or "(none)",
        )
        token = await self._get_access_token()
        # Use oapi media upload (api.dingtalk.com upload returns 404).
        # Doc:
        # https://open.dingtalk.com/document/development/upload-media-files
        url = (
            "https://oapi.dingtalk.com/media/upload"
            f"?access_token={token}&type={media_type}"
        )
        ext = "jpg" if media_type == "image" else "bin"
        name = filename or f"upload.{ext}"
        logger.info(f"dingtalk upload_media: name={name}")
        form = aiohttp.FormData()
        form.add_field(
            "media",
            data,
            filename=name,
            content_type=content_type
            or mimetypes.guess_type(name)[0]
            or "application/octet-stream",
        )
        try:
            async with self._http.post(url, data=form) as resp:
                result = await resp.json(content_type=None)
                if resp.status >= 400:
                    logger.warning(
                        "dingtalk upload_media failed: type=%s status=%s "
                        "body=%s",
                        media_type,
                        resp.status,
                        result,
                    )
                    return None
                errcode = result.get("errcode", 0)
                if errcode != 0:
                    logger.warning(
                        "dingtalk upload_media oapi err: type=%s errcode=%s",
                        media_type,
                        errcode,
                    )
                    return None
                media_id = (
                    result.get("media_id")
                    or result.get("mediaId")
                    or (result.get("result") or {}).get("media_id")
                    or (result.get("result") or {}).get("mediaId")
                )
                if media_id:
                    mid_preview = (
                        media_id[:32] + "..."
                        if len(media_id) > 32
                        else media_id
                    )
                    logger.info(
                        "dingtalk upload_media ok: type=%s media_id=%s",
                        media_type,
                        mid_preview,
                    )
                else:
                    logger.warning(
                        "dingtalk upload_media: no media_id in response",
                    )
                return media_id
        except Exception:
            logger.exception(
                "dingtalk upload_media failed: type=%s filename=%s",
                media_type,
                filename,
            )
            return None

    async def _fetch_bytes_from_url(self, url: str) -> Optional[bytes]:
        """Download binary content from URL. Returns None on failure.

        Supports http(s):// and file:// URLs. file:// is read from local disk.
        """
        logger.info(
            "dingtalk fetch_bytes_from_url: url=%s",
            url[:80] + "..." if len(url) > 80 else url,
        )
        try:
            path = file_url_to_local_path(url)
            if path is not None:
                data = await asyncio.to_thread(Path(path).read_bytes)
                logger.info(
                    "dingtalk fetch_bytes_from_url ok: size=%s (file)",
                    len(data),
                )
                return data
            if url.strip().lower().startswith("file:"):
                logger.warning(
                    f"dingtalk fetch_bytes_from_url: empty file path for "
                    f"url={url[:80]}",
                )
                return None
            async with self._http.get(url) as resp:
                if resp.status >= 400:
                    logger.warning(
                        "dingtalk fetch_bytes_from_url failed: status=%s",
                        resp.status,
                    )
                    return None
                data = await resp.read()
                logger.info(
                    "dingtalk fetch_bytes_from_url ok: size=%s",
                    len(data),
                )
                return data
        except Exception:
            logger.exception(
                "dingtalk fetch_bytes_from_url failed: url=%s",
                url[:80],
            )
            return None

    async def _get_session_webhook_for_send(
        self,
        to_handle: str,
        meta: Optional[Dict[str, Any]],
    ) -> Optional[str]:
        """Resolve session_webhook for sending (from meta or to_handle)."""
        m = meta or {}
        webhook = m.get("session_webhook") or m.get("sessionWebhook")
        if webhook:
            logger.info(
                "dingtalk _get_session_webhook_for_send: to_handle=%s "
                "source=meta session_from_url=%s",
                to_handle[:40] if to_handle else "",
                session_param_from_webhook_url(webhook),
            )
            return webhook
        route = self._route_from_handle(to_handle)
        webhook = route.get("session_webhook")
        if webhook:
            logger.info(
                "dingtalk _get_session_webhook_for_send: to_handle=%s "
                "source=route session_from_url=%s",
                to_handle[:40] if to_handle else "",
                session_param_from_webhook_url(webhook),
            )
            return webhook
        key = route.get("webhook_key")
        if key:
            webhook = await self._load_session_webhook(key)
            if webhook:
                logger.info(
                    "dingtalk _get_session_webhook_for_send: to_handle=%s "
                    "source=store webhook_key=%s",
                    to_handle[:40] if to_handle else "",
                    key,
                )
            return webhook
        logger.info(
            "dingtalk _get_session_webhook_for_send: to_handle=%s source=none",
            to_handle[:40] if to_handle else "",
        )
        return None

    def _map_upload_type(self, part: OutgoingContentPart) -> Optional[str]:
        """
        Map OutgoingContentPart type to DingTalk media/upload type.
        DingTalk upload type must be one of: image | voice | video | file
        """
        ptype = getattr(part, "type", None)
        if ptype in (ContentType.TEXT, ContentType.REFUSAL, None):
            return None  # no upload
        if ptype == ContentType.IMAGE:
            return "image"
        if ptype == ContentType.AUDIO:
            return "voice"
        if ptype == ContentType.VIDEO:
            return "video"
        if ptype == ContentType.FILE:
            return "file"
        return "file"

    async def _send_media_part_via_webhook(
        self,
        session_webhook: str,
        part: OutgoingContentPart,
    ) -> bool:
        """Upload and send one media part via session webhook."""
        ptype = getattr(part, "type", None)
        upload_type = self._map_upload_type(part)

        logger.info(
            "dingtalk _send_media_part_via_webhook: type=%s upload_type=%s",
            ptype,
            upload_type,
        )

        # text/auto/refusal: no-op here (text is handled elsewhere)
        if upload_type is None:
            return True

        # ---------- image special-case: if public picURL, send directly ------
        if upload_type == "image":
            url = getattr(part, "image_url", None) or ""
            url = (url or "").strip() if isinstance(url, str) else ""
            if self._is_public_http_url(url):
                payload = {"msgtype": "image", "image": {"picURL": url}}
                return await self._send_payload_via_session_webhook(
                    session_webhook,
                    payload,
                )
            # else: fallthrough to upload-by-bytes then send as file
            # (your existing fallback)

        # ---------- decide filename/ext ----------
        default_name = {
            "image": "image.png",
            "voice": "audio.amr",
            "video": "video.mp4",
            "file": "file.bin",
        }.get(upload_type, "file.bin")
        filename, ext = self._guess_filename_and_ext(
            part,
            default=default_name,
        )

        # ---------- if already has media id ----------
        # for file you used file_id;
        # keep compatibility but also accept media_id
        media_id = (
            getattr(part, "media_id", None)
            or getattr(part, "mediaId", None)
            or getattr(part, "file_id", None)
        )
        if media_id:
            media_id = str(media_id).strip()
            if not media_id:
                return False

            if upload_type == "image":
                # sendBySession supports image by picURL;
                # but if we only have mediaId, send as file
                payload = {
                    "msgtype": "file",
                    "file": {
                        "mediaId": media_id,
                        "fileType": ext,
                        "fileName": filename,
                    },
                }
                return await self._send_payload_via_session_webhook(
                    session_webhook,
                    payload,
                )

            if upload_type == "voice":
                payload = {"msgtype": "voice", "voice": {"mediaId": media_id}}
                return await self._send_payload_via_session_webhook(
                    session_webhook,
                    payload,
                )

            if upload_type == "video":
                pic_media_id = (
                    getattr(part, "pic_media_id", None)
                    or getattr(part, "picMediaId", None)
                    or ""
                )
                pic_media_id = (pic_media_id or "").strip()
                if pic_media_id:
                    duration = getattr(part, "duration", None)
                    if duration is None:
                        duration = 1
                    payload = {
                        "msgtype": "video",
                        "video": {
                            "videoMediaId": media_id,
                            "duration": str(int(duration)),
                            "picMediaId": pic_media_id,
                        },
                    }
                    return await self._send_payload_via_session_webhook(
                        session_webhook,
                        payload,
                    )
                # No picMediaId: send as file so user still gets the video
                payload = {
                    "msgtype": "file",
                    "file": {
                        "mediaId": media_id,
                        "fileType": ext,
                        "fileName": filename,
                    },
                }
                return await self._send_payload_via_session_webhook(
                    session_webhook,
                    payload,
                )

            # file
            payload = {
                "msgtype": "file",
                "file": {
                    "mediaId": media_id,
                    "fileType": ext,
                    "fileName": filename,
                },
            }
            return await self._send_payload_via_session_webhook(
                session_webhook,
                payload,
            )

        # ---------- load bytes from base64 or url ----------
        data: Optional[bytes] = None
        url = (
            getattr(part, "file_url", None)
            or getattr(part, "image_url", None)
            or getattr(part, "video_url", None)
            or ""
        )
        url = (url or "").strip() if isinstance(url, str) else ""
        raw_b64 = None
        if (
            isinstance(url, str)
            and url.startswith("data:")
            and "base64," in url
        ):
            raw_b64 = url
            url = ""
        if not raw_b64:
            raw_b64 = getattr(part, "base64", None)

        if raw_b64:
            if isinstance(raw_b64, str) and raw_b64.startswith("data:"):
                data, mime = parse_data_url(raw_b64)
                content_type_for_upload = (
                    mime or getattr(part, "mime_type", None) or ""
                ).strip()
                if mime and not getattr(part, "filename", None):
                    ext_guess = (mimetypes.guess_extension(mime) or "").lstrip(
                        ".",
                    ) or ""
                    if ext_guess:
                        filename = f"upload.{ext_guess}"
                        ext = ext_guess
            else:
                data = base64.b64decode(raw_b64, validate=False)
                content_type_for_upload = (
                    getattr(part, "mime_type", None) or ""
                ).strip()
        else:
            content_type_for_upload = (
                getattr(part, "mime_type", None) or ""
            ).strip()
        if not data and url:
            data = await self._fetch_bytes_from_url(url)

        if not data:
            logger.warning(
                "dingtalk media part: no data to upload, type=%s",
                ptype,
            )
            return False

        # ---------- upload ----------
        media_id = await self._upload_media(
            data,
            upload_type,  # image | voice | video | file
            filename=filename,
            content_type=content_type_for_upload or None,
        )
        if not media_id:
            return False

        # ---------- send ----------
        if upload_type == "image":
            # no public url -> safest is send as file (your current behavior)
            payload = {
                "msgtype": "file",
                "file": {
                    "mediaId": media_id,
                    "fileType": ext,
                    "fileName": filename,
                },
            }
            return await self._send_payload_via_session_webhook(
                session_webhook,
                payload,
            )

        if upload_type == "voice":
            payload = {"msgtype": "voice", "voice": {"mediaId": media_id}}
            return await self._send_payload_via_session_webhook(
                session_webhook,
                payload,
            )

        if upload_type == "video":
            pic_media_id = (
                part.get("pic_media_id") or part.get("picMediaId") or ""
            ).strip()
            if pic_media_id:
                duration = part.get("duration")
                if duration is None:
                    duration = 1
                payload = {
                    "msgtype": "video",
                    "video": {
                        "videoMediaId": media_id,
                        "duration": str(int(duration)),
                        "picMediaId": pic_media_id,
                    },
                }
                return await self._send_payload_via_session_webhook(
                    session_webhook,
                    payload,
                )
            # No picMediaId: send as file so user still gets the video
            payload = {
                "msgtype": "file",
                "file": {
                    "mediaId": media_id,
                    "fileType": ext,
                    "fileName": filename,
                },
            }
            return await self._send_payload_via_session_webhook(
                session_webhook,
                payload,
            )

        payload = {
            "msgtype": "file",
            "file": {
                "mediaId": media_id,
                "fileType": ext,
                "fileName": filename,
            },
        }
        return await self._send_payload_via_session_webhook(
            session_webhook,
            payload,
        )

    async def send_content_parts(
        self,
        to_handle: str,
        parts: List[OutgoingContentPart],
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Build one body from parts. If meta has reply_future (reply path),
        deliver via _reply_sync; otherwise proactive send via send().
        When session_webhook is available, sends text then image/file
        messages (upload media first for image/file).
        """
        text_parts = []
        media_parts: List[OutgoingContentPart] = []
        for p in parts:
            t = getattr(p, "type", None)
            if t == ContentType.TEXT and getattr(p, "text", None):
                text_parts.append(p.text or "")
            elif t == ContentType.REFUSAL and getattr(p, "refusal", None):
                text_parts.append(p.refusal or "")
            elif t == ContentType.IMAGE:
                media_parts.append(p)
            elif t == ContentType.FILE:
                media_parts.append(p)
            elif t == ContentType.VIDEO:
                media_parts.append(p)
            elif t == ContentType.AUDIO:
                media_parts.append(p)
        body = "\n".join(text_parts) if text_parts else ""
        prefix = (meta or {}).get("bot_prefix", "") or ""
        if prefix and body:
            body = prefix + body
        elif prefix and not body and not media_parts:
            body = prefix
        m = meta or {}
        session_webhook = await self._get_session_webhook_for_send(
            to_handle,
            meta,
        )
        logger.info(
            "dingtalk send_content_parts: to_handle=%s has_webhook=%s "
            "text_parts=%s media_parts=%s",
            to_handle[:40] if to_handle else "",
            bool(session_webhook),
            len(text_parts),
            len(media_parts),
        )
        if session_webhook and (body.strip() or media_parts):
            if body.strip():
                logger.info("dingtalk send_content_parts: sending text body")
                await self._send_via_session_webhook(
                    session_webhook,
                    body.strip(),
                    bot_prefix="",
                )
            for i, part in enumerate(media_parts):
                logger.info(
                    "dingtalk send_content_parts: "
                    "sending media part %s/%s type=%s",
                    i + 1,
                    len(media_parts),
                    getattr(part, "type", None),
                )
                ok = await self._send_media_part_via_webhook(
                    session_webhook,
                    part,
                )
                logger.info(
                    "dingtalk send_content_parts: media part %s result=%s",
                    i + 1,
                    ok,
                )
            if m.get("reply_loop") is not None and m.get("reply_future"):
                self._reply_sync(m, SENT_VIA_WEBHOOK)
            return
        if not body and media_parts:
            for p in media_parts:
                if getattr(p, "type", None) == ContentType.IMAGE and getattr(
                    p,
                    "image_url",
                    None,
                ):
                    text_parts.append(f"[Image: {p.image_url}]")
                elif getattr(p, "type", None) == ContentType.FILE and (
                    getattr(p, "file_url", None) or getattr(p, "file_id", None)
                ):
                    furl = getattr(p, "file_url", None)
                    fid = getattr(p, "file_id", None)
                    url_or_id = furl or fid
                    text_parts.append(f"[File: {url_or_id}]")
            body = "\n".join(text_parts) if text_parts else ""
            if prefix and body:
                body = prefix + body
        if (
            m.get("reply_loop") is not None
            and m.get("reply_future") is not None
        ):
            self._reply_sync(m, body)
        else:
            await self.send(to_handle, body.strip() or prefix, meta)

    def get_debounce_key(self, payload: Any) -> str:
        """Use short conversation_id or channel:sender for time debounce."""
        return self._debounce_key(payload)

    def merge_native_items(self, items: List[Any]) -> Any:
        """Merge payloads (content_parts + meta) for DingTalk."""
        return self._merge_native(items)

    def _on_debounce_buffer_append(
        self,
        key: str,
        payload: Any,
        existing_items: List[Any],
    ) -> None:
        """Unblock previous reply_future so stream callback does not block."""
        del key
        del payload
        if not existing_items:
            return
        prev = existing_items[-1]
        pm = prev.get("meta") or {} if isinstance(prev, dict) else {}
        if (
            pm.get("reply_loop") is not None
            and pm.get("reply_future") is not None
        ):
            self._reply_sync(pm, SENT_VIA_WEBHOOK)

    async def _run_process_loop(
        self,
        request: Any,
        to_handle: str,
        send_meta: Dict[str, Any],
    ) -> None:
        """Use webhook multi-message send instead of default loop."""
        del to_handle
        logger.info(
            "dingtalk _run_process_loop: send_meta has_sw=%s "
            "req.channel_meta has_sw=%s",
            bool((send_meta or {}).get("session_webhook")),
            bool(
                (getattr(request, "channel_meta", None) or {}).get(
                    "session_webhook",
                ),
            ),
        )
        # Keep only JSON-serializable keys on request for tracing; pass full
        # send_meta as reply_meta for _reply_sync_batch / send_content_parts.
        _NON_SERIALIZABLE = (
            "incoming_message",
            "reply_loop",
            "reply_future",
            "_reply_futures_list",
        )
        safe_meta = {
            k: v
            for k, v in (send_meta or {}).items()
            if k not in _NON_SERIALIZABLE
        }
        request.channel_meta = safe_meta
        logger.info(
            "dingtalk _run_process_loop: after set channel_meta has_sw=%s",
            bool((request.channel_meta or {}).get("session_webhook")),
        )
        await self._process_one_request(request, reply_meta=send_meta)

    async def _process_one_request(
        self,
        request: Any,
        reply_meta: Optional[Dict[str, Any]] = None,
    ) -> None:  # pylint: disable=too-many-branches
        meta = getattr(request, "channel_meta", None) or {}
        reply_meta = reply_meta or meta
        session_webhook = self._get_session_webhook(meta)
        use_multi = bool(session_webhook)
        logger.info(
            "dingtalk _process_one_request: meta has_sw=%s use_multi=%s",
            bool(meta.get("session_webhook")),
            use_multi,
        )
        last_response = None
        accumulated_parts: list = []
        event_count = 0

        # Store sessionWebhook (keyed by conversation).
        if session_webhook:
            fallback_sid = f"{self.channel}:{request.user_id}"
            webhook_key = self.to_handle_from_target(
                user_id=request.user_id or "",
                session_id=request.session_id or fallback_sid,
            )
            logger.info(
                "dingtalk _process_one_request: storing webhook "
                "session_id=%s conversation_id=%s webhook_key=%s",
                getattr(request, "session_id", None),
                meta.get("conversation_id"),
                webhook_key,
            )
            await self._save_session_webhook(
                webhook_key,
                session_webhook,
            )

        async for event in self._process(request):
            event_count += 1
            obj = getattr(event, "object", None)
            status = getattr(event, "status", None)
            ev_type = getattr(event, "type", None)
            logger.debug(
                "dingtalk event #%s: object=%s status=%s type=%s",
                event_count,
                obj,
                status,
                ev_type,
            )
            if obj == "message" and status == RunStatus.Completed:
                parts = self._message_to_content_parts(event)
                logger.info(
                    f"dingtalk completed message: type={ev_type} "
                    f"parts_count={len(parts)}",
                )
                if use_multi and parts and session_webhook:
                    body = self._parts_to_single_text(
                        parts,
                        bot_prefix="",
                    )
                    if body.strip():
                        await self._send_via_session_webhook(
                            session_webhook,
                            body.strip(),
                            bot_prefix="",
                        )
                    _media_types = (
                        ContentType.IMAGE,
                        ContentType.FILE,
                        ContentType.VIDEO,
                        ContentType.AUDIO,
                    )
                    media_count = sum(
                        1
                        for p in parts
                        if getattr(p, "type", None) in _media_types
                    )
                    if media_count:
                        logger.info(
                            "dingtalk consume_loop: "
                            "sending %s media "
                            "parts via webhook",
                            media_count,
                        )
                    for part in parts:
                        if getattr(part, "type", None) in _media_types:
                            ok = await self._send_media_part_via_webhook(
                                session_webhook,
                                part,
                            )
                            logger.info(
                                "dingtalk consume_loop: media part "
                                "type=%s result=%s",
                                getattr(part, "type", None),
                                ok,
                            )
                else:
                    accumulated_parts.extend(parts)
            elif obj == "response":
                last_response = event

        logger.info(
            "dingtalk stream done: event_count=%s parts=%s webhook=%s",
            event_count,
            len(accumulated_parts),
            use_multi,
        )

        if last_response and getattr(last_response, "error", None):
            err = getattr(
                last_response.error,
                "message",
                str(last_response.error),
            )
            err_text = self.bot_prefix + f"Error: {err}"
            if use_multi and session_webhook:
                await self._send_via_session_webhook(
                    session_webhook,
                    err_text,
                    bot_prefix="",
                )
            self._reply_sync_batch(
                reply_meta,
                SENT_VIA_WEBHOOK if use_multi else err_text,
            )
        elif use_multi:
            self._reply_sync_batch(reply_meta, SENT_VIA_WEBHOOK)
        elif accumulated_parts:
            sid = getattr(request, "session_id", "") or ""
            to_handle = (
                self.to_handle_from_target(
                    user_id=request.user_id or "",
                    session_id=sid,
                )
                if sid
                else (request.user_id or "")
            )
            await self.send_content_parts(
                to_handle,
                accumulated_parts,
                reply_meta,
            )
        elif last_response is None:
            self._reply_sync_batch(
                reply_meta,
                self.bot_prefix
                + "An error occurred while processing your request.",
            )

        if self._on_reply_sent:
            self._on_reply_sent(
                self.channel,
                request.user_id or "",
                request.session_id or f"{self.channel}:{request.user_id}",
            )

    def _debounce_key(self, native: Any) -> str:
        payload = native if isinstance(native, dict) else {}
        meta = payload.get("meta") or {}
        cid = meta.get("conversation_id") or ""
        if cid:
            return short_session_id_from_conversation_id(str(cid))
        return f"{self.channel}:{payload.get('sender_id', '')}"

    def _merge_native(self, items: list) -> dict:
        """Merge multiple native payloads into one (content_parts + meta)."""
        if not items:
            return {}
        first = items[0] if isinstance(items[0], dict) else {}
        merged_parts: List[Any] = []
        merged_meta: Dict[str, Any] = dict(first.get("meta") or {})

        reply_futures_list: List[tuple] = []
        for it in items:
            payload = it if isinstance(it, dict) else {}
            merged_parts.extend(payload.get("content_parts") or [])
            m = payload.get("meta") or {}
            for k in (
                "reply_future",
                "reply_loop",
                "incoming_message",
                "conversation_id",
                "session_webhook",
            ):
                if k in m:
                    merged_meta[k] = m[k]
            if m.get("reply_loop") and m.get("reply_future"):
                reply_futures_list.append((m["reply_loop"], m["reply_future"]))

        merged_meta["batched_count"] = len(items)
        merged_meta["_reply_futures_list"] = reply_futures_list
        # Queue is FIFO: batch = [oldest, ..., newest]. Prefer
        # session_webhook from newest (last item) so send uses current
        # session.
        out_sw: Optional[str] = None
        for it in reversed(items):
            pl = it if isinstance(it, dict) else {}
            sw = pl.get("session_webhook") or (pl.get("meta") or {}).get(
                "session_webhook",
            )
            if sw:
                out_sw = sw
                break
        out = {
            "channel_id": first.get("channel_id") or self.channel,
            "sender_id": first.get("sender_id") or "",
            "content_parts": merged_parts,
            "meta": merged_meta,
        }
        if out_sw:
            out["session_webhook"] = out_sw
            merged_meta["session_webhook"] = out_sw
        return out

    def _run_stream_forever(self) -> None:
        """Run stream loop; on _stop_event close websocket and exit cleanly."""
        logger.info(
            "dingtalk stream thread started (client_id=%s)",
            self.client_id,
        )
        try:
            if self._client:
                asyncio.run(self._stream_loop())
        except Exception:
            logger.exception("dingtalk stream thread failed")
        finally:
            self._stop_event.set()
            logger.info("dingtalk stream thread stopped")

    async def _stream_loop(self) -> None:
        """
        Drive DingTalkStreamClient.start() and stop when _stop_event is set.
        Closes client.websocket and cancels tasks to avoid "Task was destroyed
        but it is pending" on process exit.
        """
        client = self._client
        if not client:
            return
        main_task = asyncio.create_task(client.start())

        async def stop_watcher() -> None:
            while not self._stop_event.is_set():
                await asyncio.sleep(0.5)
            if client.websocket is not None:
                try:
                    await client.websocket.close()
                except Exception:
                    pass
            await asyncio.sleep(0.2)
            if not main_task.done():
                main_task.cancel()

        watcher_task = asyncio.create_task(stop_watcher())
        try:
            await main_task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("dingtalk stream start() failed")
        watcher_task.cancel()
        try:
            await watcher_task
        except asyncio.CancelledError:
            pass
        # Cancel remaining tasks (e.g. background_task) so loop exits cleanly
        loop = asyncio.get_running_loop()
        pending = [
            t
            for t in asyncio.all_tasks(loop)
            if t is not asyncio.current_task() and not t.done()
        ]
        for t in pending:
            t.cancel()
        if pending:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*pending, return_exceptions=True),
                    timeout=4.0,
                )
            except asyncio.TimeoutError:
                pass

    async def start(self) -> None:
        if not self.enabled:
            logger.debug("disabled by env DINGTALK_CHANNEL_ENABLED=0")
            return
        self._load_session_webhook_store_from_disk()
        if not self.client_id or not self.client_secret:
            raise RuntimeError(
                "DINGTALK_CLIENT_ID and DINGTALK_CLIENT_SECRET are required "
                "when channel is enabled.",
            )

        self._loop = asyncio.get_running_loop()

        credential = dingtalk_stream.Credential(
            self.client_id,
            self.client_secret,
        )
        self._client = dingtalk_stream.DingTalkStreamClient(credential)
        enqueue_cb = getattr(self, "_enqueue", None)
        internal_handler = DingTalkChannelHandler(
            main_loop=self._loop,
            enqueue_callback=enqueue_cb,
            bot_prefix=self.bot_prefix,
            download_url_fetcher=self._fetch_and_download_media,
        )
        self._client.register_callback_handler(
            ChatbotMessage.TOPIC,
            internal_handler,
        )

        self._stop_event.clear()
        self._stream_thread = threading.Thread(
            target=self._run_stream_forever,
            daemon=True,
        )
        self._stream_thread.start()
        if self._http is None:
            self._http = aiohttp.ClientSession()

    async def stop(self) -> None:
        if not self.enabled:
            return
        self._stop_event.set()
        if self._stream_thread:
            self._stream_thread.join(timeout=3)
        for task in self._debounce_timers.values():
            if task and not task.done():
                task.cancel()
        if self._debounce_timers:
            await asyncio.gather(
                *self._debounce_timers.values(),
                return_exceptions=True,
            )
        self._debounce_timers.clear()
        self._debounce_pending.clear()
        if self._http is not None:
            await self._http.close()
            self._http = None
        self._client = None

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Proactive send for DingTalk via stored sessionWebhook.

        Supports:
        1) meta["session_webhook"] or meta["sessionWebhook"]: direct url
        2) to_handle: dingtalk:sw:<sender> (stored) or http(s) url
        If no webhook is found, logs warning and returns (no 500).
        """
        if not self.enabled:
            return
        if self._http is None:
            return

        meta = meta or {}

        # direct webhook provided in meta
        session_webhook = meta.get("session_webhook") or meta.get(
            "sessionWebhook",
        )

        if not session_webhook:
            route = self._route_from_handle(to_handle)
            session_webhook = route.get("session_webhook")
            if not session_webhook:
                webhook_key = route.get("webhook_key")
                if webhook_key:
                    session_webhook = await self._load_session_webhook(
                        webhook_key,
                    )

        if not session_webhook:
            logger.warning(
                "DingTalkChannel.send: no sessionWebhook for to_handle=%s. "
                "User must have chatted with the bot first, or pass "
                "meta['session_webhook']. Skip sending.",
                to_handle,
            )
            return

        logger.info(
            "DingTalkChannel.send to_handle=%s len=%s",
            to_handle,
            len(text),
        )

        # Caller (send_content_parts) already prepends bot_prefix to text.
        await self._send_via_session_webhook(
            session_webhook,
            text,
            bot_prefix="",
        )

    async def _get_access_token(self) -> str:
        """Get and cache DingTalk accessToken for 1 hour (instance-level)."""
        if not self.client_id or not self.client_secret:
            raise RuntimeError("DingTalk client_id/client_secret missing")

        now = asyncio.get_running_loop().time()
        if self._token_value and now < self._token_expires_at:
            return self._token_value

        async with self._token_lock:
            now = asyncio.get_running_loop().time()
            if self._token_value and now < self._token_expires_at:
                return self._token_value

            url = "https://api.dingtalk.com/v1.0/oauth2/accessToken"
            payload = {
                "appKey": self.client_id,
                "appSecret": self.client_secret,
            }

            async with self._http.post(url, json=payload) as resp:
                data = await resp.json(content_type=None)
                if resp.status >= 400:
                    raise RuntimeError(
                        f"get accessToken failed status={resp.status} "
                        f"body={data}",
                    )

            token = data.get("accessToken") or data.get("access_token")
            if not token:
                raise RuntimeError(
                    f"accessToken not found in response: {data}",
                )

            self._token_value = token
            self._token_expires_at = (
                asyncio.get_running_loop().time() + DINGTALK_TOKEN_TTL_SECONDS
            )
            return token

    async def _get_message_file_download_url(
        self,
        *,
        download_code: str,
        robot_code: str,
    ) -> Optional[str]:
        """Call DingTalk messageFiles/download to get a downloadable URL."""
        if not download_code or not robot_code:
            return None
        if self._http is None:
            return None

        token = await self._get_access_token()
        url = "https://api.dingtalk.com/v1.0/robot/messageFiles/download"
        payload = {"downloadCode": download_code, "robotCode": robot_code}
        headers = {
            "Content-Type": "application/json",
            "x-acs-dingtalk-access-token": token,
        }

        async with self._http.post(
            url,
            json=payload,
            headers=headers,
        ) as resp:
            data = await resp.json(content_type=None)
            if resp.status >= 400:
                logger.warning(
                    "messageFiles/download failed status=%s body=%s",
                    resp.status,
                    data,
                )
                return None

        logger.debug("messageFiles/download response=%s", data)
        return (
            data.get("downloadUrl")
            or data.get("url")
            or (data.get("result") or {}).get("downloadUrl")
            or (data.get("result") or {}).get("url")
        )

    async def _download_media_to_local(
        self,
        url: str,
        safe_key: str,
        filename_hint: str = "file.bin",
    ) -> Optional[str]:
        """Download media to media_dir; return local path or None.
        Suffix from Content-Type then magic bytes.
        """
        if not url or not url.strip().startswith(("http://", "https://")):
            return None
        if self._http is None:
            return None
        try:
            async with self._http.get(url) as resp:
                if resp.status >= 400:
                    logger.warning(
                        "dingtalk media download failed status=%s",
                        resp.status,
                    )
                    return None
                data = await resp.read()
                content_type = (
                    resp.headers.get("Content-Type", "").split(";")[0].strip()
                )
                disposition = resp.headers.get(
                    "Content-Disposition",
                    "",
                )
            filename = filename_hint
            if "filename=" in disposition:
                part = (
                    disposition.split("filename=", 1)[-1].strip().strip("'\"")
                )
                if part:
                    filename = part
            suffix = ".file"
            if "." in filename:
                ext = filename.rsplit(".", 1)[-1].lower().strip()
                if ext:
                    suffix = "." + ext
            elif content_type:
                suffix = mimetypes.guess_extension(content_type) or ".file"
            self._media_dir.mkdir(parents=True, exist_ok=True)
            path = self._media_dir / f"{safe_key}{suffix}"
            path.write_bytes(data)
            # Fix .file/.bin with magic bytes so images get .png/.jpg etc.
            if path.suffix in (".file", ".bin"):
                real_suffix = guess_suffix_from_file_content(path)
                if real_suffix:
                    new_path = path.with_suffix(real_suffix)
                    path.rename(new_path)
                    path = new_path
                    logger.debug(
                        "dingtalk replaced suffix with %s for %s",
                        real_suffix,
                        path,
                    )
            return str(path)
        except Exception:
            logger.exception("dingtalk _download_media_to_local failed")
            return None

    async def _fetch_and_download_media(
        self,
        *,
        download_code: str,
        robot_code: str,
        filename_hint: str = "file.bin",
    ) -> Optional[str]:
        """Get download URL from API, save to local, return path."""
        url = await self._get_message_file_download_url(
            download_code=download_code,
            robot_code=robot_code,
        )
        if not url:
            return None
        key = hashlib.md5(
            (download_code + robot_code).encode(),
        ).hexdigest()[:24]
        return await self._download_media_to_local(
            url,
            key,
            filename_hint,
        )

    def _guess_filename_and_ext(
        self,
        part: OutgoingContentPart,
        default: str,
    ) -> tuple[str, str]:
        """
        Return (filename, ext) where ext has no dot.
        Tries: part.filename -> url path basename -> default
        """
        filename = (getattr(part, "filename", None) or "").strip()

        if not filename:
            url = (
                getattr(part, "file_url", None)
                or getattr(part, "image_url", None)
                or getattr(part, "video_url", None)
                or ""
            )
            url = (url or "").strip() if isinstance(url, str) else ""
            if url:
                try:
                    path = urlparse(url).path
                    base = os.path.basename(path)
                    if base:
                        filename = base
                except Exception:
                    pass

        if not filename:
            filename = default

        ext = ""
        if "." in filename:
            ext = filename.rsplit(".", 1)[-1].lower().strip()

        if not ext:
            # try from mime_type if provided
            mime = (
                getattr(part, "mime_type", None)
                or getattr(part, "content_type", None)
                or ""
            ).strip()
            if mime:
                guess = mimetypes.guess_extension(mime)  # like ".png"
                if guess:
                    ext = guess.lstrip(".").lower()

        if not ext:
            ext = (
                default.rsplit(".", 1)[-1].lower() if "." in default else "bin"
            )

        # normalize common cases
        if ext == "jpeg":
            ext = "jpg"

        return filename, ext

    def _is_public_http_url(self, s: Optional[str]) -> bool:
        if not s or not isinstance(s, str):
            return False
        s = s.strip()
        return s.startswith("http://") or s.startswith("https://")
