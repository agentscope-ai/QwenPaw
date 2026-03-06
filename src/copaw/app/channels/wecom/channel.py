# -*- coding: utf-8 -*-
"""WeCom intelligent bot channel (passive callback reply)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from agentscope_runtime.engine.schemas.agent_schemas import (
    RunStatus,
    TextContent,
)

from ....config.config import WeComConfig as WeComChannelConfig
from ..base import (
    BaseChannel,
    ContentType,
    OnReplySent,
    ProcessHandler,
)
from ..wecom_common import (
    WeComCallbackQuery,
    build_encrypted_json_response,
    decrypt_encrypted_message,
    parse_xml_to_dict,
    verify_msg_signature,
)
from .stream_state import WeComStreamState, WeComStreamStore

if TYPE_CHECKING:
    from agentscope_runtime.engine.schemas.agent_schemas import AgentRequest

logger = logging.getLogger(__name__)


class WeComChannel(BaseChannel):
    """WeCom intelligent bot callback channel.

    Receive path uses HTTP callback (GET/POST) via router:
    - GET: callback verification (decrypt echostr)
    - POST: decrypt inbound xml, enqueue request, await reply,
      return encrypted xml

    This channel supports passive reply only. Proactive send is provided by
    ``WeComAppChannel``.
    """

    channel = "wecom"
    display_name = "WeCom"

    def __init__(
        self,
        process: ProcessHandler,
        enabled: bool,
        token: str,
        encoding_aes_key: str,
        bot_prefix: str,
        receive_id: str = "",
        webhook_path: str = "/wecom",
        reply_timeout_sec: float = 4.5,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
    ):
        super().__init__(
            process,
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            filter_thinking=filter_thinking,
        )
        self.enabled = enabled
        self.token = token or ""
        self.encoding_aes_key = encoding_aes_key or ""
        self.bot_prefix = bot_prefix
        self.receive_id = receive_id or ""
        self.webhook_path = webhook_path or "/wecom"
        self.reply_timeout_sec = max(float(reply_timeout_sec or 4.5), 0.5)
        self.initial_stream_wait_sec = max(
            float(os.getenv("WECOM_INITIAL_STREAM_WAIT_SEC", "0.8") or 0.8),
            0.0,
        )
        self.stream_placeholder = (
            os.getenv("WECOM_STREAM_PLACEHOLDER", "稍等~").strip() or "稍等~"
        )
        self.stream_store = WeComStreamStore(
            ttl_seconds=float(os.getenv("WECOM_STREAM_TTL_SEC", "600") or 600),
        )

    @classmethod
    def from_env(
        cls,
        process: ProcessHandler,
        on_reply_sent: OnReplySent = None,
    ) -> "WeComChannel":
        return cls(
            process=process,
            enabled=os.getenv("WECOM_CHANNEL_ENABLED", "0") == "1",
            token=os.getenv("WECOM_TOKEN", ""),
            encoding_aes_key=os.getenv("WECOM_ENCODING_AES_KEY", ""),
            bot_prefix=os.getenv("WECOM_BOT_PREFIX", "[BOT] "),
            receive_id=os.getenv("WECOM_RECEIVE_ID", ""),
            webhook_path=os.getenv("WECOM_WEBHOOK_PATH", "/wecom"),
            reply_timeout_sec=float(
                os.getenv("WECOM_REPLY_TIMEOUT_SEC", "4.5"),
            ),
            on_reply_sent=on_reply_sent,
        )

    @classmethod
    def from_config(
        cls,
        process: ProcessHandler,
        config: WeComChannelConfig,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
    ) -> "WeComChannel":
        return cls(
            process=process,
            enabled=config.enabled,
            token=config.token or "",
            encoding_aes_key=config.encoding_aes_key or "",
            bot_prefix=config.bot_prefix or "[BOT] ",
            receive_id=config.receive_id or "",
            webhook_path=config.webhook_path or "/wecom",
            reply_timeout_sec=config.reply_timeout_sec or 4.5,
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            filter_thinking=filter_thinking,
        )

    async def start(self) -> None:
        if not self.enabled:
            logger.info("wecom: disabled")
            return
        logger.info(
            "wecom channel started: webhook_path=%s",
            self.webhook_path,
        )

    async def stop(self) -> None:
        return

    def build_agent_request_from_native(
        self,
        native_payload: Any,
    ) -> "AgentRequest":
        payload = native_payload if isinstance(native_payload, dict) else {}
        channel_id = payload.get("channel_id") or self.channel
        sender_id = payload.get("sender_id") or ""
        content_parts = payload.get("content_parts") or []
        meta = dict(payload.get("meta") or {})
        session_id = self.resolve_session_id(sender_id, meta)
        request = self.build_agent_request_from_user_content(
            channel_id=channel_id,
            sender_id=sender_id,
            session_id=session_id,
            content_parts=content_parts,
            channel_meta=meta,
        )
        setattr(request, "channel_meta", meta)
        return request

    def resolve_session_id(
        self,
        sender_id: str,
        channel_meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        meta = channel_meta or {}
        conversation_id = (meta.get("conversation_id") or "").strip()
        if conversation_id:
            return f"{self.channel}:conv:{conversation_id}"
        return f"{self.channel}:user:{sender_id}"

    @staticmethod
    def _conversation_id_from_message(msg: Dict[str, str]) -> str:
        chat_id = str(msg.get("chat_id") or "").strip()
        chat_type = str(msg.get("chat_type") or "").strip().lower()
        if chat_id and chat_type not in {"single", "p2p", "private"}:
            return chat_id
        if chat_id and not chat_type:
            return chat_id
        return str(msg.get("from_user") or "").strip()

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        del meta
        logger.warning(
            (
                "wecom passive channel does not support proactive send: "
                "to=%s text_len=%s"
            ),
            to_handle,
            len(text or ""),
        )

    async def handle_callback(
        self,
        *,
        method: str,
        request_url: str,
        body_text: str,
    ) -> tuple[int, str, str]:
        """Handle WeCom callback request.

        Returns ``(status_code, content_type, response_body)``.
        """
        if not self.enabled:
            return 503, "text/plain; charset=utf-8", "wecom disabled"

        if not self.token or not self.encoding_aes_key:
            return 500, "text/plain; charset=utf-8", "wecom not configured"

        query = WeComCallbackQuery.from_url(request_url)

        if method.upper() == "GET":
            return self._handle_verify_get(query)

        if method.upper() != "POST":
            return 405, "text/plain; charset=utf-8", "method not allowed"

        return await self._handle_message_post(query, body_text)

    def _handle_verify_get(
        self,
        query: WeComCallbackQuery,
    ) -> tuple[int, str, str]:
        if not (
            query.timestamp
            and query.nonce
            and query.signature
            and query.echostr
        ):
            return 400, "text/plain; charset=utf-8", "missing query params"

        if not verify_msg_signature(
            token=self.token,
            timestamp=query.timestamp,
            nonce=query.nonce,
            encrypt=query.echostr,
            signature=query.signature,
        ):
            return 401, "text/plain; charset=utf-8", "unauthorized"

        try:
            plaintext = decrypt_encrypted_message(
                encoding_aes_key=self.encoding_aes_key,
                encrypt=query.echostr,
                receive_id=self.receive_id,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("wecom verify decrypt failed: %s", exc)
            return 400, "text/plain; charset=utf-8", "decrypt failed"

        return 200, "text/plain; charset=utf-8", plaintext

    # pylint: disable=too-many-return-statements
    async def _handle_message_post(
        self,
        query: WeComCallbackQuery,
        body_text: str,
    ) -> tuple[int, str, str]:
        if not (query.timestamp and query.nonce and query.signature):
            return 400, "text/plain; charset=utf-8", "missing query params"

        try:
            envelope = self._parse_envelope(body_text)
        except Exception as exc:
            logger.warning("wecom parse envelope failed: %s", exc)
            return 400, "text/plain; charset=utf-8", "invalid xml"

        encrypt = (
            envelope.get("Encrypt") or envelope.get("encrypt") or ""
        ).strip()
        if not encrypt:
            return 400, "text/plain; charset=utf-8", "missing Encrypt"

        msg_signature = (
            envelope.get("MsgSignature")
            or envelope.get("msg_signature")
            or query.signature
        )
        timestamp = envelope.get("TimeStamp") or query.timestamp
        nonce = envelope.get("Nonce") or query.nonce

        if not verify_msg_signature(
            token=self.token,
            timestamp=timestamp,
            nonce=nonce,
            encrypt=encrypt,
            signature=msg_signature,
        ):
            return 401, "text/plain; charset=utf-8", "unauthorized"

        try:
            plaintext = decrypt_encrypted_message(
                encoding_aes_key=self.encoding_aes_key,
                encrypt=encrypt,
                receive_id=self.receive_id,
            )
        except Exception as exc:
            logger.warning("wecom decrypt/parse failed: %s", exc)
            return 400, "text/plain; charset=utf-8", "decrypt failed"

        msg = self._parse_plain_message(plaintext)
        msg_type = str(msg.get("msgtype") or "").strip().lower()
        if self._supports_stream_protocol():
            if msg_type == "stream":
                return self._handle_stream_poll(
                    msg=msg,
                    nonce=nonce,
                    timestamp=timestamp,
                )

        if msg_type != "text":
            return self._build_json_reply_response(
                plaintext_json={},
                nonce=nonce,
                timestamp=timestamp,
            )

        inbound_text = str(msg.get("content") or "").strip()
        from_user = str(msg.get("from_user") or "").strip()
        to_user = str(msg.get("to_user") or "").strip()
        msg_id = str(msg.get("msg_id") or "").strip()

        if not from_user:
            return 400, "text/plain; charset=utf-8", "missing sender"

        if self._supports_stream_protocol():
            existing = self.stream_store.get_by_msg_id(msg_id)
            if existing is not None:
                return self._build_stream_http_response(
                    self._build_stream_initial_reply(existing),
                    nonce=nonce,
                    timestamp=timestamp,
                )

            stream_state = self.stream_store.create(msg_id=msg_id)
            asyncio.create_task(
                self._dispatch_stream_request(
                    from_user=from_user,
                    to_user=to_user,
                    inbound_text=inbound_text,
                    channel_meta={
                        "to_user_name": to_user,
                        "from_user_name": from_user,
                        "msg_id": msg_id,
                        "conversation_id": self._conversation_id_from_message(
                            msg,
                        ),
                        "wecom_msg_type": msg_type,
                    },
                    stream_id=stream_state.stream_id,
                ),
            )
            await self._wait_for_stream_content(
                stream_id=stream_state.stream_id,
                timeout=self.initial_stream_wait_sec,
            )

            latest_state = (
                self.stream_store.get(stream_state.stream_id) or stream_state
            )
            return self._build_stream_http_response(
                self._build_stream_initial_reply(latest_state),
                nonce=nonce,
                timestamp=timestamp,
            )

        reply_text = await self._run_inbound_request(
            from_user=from_user,
            to_user=to_user,
            inbound_text=inbound_text,
            channel_meta={
                "to_user_name": to_user,
                "from_user_name": from_user,
                "msg_id": msg_id,
                "conversation_id": self._conversation_id_from_message(msg),
                "wecom_msg_type": msg_type,
            },
        )

        return self._build_json_reply_response(
            plaintext_json={
                "msgtype": "text",
                "text": {"content": reply_text},
            },
            nonce=nonce,
            timestamp=timestamp,
        )

    async def _dispatch_stream_request(
        self,
        *,
        from_user: str,
        to_user: str,
        inbound_text: str,
        channel_meta: Dict[str, Any],
        stream_id: str,
    ) -> None:
        content_parts = [
            TextContent(type=ContentType.TEXT, text=inbound_text),
        ]
        meta = {
            **channel_meta,
            "to_user_name": to_user,
            "from_user_name": from_user,
            "stream_id": stream_id,
            "bot_prefix": self.bot_prefix,
        }
        native = {
            "channel_id": self.channel,
            "sender_id": from_user,
            "content_parts": content_parts,
            "meta": meta,
        }

        try:
            if self._enqueue:
                self._enqueue(native)
            else:
                await self._consume_one_request(native)
        except Exception as exc:
            logger.exception("wecom stream dispatch failed")
            state = self.stream_store.get(stream_id)
            if state is not None:
                state.mark_finished(error=f"Error: {exc}")

    async def _wait_for_stream_content(
        self,
        *,
        stream_id: str,
        timeout: float,
    ) -> None:
        if timeout <= 0:
            return
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            state = self.stream_store.get(stream_id)
            if state is None:
                return
            if state.content.strip() or state.error or state.finished:
                return
            if asyncio.get_running_loop().time() >= deadline:
                return
            await asyncio.sleep(0.05)

    def _build_json_reply_response(
        self,
        *,
        plaintext_json: object,
        nonce: str,
        timestamp: str,
    ) -> tuple[int, str, str]:
        payload = build_encrypted_json_response(
            token=self.token,
            encoding_aes_key=self.encoding_aes_key,
            plaintext_json=plaintext_json,
            nonce=nonce,
            timestamp=timestamp,
            receive_id=self.receive_id,
        )
        return (
            200,
            "text/plain; charset=utf-8",
            json.dumps(payload, ensure_ascii=False),
        )

    def _handle_stream_poll(
        self,
        *,
        msg: Dict[str, str],
        nonce: str,
        timestamp: str,
    ) -> tuple[int, str, str]:
        stream_id = str(msg.get("stream_id") or "").strip()
        state = self.stream_store.get(stream_id)
        if state is None:
            state = WeComStreamState(
                stream_id=stream_id or "unknown",
                finished=True,
            )
        return self._build_stream_http_response(
            self._build_stream_reply_from_state(state),
            nonce=nonce,
            timestamp=timestamp,
        )

    def _build_stream_http_response(
        self,
        reply_json: Dict[str, Any],
        *,
        nonce: str,
        timestamp: str,
    ) -> tuple[int, str, str]:
        return self._build_json_reply_response(
            plaintext_json=reply_json,
            nonce=nonce,
            timestamp=timestamp,
        )

    def _build_stream_initial_reply(
        self,
        state: WeComStreamState,
    ) -> Dict[str, Any]:
        if (state.content or "").strip() or state.error:
            return self._build_stream_reply_from_state(state)
        return self._build_stream_placeholder_reply(state.stream_id)

    def _build_stream_placeholder_reply(
        self,
        stream_id: str,
    ) -> Dict[str, Any]:
        return {
            "msgtype": "stream",
            "stream": {
                "id": stream_id,
                "finish": False,
                "content": self.stream_placeholder,
            },
        }

    def _build_stream_reply_from_state(
        self,
        state: WeComStreamState,
    ) -> Dict[str, Any]:
        stream: Dict[str, Any] = {
            "id": state.stream_id,
            "finish": bool(state.finished),
        }
        content = (state.content or "").strip()
        if content:
            stream["content"] = content
        return {
            "msgtype": "stream",
            "stream": stream,
        }

    def _supports_stream_protocol(self) -> bool:
        return self.channel == "wecom"

    async def _run_inbound_request(
        self,
        *,
        from_user: str,
        to_user: str,
        inbound_text: str,
        channel_meta: Dict[str, Any],
    ) -> str:
        loop = asyncio.get_running_loop()
        reply_future: asyncio.Future[str] = loop.create_future()
        content_parts = [
            TextContent(type=ContentType.TEXT, text=inbound_text),
        ]
        meta = {
            **channel_meta,
            "to_user_name": to_user,
            "from_user_name": from_user,
            "reply_future": reply_future,
            "reply_loop": loop,
        }
        native = {
            "channel_id": self.channel,
            "sender_id": from_user,
            "content_parts": content_parts,
            "meta": meta,
        }

        if self._enqueue:
            self._enqueue(native)
        else:
            await self._consume_one_request(native)

        try:
            return await asyncio.wait_for(
                reply_future,
                timeout=self.reply_timeout_sec,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "wecom reply timeout: user=%s timeout=%.2fs",
                from_user,
                self.reply_timeout_sec,
            )
            return "我已收到，正在处理，请稍后重试。"

    def _reply_sync(
        self,
        meta: Dict[str, Any],
        text: str,
    ) -> None:
        reply_loop = meta.get("reply_loop")
        reply_future = meta.get("reply_future")
        if reply_loop is None or reply_future is None:
            return
        if getattr(reply_future, "done", lambda: True)():
            return
        reply_loop.call_soon_threadsafe(reply_future.set_result, text)

    @staticmethod
    def _parts_to_text(parts: List[Any]) -> str:
        out: List[str] = []
        for p in parts:
            t = getattr(p, "type", None)
            if t == ContentType.TEXT and getattr(p, "text", None):
                out.append(p.text)
            elif t == ContentType.REFUSAL and getattr(p, "refusal", None):
                out.append(p.refusal)
            elif t == ContentType.IMAGE:
                out.append("[图片]")
            elif t == ContentType.FILE:
                out.append("[文件]")
            elif t == ContentType.VIDEO:
                out.append("[视频]")
            elif t == ContentType.AUDIO:
                out.append("[语音]")
        return "\n".join([x for x in out if x and x.strip()]).strip()

    async def _run_process_loop(
        self,
        request: Any,
        to_handle: str,
        send_meta: Dict[str, Any],
    ) -> None:
        _NON_SERIALIZABLE = ("reply_loop", "reply_future")
        request.channel_meta = {
            k: v
            for k, v in (send_meta or {}).items()
            if k not in _NON_SERIALIZABLE
        }
        accumulated_parts: List[Any] = []
        last_response = None

        try:
            async for event in self._process(request):
                obj = getattr(event, "object", None)
                status = getattr(event, "status", None)
                if obj == "message" and status == RunStatus.Completed:
                    parts = self._message_to_content_parts(event)
                    accumulated_parts.extend(parts)
                    self._append_stream_parts(send_meta, parts)
                elif obj == "response":
                    last_response = event
        except Exception:
            logger.exception("wecom process failed")
            reply_text = "An error occurred while processing your request."
            self._mark_stream_finished(send_meta, error=reply_text)
            self._reply_sync(send_meta, reply_text)
            return

        err_msg = self._get_response_error_message(last_response)
        if err_msg:
            reply_text = f"Error: {err_msg}"
            self._mark_stream_finished(send_meta, error=reply_text)
        else:
            reply_text = self._parts_to_text(accumulated_parts)
            if send_meta.get("stream_id") and not (reply_text or "").strip():
                reply_text = "我已收到。"
            self._mark_stream_finished(send_meta, text=reply_text)

        reply_text = (reply_text or "").strip() or "我已收到。"
        bot_prefix = (send_meta or {}).get("bot_prefix", "")
        if bot_prefix and reply_text:
            reply_text = f"{bot_prefix}{reply_text}"

        # Webhook reply path.
        if send_meta.get("reply_future") is not None:
            self._reply_sync(send_meta, reply_text)
        elif self.channel == "wecom":
            logger.debug(
                "wecom passive reply finalized: stream_id=%s content_len=%s",
                send_meta.get("stream_id") or "",
                len(reply_text),
            )
        else:
            try:
                await self.send(to_handle, reply_text, send_meta)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("wecom proactive send failed: %s", exc)
                self._mark_stream_finished(
                    send_meta,
                    error="Failed to deliver message to WeCom.",
                )
                return

        if self._on_reply_sent:
            self._on_reply_sent(
                self.channel,
                request.user_id or "",
                request.session_id or f"{self.channel}:{request.user_id}",
            )

    def _append_stream_parts(
        self,
        send_meta: Dict[str, Any],
        parts: List[Any],
    ) -> None:
        stream_id = str((send_meta or {}).get("stream_id") or "").strip()
        if not stream_id:
            return
        text = self._parts_to_text(parts)
        if not text:
            return
        state = self.stream_store.get(stream_id)
        if state is None:
            return
        if not state.content and (send_meta or {}).get("bot_prefix"):
            text = f"{send_meta['bot_prefix']}{text}"
        state.append_text(text)

    def _mark_stream_finished(
        self,
        send_meta: Dict[str, Any],
        *,
        text: str = "",
        error: str = "",
    ) -> None:
        stream_id = str((send_meta or {}).get("stream_id") or "").strip()
        if not stream_id:
            return
        state = self.stream_store.get(stream_id)
        if state is None:
            return
        final_text = (text or "").strip()
        if final_text and not state.content:
            if (send_meta or {}).get("bot_prefix"):
                final_text = f"{send_meta['bot_prefix']}{final_text}"
            state.append_text(final_text)
        state.mark_finished(error=error)

    @staticmethod
    def _parse_envelope(body_text: str) -> Dict[str, str]:
        trimmed = (body_text or "").strip()
        if not trimmed:
            raise ValueError("empty body")
        if trimmed.startswith("<"):
            return parse_xml_to_dict(trimmed)
        payload = json.loads(trimmed)
        if not isinstance(payload, dict):
            raise ValueError("body is not an object")
        return {
            str(k): "" if v is None else str(v) for k, v in payload.items()
        }

    @staticmethod
    def _parse_plain_message(plaintext: str) -> Dict[str, str]:
        trimmed = (plaintext or "").strip()
        if not trimmed:
            return {}
        if trimmed.startswith("<"):
            xml = parse_xml_to_dict(trimmed)
            content = (
                (
                    parse_xml_to_dict(xml.get("Text", ""))
                    if xml.get("Text")
                    else {}
                ).get("Content")
                or xml.get("Content")
                or ""
            )
            from_block = (
                parse_xml_to_dict(xml.get("From", ""))
                if xml.get("From")
                else {}
            )
            return {
                "msgtype": (xml.get("MsgType") or "").strip().lower(),
                "content": content,
                "from_user": (
                    from_block.get("UserId") or xml.get("FromUserName") or ""
                ).strip(),
                "to_user": (xml.get("ToUserName") or "").strip(),
                "msg_id": (xml.get("MsgId") or "").strip(),
                "chat_type": (xml.get("ChatType") or "").strip().lower(),
                "chat_id": (xml.get("ChatId") or "").strip(),
                "stream_id": (
                    parse_xml_to_dict(xml.get("Stream", "")).get("Id", "")
                    if xml.get("Stream")
                    else ""
                ).strip(),
            }
        payload = json.loads(trimmed)
        if not isinstance(payload, dict):
            return {}
        from_part = payload.get("from") or {}
        text_part = payload.get("text") or {}
        event_part = payload.get("event") or {}
        stream_part = payload.get("stream") or {}
        return {
            "msgtype": str(payload.get("msgtype") or "").strip().lower(),
            "content": str(
                text_part.get("content")
                if isinstance(text_part, dict)
                else payload.get("content") or "",
            ).strip(),
            "from_user": str(
                from_part.get("userid")
                if isinstance(from_part, dict)
                else payload.get("userid") or "",
            ).strip(),
            "to_user": str(payload.get("to_user") or "").strip(),
            "msg_id": str(payload.get("msgid") or "").strip(),
            "chat_type": str(payload.get("chattype") or "").strip().lower(),
            "chat_id": str(payload.get("chatid") or "").strip(),
            "event_type": str(
                event_part.get("eventtype")
                if isinstance(event_part, dict)
                else payload.get("eventtype") or "",
            )
            .strip()
            .lower(),
            "stream_id": str(
                stream_part.get("id")
                if isinstance(stream_part, dict)
                else payload.get("stream_id") or "",
            ).strip(),
        }
