# -*- coding: utf-8 -*-
"""Wechat channel implementation."""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from ....config.config import WechatConfig as WechatChannelConfig
from ....constant import DEFAULT_MEDIA_DIR, WORKING_DIR
from ..base import (
    AudioContent,
    BaseChannel,
    ContentType,
    FileContent,
    ImageContent,
    OnReplySent,
    OutgoingContentPart,
    ProcessHandler,
    VideoContent,
)
from ..utils import file_url_to_local_path
from .client import (
    WechatApiClient,
    WechatApiError,
    WechatProtocolError,
    extract_inbound_aes_key,
)
from .state import WechatStateStore
from .types import (
    MESSAGE_ITEM_FILE,
    MESSAGE_ITEM_IMAGE,
    MESSAGE_ITEM_VIDEO,
    MESSAGE_ITEM_VOICE,
    MESSAGE_STATE_FINISH,
    MESSAGE_TYPE_BOT,
    MESSAGE_TYPE_USER,
    TYPING_STATUS_CANCEL,
    TYPING_STATUS_TYPING,
    UploadResult,
    build_file_item,
    build_image_item,
    build_text_item,
    build_video_item,
    media_type_for_part,
    message_item_list_to_parts,
)

logger = logging.getLogger(__name__)

_RETRY_INITIAL_S = 1.0
_RETRY_MAX_S = 20.0


def _extract_inbound_cdn_descriptor(
    item: Dict[str, Any],
) -> Optional[Tuple[str, str, Any]]:
    """Return (encrypt_query_param, filename, aes_key) for CDN download."""
    it = int(item.get("type") or 0)
    media: Dict[str, Any] = {}
    parent: Dict[str, Any] = {}
    filename = "attachment.bin"
    if it == MESSAGE_ITEM_IMAGE:
        parent = item.get("image_item") or {}
        media = parent.get("media") or {}
        filename = "image.jpg"
    elif it == MESSAGE_ITEM_VIDEO:
        parent = item.get("video_item") or {}
        media = parent.get("media") or {}
        filename = "video.mp4"
    elif it == MESSAGE_ITEM_VOICE:
        parent = item.get("voice_item") or {}
        if (parent.get("text") or "").strip():
            return None
        media = parent.get("media") or {}
        filename = "voice.bin"
    elif it == MESSAGE_ITEM_FILE:
        parent = item.get("file_item") or {}
        media = parent.get("media") or {}
        filename = parent.get("file_name") or "attachment.bin"
    else:
        return None

    query = media.get("encrypt_query_param")
    if not query:
        return None
    q = str(query).strip()
    aes_raw = extract_inbound_aes_key(parent, media, item)
    if aes_raw is None:
        logger.warning(
            "wechat inbound CDN item missing aes_key, skip type=%s name=%s",
            it,
            filename,
        )
        return None
    return (q, str(filename), aes_raw)


