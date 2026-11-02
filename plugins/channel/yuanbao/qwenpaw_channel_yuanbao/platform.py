# -*- coding: utf-8 -*-
"""Worker-owned Yuanbao gateway, native parsing, sessions and COS effects."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import errno
import hashlib
import json
import logging
import os
from pathlib import Path
import tempfile
from typing import Any, List, Optional
import uuid

import aiohttp

from qwenpaw.app.channels.utils import split_text
from .auth import TokenManager
from .codec import (
    CMD_AUTH_BIND,
    CMD_KICKOUT,
    CMD_PING,
    CMD_TYPE_PUSH,
    CMD_TYPE_RESPONSE,
    build_auth_bind_msg,
    build_heartbeat_msg,
    build_ping_msg,
    build_push_ack,
    build_send_c2c_msg,
    build_send_group_msg,
    decode_auth_bind_rsp,
    decode_conn_msg,
    decode_kickout_msg,
    decode_ping_rsp,
    decode_send_rsp,
)
from .constants import (
    AUTH_ALREADY_CODE,
    AUTH_FAILED_CODES,
    DEFAULT_API_DOMAIN,
    DEFAULT_WS_URL,
    HEARTBEAT_FINISH,
    HEARTBEAT_RUNNING,
    HEARTBEAT_INTERVAL,
    HEARTBEAT_TIMEOUT_THRESHOLD,
    MAX_RECONNECT_ATTEMPTS,
    NO_RECONNECT_CLOSE_CODES,
    RECONNECT_DELAYS,
    SEND_TIMEOUT,
    SESSION_ID_SUFFIX_LEN,
    TYPING_KEEPALIVE_INTERVAL,
)
from .errors import YuanbaoDeliveryError, YuanbaoReceipt
from .media import (
    build_file_msg_body,
    build_image_msg_body,
    download_and_upload_media,
    resolve_download_url,
)
from .utils import download_media

logger = logging.getLogger(__name__)
_AUDIO_EXTS = frozenset(
    {
        ".mp3",
        ".wav",
        ".m4a",
        ".ogg",
        ".opus",
        ".silk",
        ".amr",
        ".aac",
        ".flac",
    },
)
_QUOTE_TYPE_LABEL = {1: "message", 2: "image", 3: "file"}


def _short_id(raw_id: str) -> str:
    n = SESSION_ID_SUFFIX_LEN
    return raw_id[-n:] if len(raw_id) >= n else raw_id


def _sender_display(nickname: str, raw_sender_id: str) -> str:
    nick = (nickname or "").strip() or "unknown"
    suffix = (
        raw_sender_id[-4:]
        if len(raw_sender_id) >= 4
        else (raw_sender_id or "????")
    )
    return f"{nick}#{suffix}"


class YuanbaoPlatform:
    def __init__(self, config, on_event, on_state):
        self.config, self.on_event, self.on_state = (
            dict(config),
            on_event,
            on_state,
        )
        self.enabled = bool(config.get("enabled", False))
        self.app_id = config.get("app_id", "")
        self.app_secret = config.get("app_secret", "")
        self.api_domain = config.get("api_domain") or DEFAULT_API_DOMAIN
        self.ws_url = (config.get("ws_url") or "").strip() or DEFAULT_WS_URL
        self.accept_bot_messages = config.get("accept_bot_messages", False)
        workspace = config.get("workspace_dir")
        self._workspace_dir = (
            Path(workspace).expanduser() if workspace else None
        )
        if config.get("media_dir"):
            self._media_dir = Path(config["media_dir"]).expanduser()
        elif self._workspace_dir:
            self._media_dir = self._workspace_dir / "media"
        else:
            from qwenpaw.constant import DEFAULT_MEDIA_DIR

            self._media_dir = DEFAULT_MEDIA_DIR / "yuanbao"
        self._token_manager = None
        self._ws = self._session = self._media_session = None
        self._connected = self._stopping = False
        self._bot_id = ""
        self._reconnect_attempts = 0
        self._heartbeat_interval = HEARTBEAT_INTERVAL
        self._heartbeat_ack_received = True
        self._heartbeat_timeout_count = 0
        self._heartbeat_task = self._receive_task = self._reconnect_task = None
        self._tasks, self._operations = set(), set()
        self._typing_tasks = {}
        self._pending_requests = {}
        self._seen_message_ids = {}
        self._admission_lock = asyncio.Lock()
        self._session_map = {}
        self._session_changes = {}
        self._load_session_map_from_disk()

    def _spawn(self, coroutine):
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)

        def done(finished):
            self._tasks.discard(finished)
            if not finished.cancelled() and finished.exception() is not None:
                logger.error(
                    "yuanbao: background operation failed: %s",
                    finished.exception(),
                )

        task.add_done_callback(done)
        return task

    @asynccontextmanager
    async def _effect(self):
        if self._stopping:
            raise YuanbaoDeliveryError("YUANBAO_STOPPING")
        owner = asyncio.current_task()
        self._operations.add(owner)
        try:
            yield
        finally:
            self._operations.discard(owner)

    async def start(self):
        if not self.enabled:
            await self.on_state("disconnected")
            return
        if not self.app_id or not self.app_secret:
            raise ValueError("Yuanbao app_id and app_secret are required")
        self._media_dir.mkdir(parents=True, exist_ok=True)
        self._token_manager = TokenManager(
            self.app_id,
            self.app_secret,
            self.api_domain,
        )
        async with self._effect():
            try:
                await self._connect()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("yuanbao: initial connection failed")
                await self._close_connection()
                self._schedule_reconnect()

    async def _connect(self):
        await self._close_connection()
        await self.on_state("connecting")
        token = await self._token_manager.get_token()
        self._bot_id = token.bot_id
        self._session = aiohttp.ClientSession()
        # ClientWSTimeout was added after the legacy aiohttp>=3.9 floor.
        timeout = (
            aiohttp.ClientWSTimeout(ws_close=float(SEND_TIMEOUT))
            if hasattr(aiohttp, "ClientWSTimeout")
            else float(SEND_TIMEOUT)
        )
        self._ws = await self._session.ws_connect(self.ws_url, timeout=timeout)
        raw = build_auth_bind_msg(
            biz_id="ybBot",
            uid=self._bot_id,
            source=token.source,
            token=token.token,
        )
        if raw is None:
            raise RuntimeError("AUTH_ENCODING_FAILED")
        await asyncio.wait_for(self._ws.send_bytes(raw), SEND_TIMEOUT)
        if not await self._wait_for_auth_response():
            # The next connection must not reuse a token rejected by AuthBind.
            await self._token_manager.force_refresh()
            raise RuntimeError("AUTH_BIND_FAILED")
        self._connected = True
        self._reconnect_attempts = 0
        self._heartbeat_ack_received = True
        self._heartbeat_timeout_count = 0
        await self.on_state("connected")
        self._heartbeat_task = self._spawn(self._heartbeat_loop())
        self._receive_task = self._spawn(self._receive_loop())

    async def _wait_for_auth_response(self) -> bool:
        """Wait for AuthBindRsp from server."""
        assert self._ws is not None
        try:
            msg = await asyncio.wait_for(
                self._ws.receive(),
                timeout=SEND_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.error("yuanbao: auth response timeout")
            return False

        if msg.type != aiohttp.WSMsgType.BINARY:
            logger.error(
                "yuanbao: expected binary auth response, got %s",
                msg.type,
            )
            return False

        conn_msg = decode_conn_msg(msg.data)
        if not conn_msg:
            logger.error("yuanbao: failed to decode auth response")
            return False

        head = conn_msg["head"]
        if head.get("cmd") != CMD_AUTH_BIND:
            logger.error(
                "yuanbao: unexpected auth cmd: %s",
                head.get("cmd"),
            )
            return False

        raw_data = conn_msg["data"]
        logger.info(
            "yuanbao: auth response head=%s, data_len=%s, status=%s",
            head.get("cmd"),
            len(raw_data) if raw_data else 0,
            head.get("status", 0),
        )

        # AuthBindRsp may be empty on success (status in head)
        status_code = head.get("status", 0)
        rsp = decode_auth_bind_rsp(raw_data) if raw_data else {}
        if rsp is None:
            rsp = {}

        code = rsp.get("code", status_code)
        if code in (0, AUTH_ALREADY_CODE):
            connect_id = rsp.get("connectId", "")
            logger.info(
                "yuanbao: auth success connectId=%s",
                connect_id,
            )
            return True

        logger.error(
            "yuanbao: auth failed: code=%s, message=%s",
            code,
            rsp.get("message", ""),
        )
        return False

    async def _heartbeat_loop(self) -> None:
        """Send periodic protobuf Ping to keep connection alive."""
        while self._connected and self._ws and not self._ws.closed:
            try:
                await asyncio.sleep(self._heartbeat_interval)
                if not self._connected or not self._ws or self._ws.closed:
                    break

                if not self._heartbeat_ack_received:
                    self._heartbeat_timeout_count += 1
                    logger.warning(
                        "yuanbao: heartbeat timeout (%s/%s)",
                        self._heartbeat_timeout_count,
                        HEARTBEAT_TIMEOUT_THRESHOLD,
                    )
                    if (
                        self._heartbeat_timeout_count
                        >= HEARTBEAT_TIMEOUT_THRESHOLD
                    ):
                        logger.error(
                            "yuanbao: heartbeat threshold "
                            "reached, reconnecting",
                        )
                        await self._force_close_ws()
                        break
                else:
                    self._heartbeat_timeout_count = 0

                self._heartbeat_ack_received = False
                ping_binary = build_ping_msg()
                if ping_binary is not None:
                    await asyncio.wait_for(
                        self._ws.send_bytes(ping_binary),
                        timeout=SEND_TIMEOUT,
                    )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("yuanbao: heartbeat error: %s", exc)
                await self._force_close_ws()
                break

    async def _force_close_ws(self) -> None:
        if self._ws and not self._ws.closed:
            try:
                await self._ws.close()
            except Exception:
                pass

    async def _handle_binary_frame(self, raw: bytes) -> None:
        """Decode and dispatch a binary ConnMsg frame."""
        logger.debug(
            "yuanbao: raw ws frame %d bytes",
            len(raw),
        )
        conn_msg = decode_conn_msg(raw)
        if not conn_msg or not conn_msg.get("head"):
            logger.warning(
                "yuanbao: received undecodable frame (%s bytes)",
                len(raw),
            )
            return

        head = conn_msg["head"]
        cmd_type = head.get("cmdType", 0)
        cmd = head.get("cmd", "")
        data = conn_msg.get("data", b"")

        logger.debug(
            "yuanbao: frame cmdType=%s cmd=%s module=%s data_len=%s",
            cmd_type,
            cmd,
            head.get("module", ""),
            len(data) if data else 0,
        )

        if cmd_type == CMD_TYPE_RESPONSE:
            await self._handle_response(head, data)
        elif cmd_type == CMD_TYPE_PUSH:
            await self._handle_push(head, data)
        else:
            logger.info("yuanbao: unhandled cmdType=%s", cmd_type)

    @staticmethod
    def _normalize_inbound(data: dict) -> dict:
        """Normalize inbound JSON.

        Ensures ``msg_content`` is always a dict and parses the
        ``cloud_custom_data`` JSON string into a dict (used for quoted
        message extraction downstream).
        """
        msg_body = []
        raw_body = data.get("msg_body")
        for elem in raw_body if isinstance(raw_body, list) else []:
            if not isinstance(elem, dict):
                continue
            content = elem.get("msg_content", {})
            if isinstance(content, str):
                try:
                    content = json.loads(content)
                except (ValueError, TypeError):
                    content = {"text": content}
            if not isinstance(content, dict):
                content = {}
            msg_body.append(
                {
                    "msg_type": elem.get("msg_type", ""),
                    "msg_content": content,
                },
            )

        ccd = data.get("cloud_custom_data", "")
        if isinstance(ccd, str):
            try:
                ccd = json.loads(ccd) if ccd else {}
            except (ValueError, TypeError):
                ccd = {}
        if not isinstance(ccd, dict):
            ccd = {}

        normalized = dict(data)
        normalized["msg_body"] = msg_body
        normalized["cloud_custom_data"] = ccd
        return normalized

    async def _handle_auth_failure(self) -> None:
        """Handle auth failure by refreshing token and reconnecting."""
        if self._token_manager:
            try:
                token_data = await self._token_manager.force_refresh()
                self._bot_id = token_data.bot_id
                logger.info(
                    "yuanbao: token refreshed, reconnecting...",
                )
            except Exception as exc:
                logger.error(
                    "yuanbao: token refresh failed: %s",
                    exc,
                )
        await self._force_close_ws()

    async def _resolve_media_url(self, url: str) -> str:
        """Resolve Yuanbao CDN URL to a real download URL via download API."""
        if not self._token_manager or not url:
            return url
        try:
            session = await self._get_or_create_http_session()
            auth_headers = await self._token_manager.get_auth_headers()
            return await resolve_download_url(
                url,
                session,
                self.api_domain,
                auth_headers,
            )
        except Exception as exc:
            logger.warning("yuanbao: resolve media URL failed: %s", exc)
            return url

    def _is_bot_mention(self, content: dict) -> bool:
        """Check if a TIMCustomElem content mentions this bot."""
        data_str = content.get("data", "")
        if not data_str or not isinstance(data_str, str):
            return False
        try:
            custom = json.loads(data_str)
            if isinstance(custom, dict) and custom.get("elem_type") == 1002:
                return custom.get("user_id", "") == self._bot_id
        except (ValueError, TypeError):
            pass
        return False

    def _is_bot_message(self, inbound: dict) -> bool:
        """Return True if the inbound message was sent by a bot.

        Two signals are used in combination:
        1. ``from_account`` starts with ``bot_`` — the platform uses this
           prefix for all custom bot accounts.
        2. Any ``TIMTextElem`` carries a ``data`` field whose JSON payload
           has ``elem_type == 1013`` — the platform attaches this structured
           copy exclusively to bot-originated text messages.
        """
        if str(inbound.get("from_account") or "").startswith("bot_"):
            return True
        for elem in inbound.get("msg_body", []):
            if elem.get("msg_type") != "TIMTextElem":
                continue
            data_str = elem.get("msg_content", {}).get("data", "")
            if not data_str:
                continue
            try:
                parsed = json.loads(data_str)
                if (
                    isinstance(parsed, dict)
                    and parsed.get("elem_type") == 1013
                ):
                    return True
            except (ValueError, TypeError):
                pass
        return False

    async def _parse_msg_body(
        self,
        msg_body: List[dict],
        is_group: bool = False,
    ) -> tuple:
        """Parse msg_body elements into content parts.

        Yuanbao only emits four element kinds in practice:
          * ``TIMCustomElem`` (elem_type=1002) -- @mention tag
          * ``TIMTextElem`` -- plain text
          * ``TIMImageElem`` -- image with multi-resolution url array
          * ``TIMFileElem`` -- generic file (incl. audio uploaded as file)

        Audio is routed to :class:`AudioContent` based on the file-name
        suffix so it joins the unified ASR pipeline.  Video / voice elem
        types historically supported by TIM are not pushed by Yuanbao;
        an ``unhandled msg_type`` warning is emitted as a safety net.
        """
        parts: List[Any] = []
        bot_mentioned = False

        for elem in msg_body:
            msg_type = elem.get("msg_type", "")
            content = elem.get("msg_content", {})

            # TIMCustomElem with elem_type 1002 is an @mention tag
            # in group chats — skip it but note the mention.
            if msg_type == "TIMCustomElem":
                bot_mentioned = bot_mentioned or self._is_bot_mention(
                    content,
                )
                continue

            if msg_type == "TIMTextElem":
                text = str(content.get("text") or "").strip()
                if text and self._bot_id:
                    text = text.replace(f"@{self._bot_id}", "").strip()
                if text:
                    parts.append(
                        {"type": "text", "text": text},
                    )

            elif msg_type == "TIMImageElem":
                image_url = ""
                for img_info in content.get("image_info_array", []):
                    if img_info.get("url"):
                        image_url = img_info["url"]
                        break
                if not image_url:
                    image_url = content.get("url", "")
                if image_url:
                    part = await self._download_and_wrap(
                        image_url,
                        filename="image.jpg",
                        kind="image",
                    )
                    if part is not None:
                        parts.append(part)

            elif msg_type == "TIMFileElem":
                file_url = content.get("url", "")
                filename = content.get("file_name", "file") or "file"
                if file_url:
                    kind = self._classify_file(filename)
                    part = await self._download_and_wrap(
                        file_url,
                        filename=filename,
                        kind=kind,
                    )
                    if part is not None:
                        parts.append(part)

            else:
                logger.warning(
                    "yuanbao: unhandled msg_type=%s",
                    msg_type,
                )

        return parts, bot_mentioned

    @staticmethod
    def _classify_file(filename: str) -> str:
        """Classify a TIMFileElem payload as ``audio`` or ``file``.

        Returns ``audio`` when the filename suffix is in :data:`_AUDIO_EXTS`,
        otherwise ``file``.
        """
        if Path(filename).suffix.lower() in _AUDIO_EXTS:
            return "audio"
        return "file"

    @staticmethod
    def _build_quoted_prefix(quote: dict) -> Optional[str]:
        """Render an inline placeholder for ``cloud_custom_data.quote``.

        Yuanbao only includes ``id`` / ``desc`` / ``sender_*`` in quote
        payloads (no url/key, no API to fetch the original message), so
        this returns a plain bracketed text the model can read.

        The placeholder tells the model:
          * the **kind** of the quoted item (message / image / file / audio)
          * the **filename** when the upstream provides one (type=3)
        so the model can match it against earlier turns in history.
        """
        if not isinstance(quote, dict):
            return None
        qtype_raw = quote.get("type")
        qtype = qtype_raw if isinstance(qtype_raw, int) else 0
        desc = str(quote.get("desc") or "").strip()
        label = _QUOTE_TYPE_LABEL.get(qtype, "message")
        # type=3 carries a filename in desc; use the same suffix set as
        # _classify_file so wording stays consistent with non-quoted
        # messages the model has already seen.
        if qtype == 3 and desc and Path(desc).suffix.lower() in _AUDIO_EXTS:
            label = "audio"
        if desc:
            return f"[quoted {label}: {desc}]"
        return f"[quoted {label}]"

    def _prune_seen_ids(self) -> None:
        sorted_ids = sorted(
            self._seen_message_ids.items(),
            key=lambda kv: kv[1],
        )
        remove_count = len(sorted_ids) // 2
        for msg_id, _ in sorted_ids[:remove_count]:
            self._seen_message_ids.pop(msg_id, None)

    def _session_map_path(self) -> Path:
        """Path to persist session mapping for send / cron."""
        if self._workspace_dir:
            return self._workspace_dir / "yuanbao_sessions.json"
        return self._media_dir.parent / "yuanbao_sessions.json"

    async def _get_or_create_http_session(self) -> aiohttp.ClientSession:
        """Get or create an aiohttp session for media uploads.

        Uses a dedicated session separate from the WebSocket session to
        avoid connection conflicts.
        """
        if self._media_session is None or self._media_session.closed:
            self._media_session = aiohttp.ClientSession()
        return self._media_session

    async def _receive_loop(self):
        ws = self._ws
        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.BINARY:
                    await self._handle_binary_frame(msg.data)
                elif msg.type in (
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSED,
                ):
                    if (msg.data or ws.close_code) in NO_RECONNECT_CLOSE_CODES:
                        self._stopping = True
                    break
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    break
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("yuanbao: receive failed")
        finally:
            if ws is self._ws:
                if ws.close_code in NO_RECONNECT_CLOSE_CODES:
                    self._stopping = True
                self._connected = False
                self._fail_pending()
                await self.on_state("disconnected")
                if not self._stopping:
                    self._schedule_reconnect()

    async def _handle_response(self, head, data):
        cmd = head.get("cmd", "")
        if cmd == CMD_PING:
            self._heartbeat_ack_received = True
            rsp = decode_ping_rsp(data)
            interval = (rsp or {}).get("heartInterval")
            if isinstance(interval, (float, int)) and interval > 0:
                self._heartbeat_interval = interval
            return
        if cmd == CMD_AUTH_BIND:
            rsp = decode_auth_bind_rsp(data) if data else {}
            if (
                head.get("status", 0) in AUTH_FAILED_CODES
                or (rsp or {}).get("code") in AUTH_FAILED_CODES
            ):
                await self._handle_auth_failure()
            return
        pending = self._pending_requests.get(head.get("msgId", ""))
        if pending is not None:
            expected, future = pending
            if expected == cmd and not future.done():
                future.set_result((dict(head), decode_send_rsp(data)))

    async def _handle_push(self, head, data):
        # Native ACK means this push frame arrived, as in the legacy gateway.
        # It never implies that event.batch has accepted or executed a message.
        if head.get("needAck"):
            ack = build_push_ack(head)
            if ack is not None and self._ws and not self._ws.closed:
                try:
                    await asyncio.wait_for(
                        self._ws.send_bytes(ack),
                        SEND_TIMEOUT,
                    )
                except Exception:
                    logger.warning("yuanbao: native push ACK write failed")
        if head.get("cmd") == CMD_KICKOUT:
            reason = (decode_kickout_msg(data) or {}).get("reason", "")
            logger.warning("yuanbao: kicked out: %s", reason)
            self._stopping = True
            await self._force_close_ws()
            return
        try:
            value = json.loads(data)
        except (ValueError, UnicodeDecodeError):
            return
        if isinstance(value, dict) and value.get("callback_command"):
            # Keep the receive reader free to resolve concurrent send receipts.
            self._spawn(
                self._handle_chat_message(self._normalize_inbound(value)),
            )

    async def _handle_chat_message(self, inbound):
        async with self._effect(), self._admission_lock:
            if not self._connected:
                return False
            msg_id = str(inbound.get("msg_id") or inbound.get("msg_key") or "")
            if msg_id and msg_id in self._seen_message_ids:
                return True
            raw_sender = str(inbound.get("from_account") or "")
            if not raw_sender:
                return False
            if not self.accept_bot_messages and self._is_bot_message(inbound):
                return False
            is_group = str(inbound.get("callback_command") or "").startswith(
                "Group.",
            )
            group_code = (
                str(inbound.get("group_code") or "") if is_group else ""
            )
            if is_group and not group_code:
                return False
            parts, mentioned = await self._parse_msg_body(
                inbound.get("msg_body", []),
                is_group=is_group,
            )
            if not parts:
                return False
            if (
                is_group
                and self.config.get("require_mention", False)
                and not mentioned
            ):
                return False
            quote = (inbound.get("cloud_custom_data") or {}).get("quote")
            prefix = (
                self._build_quoted_prefix(quote)
                if isinstance(quote, dict)
                else None
            )
            if prefix:
                for part in parts:
                    if part["type"] == "text":
                        part["text"] = prefix + "\n" + part["text"]
                        break
                else:
                    parts.insert(0, {"type": "text", "text": prefix})
            session = group_code if is_group else _short_id(raw_sender)
            nickname = str(inbound.get("sender_nickname") or "")
            target = {
                "chat_type": "group" if is_group else "c2c",
                "sender_id": raw_sender,
                "group_code": group_code,
                "msg_id": msg_id,
            }
            self._session_map[session] = target
            self._session_changes[session] = target
            await self._save_session_map_to_disk_async()
            # No platform ID means no content-hash dedup promise.
            value = {
                "event_id": msg_id or uuid.uuid4().hex,
                "sender_id": _sender_display(nickname, raw_sender),
                "raw_sender_id": raw_sender,
                "sender_name": nickname,
                "session_id": session,
                "content_parts": parts,
                "route": target,
                "meta": {
                    "chat_type": target["chat_type"],
                    "group_code": group_code,
                    "msg_id": msg_id,
                    "raw_sender_id": raw_sender,
                    "is_group": is_group,
                    "user_name": nickname,
                    "bot_mentioned": mentioned,
                    "session_id": session,
                    "sender_id": _sender_display(nickname, raw_sender),
                },
            }
            accepted = await self.on_event(value)
            if accepted and msg_id:
                self._seen_message_ids[
                    msg_id
                ] = asyncio.get_running_loop().time()
                if len(self._seen_message_ids) > 5000:
                    self._prune_seen_ids()
            return bool(accepted)

    async def _download_and_wrap(self, url, *, filename, kind):
        resolved = await self._resolve_media_url(url)
        local = await download_media(
            resolved,
            self._media_dir,
            filename=filename,
        )
        if not local:
            return {"type": "text", "text": f"[{kind}: download failed]"}
        uri = Path(local).resolve().as_uri()
        if kind == "image":
            return {"type": "image", "image_url": uri}
        if kind == "audio":
            return {"type": "audio", "data": uri}
        return {"type": "file", "file_url": uri, "filename": filename}

    def _load_session_map_from_disk(self):
        try:
            data = json.loads(self._session_map_path().read_text("utf-8"))
            if isinstance(data, dict):
                self._session_map = data
        except (OSError, ValueError):
            logger.debug("yuanbao: session map unavailable", exc_info=True)

    def _save_session_map_to_disk(self):
        self._write_session_map(blocking=True)

    async def _save_session_map_to_disk_async(self):
        # No lock or background thread survives an await/cancellation.
        loop = asyncio.get_running_loop()
        deadline = loop.time() + SEND_TIMEOUT
        while not self._write_session_map(blocking=False):
            remaining = deadline - loop.time()
            if remaining <= 0:
                logger.warning(
                    "yuanbao: session map lock timed out; changes retained",
                )
                return
            await asyncio.sleep(min(0.05, remaining))

    def _write_session_map(self, *, blocking):
        # Merge only changed keys while holding an OS lock; atomic replacement
        # preserves unrelated legacy records and never truncates a bad file.
        path = self._session_map_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            logger.warning(
                "yuanbao: refusing to replace a symlinked session map",
            )
            return True
        try:
            with open(str(path) + ".lock", "a+b") as lock:
                if os.name == "nt":
                    import msvcrt

                    lock.seek(0)
                    lock.write(b"\0")
                    lock.flush()
                    lock.seek(0)
                else:
                    import fcntl

                try:
                    if os.name == "nt":
                        mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
                        msvcrt.locking(lock.fileno(), mode, 1)
                    else:
                        mode = fcntl.LOCK_EX
                        if not blocking:
                            mode |= fcntl.LOCK_NB
                        fcntl.flock(lock, mode)
                except OSError as exc:
                    if not blocking and exc.errno in (
                        errno.EACCES,
                        errno.EAGAIN,
                        errno.EDEADLK,
                    ):
                        return False
                    raise
                try:
                    data = (
                        json.loads(path.read_text("utf-8"))
                        if path.exists()
                        else {}
                    )
                    if not isinstance(data, dict):
                        raise ValueError("SESSION_MAP_INVALID")
                    data.update(self._session_changes)
                    fd, temporary = tempfile.mkstemp(
                        prefix=".yuanbao-sessions-",
                        dir=path.parent,
                    )
                    try:
                        with os.fdopen(fd, "w", encoding="utf-8") as output:
                            json.dump(
                                data,
                                output,
                                indent=2,
                                ensure_ascii=False,
                            )
                            output.flush()
                            os.fsync(output.fileno())
                        os.replace(temporary, path)
                    finally:
                        Path(temporary).unlink(missing_ok=True)
                    self._session_map.update(data)
                    self._session_changes.clear()
                finally:
                    if os.name == "nt":
                        lock.seek(0)
                        msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(lock, fcntl.LOCK_UN)
        except (OSError, ValueError):
            logger.warning(
                "yuanbao: session map write skipped; existing data preserved",
                exc_info=True,
            )
        return True

    def resolve_target(self, session_id, meta=None):
        meta = meta or {}
        self._load_session_map_from_disk()
        value = self._session_map.get(meta.get("session_id") or session_id)
        # Native metadata is accepted only as a complete route, never by
        # guessing that a shortened user/session ID is the native account.
        if not isinstance(value, dict):
            value = {
                "chat_type": meta.get("chat_type"),
                "sender_id": meta.get("raw_sender_id"),
                "group_code": meta.get("group_code"),
                "msg_id": meta.get("msg_id") or "",
            }
        kind = value.get("chat_type")
        target = (
            value.get("group_code")
            if kind == "group"
            else value.get("sender_id")
        )
        if (
            kind not in ("c2c", "group")
            or not isinstance(target, str)
            or not target
        ):
            raise YuanbaoDeliveryError("OUTBOUND_TARGET_UNKNOWN")
        return {
            key: str(value.get(key) or "")
            for key in ("chat_type", "sender_id", "group_code", "msg_id")
        }

    def _require_connection(self):
        if (
            self._stopping
            or not self._connected
            or not self._ws
            or self._ws.closed
        ):
            raise YuanbaoDeliveryError("YUANBAO_NOT_CONNECTED", retryable=True)
        return self._ws

    def _fail_pending(self):
        for _, future in self._pending_requests.values():
            if not future.done():
                future.set_exception(
                    YuanbaoDeliveryError(
                        "YUANBAO_CONNECTION_LOST",
                        side_effect_possible=True,
                    ),
                )
        self._pending_requests.clear()

    async def _write_request(self, result):
        if result is None:
            raise YuanbaoDeliveryError("YUANBAO_ENCODING_FAILED")
        ws = self._require_connection()
        raw, msg_id = result
        head = decode_conn_msg(raw)["head"]
        future = asyncio.get_running_loop().create_future()
        self._pending_requests[msg_id] = (head["cmd"], future)
        written = None
        try:
            # Once send_bytes starts, a timeout/exception can have an effect.
            await asyncio.wait_for(ws.send_bytes(raw), SEND_TIMEOUT)
            written = True
            response_head, rsp = await asyncio.wait_for(future, SEND_TIMEOUT)
            status = response_head.get("status", 0)
            if rsp is None:
                raise YuanbaoDeliveryError(
                    "YUANBAO_RESPONSE_INVALID",
                    side_effect_possible=True,
                    receipt=YuanbaoReceipt(msg_id, True),
                )
            code = rsp.get("code", 0)
            receipt = YuanbaoReceipt(
                msg_id,
                True,
                status == 0 and code == 0,
                status,
                code,
            )
            if not receipt.business_accepted:
                raise YuanbaoDeliveryError(
                    "YUANBAO_BUSINESS_REJECTED",
                    receipt=receipt,
                )
            return receipt
        except asyncio.CancelledError:
            raise
        except YuanbaoDeliveryError as exc:
            if exc.receipt is not None:
                raise
            raise YuanbaoDeliveryError(
                exc.reason_code,
                side_effect_possible=exc.side_effect_possible,
                retryable=exc.retryable,
                receipt=YuanbaoReceipt(msg_id, written),
            ) from exc
        except Exception as exc:
            raise YuanbaoDeliveryError(
                "YUANBAO_RESULT_UNKNOWN",
                side_effect_possible=True,
                receipt=YuanbaoReceipt(msg_id, written),
            ) from exc
        finally:
            self._pending_requests.pop(msg_id, None)
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                future.exception()  # Consume a disconnect concurrent with write failure.

    async def _send_raw_msg_body(self, route, msg_body, msg_id):
        if route["chat_type"] == "group":
            result = build_send_group_msg(
                route["group_code"],
                msg_body,
                self._bot_id,
                msg_id=msg_id,
            )
        else:
            result = build_send_c2c_msg(
                route["sender_id"],
                msg_body,
                self._bot_id,
                msg_id=msg_id,
            )
        return await self._write_request(result)

    @staticmethod
    def _extract_media_url(part):
        kind = part.get("type")
        if kind == "file":
            return part.get("file_url") or part.get("file_id") or ""
        if kind == "audio":
            return (
                part.get("data")
                or part.get("audio_url")
                or part.get("file_url")
                or ""
            )
        return part.get(str(kind) + "_url") or ""

    @staticmethod
    def _media_url_fallback_text(part):
        kind = part.get("type")
        url = YuanbaoPlatform._extract_media_url(part)
        if kind == "image":
            return f"[图片: {url}]" if url else ""
        if kind == "file":
            return (
                f"[文件: {part.get('filename', 'file')} - {url}]" if url else ""
            )
        if kind == "video":
            return f"[视频: {url}]" if url else ""
        return "[音频]" if kind == "audio" else ""

    async def send_parts(self, route, parts, content_source, delivery_id):
        if getattr(content_source, "value", content_source) == "media":
            # The old public send_media inherited BaseChannel's zero effect.
            raise YuanbaoDeliveryError("LEGACY_MEDIA_ENTRYPOINT_UNSUPPORTED")
        async with self._effect():
            self._require_connection()
            receipts = []

            async def send(body):
                request_id = hashlib.sha256(
                    f"{delivery_id}:{len(receipts)}".encode(),
                ).hexdigest()[:32]
                receipts.append(
                    await self._send_raw_msg_body(route, body, request_id),
                )

            try:
                text = "\n".join(
                    p.get("text", "") for p in parts if p.get("type") == "text"
                )
                if text.strip():
                    for chunk in split_text(text):
                        await send(
                            [
                                {
                                    "msg_type": "TIMTextElem",
                                    "msg_content": {"text": chunk},
                                },
                            ],
                        )
                for part in parts:
                    if part.get("type") == "text":
                        continue
                    url = self._extract_media_url(part)
                    if not url:
                        continue
                    try:
                        session = await self._get_or_create_http_session()
                        headers = await self._token_manager.get_auth_headers()
                        roots = [self._media_dir.resolve()]
                        if self._workspace_dir:
                            roots.append(self._workspace_dir.resolve())
                        media = await download_and_upload_media(
                            url,
                            session,
                            self.api_domain,
                            headers,
                            allowed_roots=roots,
                        )
                    except PermissionError as exc:
                        raise YuanbaoDeliveryError(
                            "MEDIA_PATH_UNAUTHORIZED",
                        ) from exc
                    except Exception:
                        # Only preparation/upload failure can select the legacy
                        # link fallback. Never fallback after a native send begins.
                        fallback = self._media_url_fallback_text(part)
                        if fallback:
                            await send(
                                [
                                    {
                                        "msg_type": "TIMTextElem",
                                        "msg_content": {"text": fallback},
                                    },
                                ],
                            )
                        continue
                    body = (
                        build_image_msg_body(media)
                        if media.mime_type.startswith("image/")
                        else build_file_msg_body(media)
                    )
                    await send(body)
            except YuanbaoDeliveryError as exc:
                raise YuanbaoDeliveryError(
                    exc.reason_code,
                    side_effect_possible=bool(receipts)
                    or exc.side_effect_possible,
                    retryable=exc.retryable and not receipts,
                    receipt=exc.receipt,
                ) from exc
            return {
                "scope": "business.response" if receipts else "no_effect",
                "native_message_ids": json.dumps(
                    [r.request_id for r in receipts],
                ),
                "transport_written": "true" if receipts else "false",
                "business_accepted": "true" if receipts else "false",
                "messages": str(len(receipts)),
            }

    async def _send_typing_heartbeat(self, route, heartbeat):
        ws = self._require_connection()
        result = build_heartbeat_msg(
            from_account=self._bot_id,
            to_account=route["sender_id"],
            heartbeat=heartbeat,
            group_code=(
                route["group_code"] if route["chat_type"] == "group" else None
            ),
        )
        if result is None:
            raise YuanbaoDeliveryError("YUANBAO_TYPING_ENCODING_FAILED")
        raw, msg_id = result
        try:
            await asyncio.wait_for(ws.send_bytes(raw), SEND_TIMEOUT)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise YuanbaoDeliveryError(
                "YUANBAO_TYPING_WRITE_UNKNOWN",
                side_effect_possible=True,
                receipt=YuanbaoReceipt(msg_id, None),
            ) from exc
        return YuanbaoReceipt(msg_id, True)

    async def start_typing(self, owner, route):
        async with self._effect():
            receipt = await self._send_typing_heartbeat(
                route,
                HEARTBEAT_RUNNING,
            )
            if owner not in self._typing_tasks:

                async def keepalive():
                    try:
                        while True:
                            await asyncio.sleep(TYPING_KEEPALIVE_INTERVAL)
                            await self._send_typing_heartbeat(
                                route,
                                HEARTBEAT_RUNNING,
                            )
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        logger.warning(
                            "yuanbao: typing keepalive stopped",
                            exc_info=True,
                        )

                self._typing_tasks[owner] = self._spawn(keepalive())
            return receipt

    async def stop_typing(self, owner, route):
        task = self._typing_tasks.get(owner)
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            self._typing_tasks.pop(owner, None)
        async with self._effect():
            return await self._send_typing_heartbeat(route, HEARTBEAT_FINISH)

    def _schedule_reconnect(self):
        if self._stopping or (
            self._reconnect_task and not self._reconnect_task.done()
        ):
            return

        async def reconnect():
            while (
                not self._stopping
                and self._reconnect_attempts < MAX_RECONNECT_ATTEMPTS
            ):
                delay = RECONNECT_DELAYS[
                    min(self._reconnect_attempts, len(RECONNECT_DELAYS) - 1)
                ]
                self._reconnect_attempts += 1
                await asyncio.sleep(delay)
                if self._stopping:
                    return
                try:
                    await self._connect()
                    return
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("yuanbao: reconnect failed")
                    await self._close_connection()
            if not self._stopping:
                await self.on_state("failed")

        self._reconnect_task = self._spawn(reconnect())

    async def _close_connection(self):
        self._connected = False
        self._fail_pending()
        current = asyncio.current_task()
        tasks = [
            t
            for t in (self._heartbeat_task, self._receive_task)
            if t and t is not current
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self._ws is not None:
            await self._ws.close()
            self._ws = None
        if self._session is not None:
            await self._session.close()
            self._session = None
        self._heartbeat_task = self._receive_task = None

    async def _cleanup_session(self):
        await self._close_connection()
        if self._media_session is not None:
            await self._media_session.close()
            self._media_session = None

    async def stop(self):
        self._stopping = True
        self._connected = False
        self._fail_pending()
        current = asyncio.current_task()
        tasks = (self._tasks | self._operations) - {current}
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        # Close errors propagate; the Driver keeps this resource owner on failure.
        await self._cleanup_session()
        if self._token_manager is not None:
            await self._token_manager.close()
            self._token_manager = None
        self._typing_tasks.clear()
        self._heartbeat_task = self._receive_task = self._reconnect_task = None
        await self.on_state("disconnected")