def _collect_inbound_cdn_query_info(
    item_list: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    query_info: Dict[str, Dict[str, Any]] = {}
    for item in item_list:
        if not isinstance(item, dict):
            continue
        desc = _extract_inbound_cdn_descriptor(item)
        if desc is None:
            continue
        q, filename, aes_raw = desc
        if q not in query_info:
            query_info[q] = {
                "aes_key": aes_raw,
                "filename": filename,
            }
    return query_info


def _cdn_part_url_for_type(part: OutgoingContentPart, pt: Any) -> str:
    if pt == ContentType.IMAGE:
        return str(getattr(part, "image_url", "") or "")
    if pt == ContentType.VIDEO:
        return str(getattr(part, "video_url", "") or "")
    if pt == ContentType.AUDIO:
        return str(getattr(part, "data", "") or "")
    if pt == ContentType.FILE:
        return str(getattr(part, "file_url", "") or "")
    return ""


def _replace_cdn_part_with_local(
    part: OutgoingContentPart,
    *,
    query_to_path: Dict[str, str],
    cdn_prefix: str,
) -> Optional[OutgoingContentPart]:
    pt = getattr(part, "type", None)
    url = _cdn_part_url_for_type(part, pt)
    if pt not in (
        ContentType.IMAGE,
        ContentType.VIDEO,
        ContentType.AUDIO,
        ContentType.FILE,
    ):
        return None
    if not url.startswith(cdn_prefix):
        return None
    q = url[len(cdn_prefix) :]
    local = query_to_path.get(q)
    if not local:
        return None

    result: Optional[OutgoingContentPart] = None
    if pt == ContentType.IMAGE:
        result = ImageContent(type=ContentType.IMAGE, image_url=local)
    elif pt == ContentType.VIDEO:
        result = VideoContent(type=ContentType.VIDEO, video_url=local)
    elif pt == ContentType.AUDIO:
        result = AudioContent(type=ContentType.AUDIO, data=local)
    elif pt == ContentType.FILE:
        result = FileContent(
            type=ContentType.FILE,
            filename=getattr(part, "filename", None) or "attachment.bin",
            file_url=local,
        )
    return result


def _rewrite_cdn_parts_with_local_paths(
    content_parts: List[OutgoingContentPart],
    query_to_path: Dict[str, str],
) -> List[OutgoingContentPart]:
    cdn_prefix = "wechat://cdn/"
    out: List[OutgoingContentPart] = []
    for part in content_parts:
        replaced = _replace_cdn_part_with_local(
            part,
            query_to_path=query_to_path,
            cdn_prefix=cdn_prefix,
        )
        if replaced is not None:
            out.append(replaced)
        else:
            out.append(part)
    return out


class WechatChannel(BaseChannel):
    """Wechat channel over OpenClaw HTTP protocol."""

    channel = "wechat"

    def __init__(
        self,
        *,
        process: ProcessHandler,
        enabled: bool,
        base_url: str,
        bot_token: str,
        uin: str = "",
        on_reply_sent: OnReplySent = None,
        bot_prefix: str = "[BOT] ",
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
        poll_timeout_ms: int = 35_000,
        request_timeout_ms: int = 15_000,
        state_dir: str = "",
        media_dir: str = "",
        cdn_base_url: str = "",
        max_send_retries: int = 3,
        typing_enabled: bool = True,
    ) -> None:
        super().__init__(
            process,
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            filter_thinking=filter_thinking,
        )
        self.enabled = enabled
        self.base_url = base_url.strip()
        self.bot_token = bot_token.strip()
        self.uin = uin.strip()
        self.bot_prefix = bot_prefix
        self.poll_timeout_ms = max(5_000, int(poll_timeout_ms))
        self.request_timeout_ms = max(1_000, int(request_timeout_ms))
        self.max_send_retries = max(1, int(max_send_retries))
        self.typing_enabled = bool(typing_enabled)
        self._cdn_base_url = (cdn_base_url or "").strip()

        default_state_dir = WORKING_DIR / "state" / "wechat"
        self._state_dir = (
            Path(state_dir).expanduser().resolve()
            if state_dir
            else default_state_dir.resolve()
        )
        self._media_dir = (
            Path(media_dir).expanduser().resolve()
            if media_dir
            else (DEFAULT_MEDIA_DIR / "wechat").resolve()
        )
        self._media_dir.mkdir(parents=True, exist_ok=True)

        self._state = WechatStateStore(self._state_dir / "state.json")
        self._client: Optional[WechatApiClient] = None
        self._poll_task: Optional[asyncio.Task[None]] = None
        self._stop_event = asyncio.Event()
        self._typing_tickets: Dict[str, str] = {}

    @classmethod
    def from_env(
        cls,
        process: ProcessHandler,
        on_reply_sent: OnReplySent = None,
    ) -> "WechatChannel":
        return cls(
            process=process,
            enabled=os.getenv("WECHAT_CHANNEL_ENABLED", "0") == "1",
            base_url=os.getenv("WECHAT_BASE_URL", ""),
            bot_token=os.getenv("WECHAT_BOT_TOKEN", ""),
            uin=os.getenv("WECHAT_UIN", ""),
            on_reply_sent=on_reply_sent,
            bot_prefix=os.getenv("WECHAT_BOT_PREFIX", "[BOT] "),
            poll_timeout_ms=int(os.getenv("WECHAT_POLL_TIMEOUT_MS", "35000")),
            request_timeout_ms=int(
                os.getenv("WECHAT_REQUEST_TIMEOUT_MS", "15000"),
            ),
            state_dir=os.getenv("WECHAT_STATE_DIR", ""),
            media_dir=os.getenv("WECHAT_MEDIA_DIR", ""),
            cdn_base_url=os.getenv("WECHAT_CDN_BASE_URL", ""),
            max_send_retries=int(os.getenv("WECHAT_MAX_SEND_RETRIES", "3")),
            typing_enabled=os.getenv("WECHAT_TYPING_ENABLED", "1") == "1",
        )

    @classmethod
    def from_config(
        cls,
        process: ProcessHandler,
        config: WechatChannelConfig,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
    ) -> "WechatChannel":
        return cls(
            process=process,
            enabled=bool(config.enabled),
            base_url=str(config.base_url or ""),
            bot_token=str(config.bot_token or ""),
            uin=str(config.uin or ""),
            on_reply_sent=on_reply_sent,
            bot_prefix=str(config.bot_prefix or "[BOT] "),
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            filter_thinking=filter_thinking,
            poll_timeout_ms=int(config.poll_timeout_ms),
            request_timeout_ms=int(config.request_timeout_ms),
            state_dir=str(config.state_dir or ""),
            media_dir=str(config.media_dir or ""),
            cdn_base_url=str(config.cdn_base_url or ""),
            max_send_retries=int(config.max_send_retries),
            typing_enabled=bool(config.typing_enabled),
        )

    def resolve_session_id(
        self,
        sender_id: str,
        channel_meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        peer_id = sender_id or "unknown"
        account = self.uin or "default"
        return f"{self.channel}:{account}:{peer_id}"

    def build_agent_request_from_native(self, native_payload: Any) -> Any:
        payload = native_payload if isinstance(native_payload, dict) else {}
        sender_id = str(payload.get("sender_id") or "")
        content_parts = payload.get("content_parts") or []
        meta = payload.get("meta") or {}
        request = self.build_agent_request_from_user_content(
            channel_id=self.channel,
            sender_id=sender_id,
            session_id=payload.get("session_id")
            or self.resolve_session_id(sender_id, meta),
            content_parts=content_parts,
            channel_meta=meta,
        )
        request.channel_meta = meta
        return request

    async def start(self) -> None:
        if not self.enabled:
            logger.debug("wechat: disabled")
            return
        if not self.base_url or not self.bot_token:
            logger.warning("wechat: missing base_url or bot_token, disabled")
            return
        await self._state.load()
        self._client = WechatApiClient(
            base_url=self.base_url,
            token=self.bot_token,
            uin=self.uin,
            timeout_ms=self.request_timeout_ms,
            long_poll_timeout_ms=self.poll_timeout_ms,
            cdn_base_url=self._cdn_base_url,
        )
        self._stop_event.clear()
        self._poll_task = asyncio.create_task(
            self._poll_loop(),
            name="wechat_poll",
        )
        logger.info("wechat: channel started")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._poll_task is not None:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None
        if self._client is not None:
            await self._client.close()
            self._client = None
        logger.info("wechat: channel stopped")

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not text.strip():
            return
        await self._send_items(
            to_user_id=to_handle,
            item_list=[build_text_item(text.strip())],
            meta=meta,
        )

    async def send_content_parts(
        self,
        to_handle: str,
        parts: List[OutgoingContentPart],
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        text_segments: List[str] = []
        item_list: List[Dict[str, Any]] = []
        for part in parts:
            part_type = getattr(part, "type", None)
            if part_type == ContentType.TEXT and getattr(part, "text", None):
                text_segments.append(part.text.strip())
                continue
            if part_type == ContentType.REFUSAL and getattr(
                part,
                "refusal",
                None,
            ):
                text_segments.append(part.refusal.strip())
                continue
            upload = await self._upload_media_part(part, to_user_id=to_handle)
            if upload is None:
                continue
            if part_type == ContentType.IMAGE:
                item_list.append(build_image_item(upload))
            elif part_type == ContentType.FILE:
                filename = getattr(part, "filename", None) or "attachment.bin"
                item_list.append(build_file_item(upload, str(filename)))
            elif part_type == ContentType.VIDEO:
                item_list.append(build_video_item(upload))

        body_text = "\n".join([s for s in text_segments if s])
        prefix = (meta or {}).get("bot_prefix", "")
        if prefix and body_text:
            body_text = f"{prefix}{body_text}"
        if body_text:
            item_list.insert(0, build_text_item(body_text))
        if not item_list:
            return
        await self._send_items(
            to_user_id=to_handle,
            item_list=item_list,
            meta=meta,
        )

    async def _materialize_inbound_cdn_media(
        self,
        item_list: List[Dict[str, Any]],
        content_parts: List[OutgoingContentPart],
    ) -> List[OutgoingContentPart]:
        """Download wechat://cdn media; replace parts with local paths."""
        if self._client is None:
            return content_parts

        query_info = _collect_inbound_cdn_query_info(item_list)
        if not query_info:
            return content_parts

        inbound_dir = self._media_dir / "inbound"
        inbound_dir.mkdir(parents=True, exist_ok=True)

        query_to_path: Dict[str, str] = {}
        for q, info in query_info.items():
            try:
                raw = await self._client.download_cdn_file(
                    encrypted_query_param=q,
                    aes_key_b64_or_hex=info["aes_key"],
                )
            except (
                WechatApiError,
                WechatProtocolError,
                httpx.HTTPError,
                ValueError,
            ) as exc:
                logger.error("wechat inbound CDN download failed: %s", exc)
                continue
            safe_name = Path(info["filename"]).name or "attachment.bin"
            local_path = inbound_dir / f"{uuid.uuid4().hex}_{safe_name}"
            local_path.write_bytes(raw)
            query_to_path[q] = str(local_path.resolve())

        if not query_to_path:
            return content_parts
        return _rewrite_cdn_parts_with_local_paths(
            content_parts,
            query_to_path,
        )

    async def _poll_loop(self) -> None:
        if self._client is None:
            return
        delay = _RETRY_INITIAL_S
        consecutive_session_timeout = 0
        while not self._stop_event.is_set():
            try:
                response = await self._client.get_updates(
                    self._state.get_updates_buf,
                )
                delay = _RETRY_INITIAL_S
                errcode = response.get("errcode")
                if errcode == -14:
                    # Stale or invalid get_updates_buf
                    # (common after restart). Do not
                    # persist get_updates_buf from
                    # this response. Back off to
                    # avoid a tight loop if
                    # the server returns -14 repeatedly.
                    consecutive_session_timeout += 1
                    if consecutive_session_timeout == 1:
                        logger.info(
                            "wechat: session expired, reset get_updates_buf",
                        )
                    else:
                        logger.debug(
                            "wechat: get_updates_buf still "
                            "invalid (%s), retry",
                            consecutive_session_timeout,
                        )
                    await self._state.set_get_updates_buf("")
                    backoff = min(
                        0.5 * (2 ** min(consecutive_session_timeout - 1, 4)),
                        8.0,
                    )
                    await asyncio.sleep(backoff)
                    continue
                consecutive_session_timeout = 0

                new_buf = str(
                    response.get("get_updates_buf")
                    or response.get("sync_buf")
                    or self._state.get_updates_buf,
                )
                if new_buf and new_buf != self._state.get_updates_buf:
                    await self._state.set_get_updates_buf(new_buf)

                messages = response.get("msgs") or []
                if not isinstance(messages, list):
                    continue
                for message in messages:
                    await self._on_incoming_message(message)
            except asyncio.CancelledError:
                break
            except (
                WechatApiError,
                WechatProtocolError,
                httpx.HTTPError,
                ValueError,
            ) as exc:
                logger.error("wechat poll failed: %s", exc)
                await asyncio.sleep(delay)
                delay = min(delay * 2.0, _RETRY_MAX_S)

    async def _on_incoming_message(self, message: Any) -> None:
        if not isinstance(message, dict):
            return
        message_type = int(message.get("message_type") or 0)
        if message_type != MESSAGE_TYPE_USER:
            logger.info(
                "wechat inbound non-user message_type=%s from=%s to=%s",
                message_type,
                message.get("from_user_id"),
                message.get("to_user_id"),
            )
            return
        sender_id = str(message.get("from_user_id") or "").strip()
        if not sender_id:
            return
        item_list = message.get("item_list") or []
        if not isinstance(item_list, list):
            return
        content_parts = message_item_list_to_parts(item_list)
        if not content_parts:
            return
        content_parts = await self._materialize_inbound_cdn_media(
            item_list,
            content_parts,
        )

        context_token = str(message.get("context_token") or "").strip()
        logger.info(
            "wechat inbound sender=%s has_context_token=%s",
            sender_id,
            bool(context_token),
        )
        if context_token:
            prev = self._state.get_context_token(sender_id) or ""
            if prev and prev != context_token:
                logger.info(
                    "wechat inbound token changed"
                    " sender=%s prev_len=%s new_len=%s",
                    sender_id,
                    len(prev),
                    len(context_token),
                )
            await self._state.set_context_token(sender_id, context_token)

        meta = {
            "context_token": context_token,
            "to_user_id": str(message.get("to_user_id") or ""),
            "message_id": message.get("message_id"),
            "raw_message": message,
        }
        payload = {
            "channel_id": self.channel,
            "sender_id": sender_id,
            "session_id": self.resolve_session_id(sender_id, meta),
            "content_parts": content_parts,
            "meta": meta,
        }
        if self._enqueue is None:
            logger.warning("wechat: _enqueue is not set, dropping message")
            return
        self._enqueue(payload)

    async def _send_items(
        self,
        *,
        to_user_id: str,
        item_list: List[Dict[str, Any]],
        meta: Optional[Dict[str, Any]],
    ) -> None:
        if self._client is None:
            raise WechatProtocolError("channel is not started")
        if not to_user_id:
            raise WechatProtocolError("to_user_id is empty")

        meta_token = str((meta or {}).get("context_token") or "").strip()
        stored_token = (
            self._state.get_context_token(to_user_id) or ""
        ).strip()
        if stored_token:
            context_token = stored_token
            context_source = "state"
        elif meta_token:
            context_token = meta_token
            context_source = "meta"
        else:
            context_token = ""
            context_source = "none"
        logger.info(
            "wechat outbound to=%s token_source=%s has_context_token=%s "
            "meta_token=%s state_token=%s items=%s",
            to_user_id,
            context_source,
            bool(context_token),
            bool(meta_token),
            bool(stored_token),
            len(item_list),
        )

        typing_started = False
        if self.typing_enabled:
            typing_started = await self._start_typing(
                to_user_id=to_user_id,
                context_token=context_token,
            )

        request_body = {
            "msg": {
                "from_user_id": "",
                "to_user_id": to_user_id,
                "client_id": f"copaw-wechat-{uuid.uuid4().hex}",
                "message_type": MESSAGE_TYPE_BOT,
                "message_state": MESSAGE_STATE_FINISH,
                "context_token": context_token,
                "item_list": item_list,
            },
        }
        logger.info(
            "wechat outbound payload client_id=%s"
            " message_type=%s message_state=%s",
            request_body["msg"]["client_id"],
            request_body["msg"]["message_type"],
            request_body["msg"]["message_state"],
        )

        delay = _RETRY_INITIAL_S
        attempt = 0
        try:
            while True:
                attempt += 1
                try:
                    response = await self._client.send_message(request_body)
                    response_token = str(
                        response.get("context_token") or "",
                    ).strip()
                    updated_token = response_token or context_token
                    if updated_token:
                        await self._state.set_context_token(
                            to_user_id,
                            updated_token,
                        )
                    logger.info(
                        "wechat outbound ack to=%s ret=%s errcode=%s "
                        "response_context_token=%s persisted_context_token=%s",
                        to_user_id,
                        response.get("ret"),
                        response.get("errcode"),
                        bool(response_token),
                        bool(updated_token),
                    )
                    break
                except (
                    WechatApiError,
                    httpx.TimeoutException,
                    httpx.NetworkError,
                ) as exc:
                    if attempt >= self.max_send_retries:
                        raise WechatApiError(
                            f"sendmessage failed after retries: {exc}",
                        ) from exc
                    logger.warning(
                        "wechat send retry %s/%s due to: %s",
                        attempt,
                        self.max_send_retries,
                        exc,
                    )
                    await asyncio.sleep(delay)
                    delay = min(delay * 2.0, _RETRY_MAX_S)
        finally:
            if typing_started:
                await self._stop_typing(to_user_id=to_user_id)

    async def _upload_media_part(
        self,
        part: OutgoingContentPart,
        *,
        to_user_id: str,
    ) -> Optional[UploadResult]:
        if self._client is None:
            return None
        media_type = media_type_for_part(part)
        if media_type is None:
            return None

        local_path = await self._resolve_local_media_path(part)
        if local_path is None:
            return None
        return await self._client.upload_media(
            local_path=local_path,
            to_user_id=to_user_id,
            media_type=media_type,
        )

    async def _resolve_local_media_path(
        self,
        part: OutgoingContentPart,
    ) -> Optional[Path]:
        candidate = ""
        part_type = getattr(part, "type", None)
        if part_type == ContentType.IMAGE:
            candidate = str(getattr(part, "image_url", "") or "")
        elif part_type == ContentType.VIDEO:
            candidate = str(getattr(part, "video_url", "") or "")
        elif part_type == ContentType.FILE:
            candidate = str(getattr(part, "file_url", "") or "")
        elif part_type == ContentType.AUDIO:
            candidate = str(
                getattr(part, "data", None) or getattr(part, "audio_url", ""),
            )
        if not candidate:
            return None

        if candidate.startswith("http://") or candidate.startswith("https://"):
            filename = (
                Path(candidate.split("?", maxsplit=1)[0]).name or "remote.bin"
            )
            target_path = self._media_dir / filename
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(candidate)
            if response.status_code >= 400:
                raise WechatApiError(
                    f"failed to fetch remote media: "
                    f"status={response.status_code}",
                )
            target_path.write_bytes(response.content)
            return target_path

        local = file_url_to_local_path(candidate)
        if local:
            path = Path(local).expanduser()
            if path.is_file():
                return path.resolve()
        return None

    async def _start_typing(
        self,
        *,
        to_user_id: str,
        context_token: str,
    ) -> bool:
        if self._client is None:
            return False
        ticket = self._typing_tickets.get(to_user_id)
        if not ticket:
            try:
                config = await self._client.get_config(
                    ilink_user_id=to_user_id,
                    context_token=context_token,
                )
            except (WechatApiError, httpx.HTTPError, ValueError):
                return False
            ticket = str(config.get("typing_ticket") or "").strip()
            if not ticket:
                return False
            self._typing_tickets[to_user_id] = ticket
        try:
            await self._client.send_typing(
                ilink_user_id=to_user_id,
                typing_ticket=ticket,
                status=TYPING_STATUS_TYPING,
            )
            return True
        except (WechatApiError, httpx.HTTPError, ValueError):
            return False

    async def _stop_typing(self, *, to_user_id: str) -> None:
        if self._client is None:
            return
        ticket = self._typing_tickets.get(to_user_id)
        if not ticket:
            return
        try:
            await self._client.send_typing(
                ilink_user_id=to_user_id,
                typing_ticket=ticket,
                status=TYPING_STATUS_CANCEL,
            )
        except (WechatApiError, httpx.HTTPError, ValueError):
            logger.debug("wechat: stop typing failed for %s", to_user_id)

    def to_handle_from_target(self, *, user_id: str, session_id: str) -> str:
        return user_id or session_id
