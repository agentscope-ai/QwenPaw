# -*- coding: utf-8 -*-
"""Minimal WeCom channel skeleton for plugin discovery and routing tests."""

from __future__ import annotations

import os
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .constants import DEFAULT_BOT_PREFIX
from .constants import DEFAULT_HEARTBEAT_INTERVAL_SECONDS
from .constants import DEFAULT_PROCESSED_IDS_MAX_ITEMS
from .constants import DEFAULT_RECONNECT_MAX_SECONDS
from .constants import DEFAULT_RECONNECT_MIN_SECONDS
from .constants import DEFAULT_WS_URL
from .media import (
    describe_media_fallback,
    extract_media_descriptor,
    extract_mixed_parts,
)
from .schema import WeComRoute
from .sender import (
    build_active_markdown_command,
    build_active_template_card_command,
    build_file_message,
    build_image_message,
    build_markdown_message,
    build_stream_reply_command,
    build_text_message,
    build_welcome_command,
    parse_send_target,
    target_to_chat_type,
)
from .store import ProcessedMessageStore, RouteStore
from .ws_client import WeComRuntimeClient, WeComWebSocketTransport
from copaw.app.channels.base import BaseChannel, OnReplySent, ProcessHandler
from agentscope_runtime.engine.schemas.agent_schemas import (
    ContentType,
    FileContent,
    ImageContent,
    MessageType,
    RunStatus,
    TextContent,
)

logger = logging.getLogger(__name__)


async def _noop_process(_request):
    """Default process used by tests for minimal instantiation."""

    if False:
        yield _request


class _MemorySender:
    """Minimal sender used by tests before real HTTP transport is added."""

    def __init__(self):
        self.last_target = None
        self.last_payload = None
        self.sent_messages: list[tuple[Any, dict]] = []

    async def send_payload(self, target: Any, payload: dict) -> None:
        self.last_target = target
        self.last_payload = payload
        self.sent_messages.append((target, payload))


class WeComChannel(BaseChannel):
    """Minimal WeCom channel implementation used to grow the plugin safely."""

    channel = "wecom"
    display_name = "WeCom"

    def __init__(
        self,
        process: Optional[ProcessHandler] = None,
        enabled: bool = True,
        bot_prefix: str = DEFAULT_BOT_PREFIX,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
        show_streaming_reply: bool = True,
        dm_policy: str = "open",
        group_policy: str = "open",
        allow_from: Optional[list[str]] = None,
        deny_message: str = "",
        processed_ids_path: Optional[Path] = None,
        route_store_path: Optional[Path] = None,
        processed_ids_max_items: int = DEFAULT_PROCESSED_IDS_MAX_ITEMS,
        sender: Optional[_MemorySender] = None,
        transport: Optional[WeComWebSocketTransport] = None,
        bot_id: str = "",
        bot_secret: str = "",
        ws_url: str = DEFAULT_WS_URL,
        ping_interval_seconds: int = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
        reconnect_min_seconds: int = DEFAULT_RECONNECT_MIN_SECONDS,
        reconnect_max_seconds: int = DEFAULT_RECONNECT_MAX_SECONDS,
        runtime_client_factory: Optional[
            Callable[..., WeComWebSocketTransport]
        ] = None,
        **_kwargs: Any,
    ):
        super().__init__(
            process=process or _noop_process,
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
        self.bot_prefix = bot_prefix or DEFAULT_BOT_PREFIX
        self.show_streaming_reply = bool(show_streaming_reply)
        self.bot_id = str(bot_id or "").strip()
        self.bot_secret = str(bot_secret or "").strip()
        self.ws_url = str(ws_url or DEFAULT_WS_URL).strip() or DEFAULT_WS_URL
        self.ping_interval_seconds = max(0, int(ping_interval_seconds))
        self.reconnect_min_seconds = max(1, int(reconnect_min_seconds))
        self.reconnect_max_seconds = max(
            self.reconnect_min_seconds,
            int(reconnect_max_seconds),
        )
        self._processed_ids = ProcessedMessageStore(
            Path(processed_ids_path) if processed_ids_path else None,
            max_items=processed_ids_max_items,
        )
        self._route_store = RouteStore(
            Path(route_store_path) if route_store_path else None,
        )
        self._sender = sender or _MemorySender()
        self._transport = transport
        self._runtime_client = None
        self._runtime_client_factory = runtime_client_factory or WeComRuntimeClient

    @classmethod
    def from_env(
        cls,
        process: ProcessHandler,
        on_reply_sent: OnReplySent = None,
    ) -> "WeComChannel":
        allow_from_env = os.getenv("WECOM_ALLOW_FROM", "")
        allow_from = [
            item.strip()
            for item in allow_from_env.split(",")
            if item.strip()
        ]
        return cls(
            process=process,
            enabled=os.getenv("WECOM_CHANNEL_ENABLED", "0") == "1",
            bot_prefix=os.getenv("WECOM_BOT_PREFIX", DEFAULT_BOT_PREFIX),
            on_reply_sent=on_reply_sent,
            dm_policy=os.getenv("WECOM_DM_POLICY", "open"),
            group_policy=os.getenv("WECOM_GROUP_POLICY", "open"),
            show_streaming_reply=(
                os.getenv("WECOM_SHOW_STREAMING_REPLY", "1") != "0"
            ),
            allow_from=allow_from,
            deny_message=os.getenv("WECOM_DENY_MESSAGE", ""),
            processed_ids_path=os.getenv("WECOM_PROCESSED_IDS_PATH", ""),
            route_store_path=os.getenv("WECOM_ROUTE_STORE_PATH", ""),
            bot_id=os.getenv("WECOM_BOT_ID", ""),
            bot_secret=os.getenv("WECOM_BOT_SECRET", ""),
            ws_url=os.getenv("WECOM_WS_URL", DEFAULT_WS_URL),
            ping_interval_seconds=os.getenv(
                "WECOM_PING_INTERVAL_SECONDS",
                str(DEFAULT_HEARTBEAT_INTERVAL_SECONDS),
            ),
            reconnect_min_seconds=os.getenv(
                "WECOM_RECONNECT_MIN_SECONDS",
                str(DEFAULT_RECONNECT_MIN_SECONDS),
            ),
            reconnect_max_seconds=os.getenv(
                "WECOM_RECONNECT_MAX_SECONDS",
                str(DEFAULT_RECONNECT_MAX_SECONDS),
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
    ) -> "WeComChannel":
        return cls(
            process=process,
            enabled=getattr(config, "enabled", True),
            bot_prefix=getattr(config, "bot_prefix", DEFAULT_BOT_PREFIX),
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            filter_thinking=filter_thinking,
            show_streaming_reply=getattr(config, "show_streaming_reply", True),
            dm_policy=getattr(config, "dm_policy", "open"),
            group_policy=getattr(config, "group_policy", "open"),
            allow_from=getattr(config, "allow_from", []),
            deny_message=getattr(config, "deny_message", ""),
            processed_ids_path=getattr(config, "processed_ids_path", ""),
            route_store_path=getattr(config, "route_store_path", ""),
            bot_id=getattr(config, "bot_id", ""),
            bot_secret=getattr(config, "bot_secret", ""),
            ws_url=getattr(config, "ws_url", DEFAULT_WS_URL),
            ping_interval_seconds=getattr(
                config,
                "ping_interval_seconds",
                DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
            ),
            reconnect_min_seconds=getattr(
                config,
                "reconnect_min_seconds",
                DEFAULT_RECONNECT_MIN_SECONDS,
            ),
            reconnect_max_seconds=getattr(
                config,
                "reconnect_max_seconds",
                DEFAULT_RECONNECT_MAX_SECONDS,
            ),
        )

    async def start(self) -> None:
        """Start the optional WeCom long-connection runtime."""

        if not self.enabled:
            return
        if self._runtime_client is not None:
            await self._runtime_client.start()
            return
        if self._transport is not None:
            return
        self._validate_runtime_credentials()
        runtime = self._runtime_client_factory(
            bot_id=self.bot_id,
            secret=self.bot_secret,
            ws_url=self.ws_url,
            ping_interval_seconds=self.ping_interval_seconds,
            reconnect_min_seconds=self.reconnect_min_seconds,
            reconnect_max_seconds=self.reconnect_max_seconds,
            on_payload=self._handle_incoming_payload,
        )
        self._runtime_client = runtime
        self._transport = runtime
        await runtime.start()

    async def stop(self) -> None:
        """Stop the runtime client if this channel created one."""

        if self._runtime_client is None:
            return
        runtime = self._runtime_client
        self._runtime_client = None
        await runtime.stop()
        if self._transport is runtime:
            self._transport = None

    def _validate_runtime_credentials(self) -> None:
        """Fail fast when runtime mode is enabled without required credentials."""

        if not self.bot_id:
            raise ValueError("WECOM_BOT_ID is required when WeCom runtime is enabled")
        if not self.bot_secret:
            raise ValueError(
                "WECOM_BOT_SECRET is required when WeCom runtime is enabled"
            )

    async def _handle_incoming_payload(self, payload: Dict[str, Any]) -> None:
        """Forward native payloads to the manager queue when configured."""

        enqueue = getattr(self, "_enqueue", None)
        if enqueue is None:
            return
        enqueue(payload)

    def resolve_session_id(
        self,
        sender_id: str,
        channel_meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Map user/group metadata to stable WeCom session ids."""

        meta = channel_meta or {}
        chat_type = str(meta.get("chat_type") or meta.get("chattype") or "")
        if chat_type == "group":
            chat_id = str(meta.get("chat_id") or meta.get("chatid") or "")
            if chat_id:
                return f"{self.channel}:chat:{chat_id}"
        return f"{self.channel}:user:{sender_id}"

    def to_handle_from_target(self, *, user_id: str, session_id: str) -> str:
        """Convert session or user identifiers into send handles."""

        if session_id.startswith(f"{self.channel}:"):
            return session_id
        return f"{self.channel}:user:{user_id}"

    def get_to_handle_from_request(self, request: Any) -> str:
        """Resolve WeCom replies to a valid handle instead of a bare user id."""

        session_id = str(getattr(request, "session_id", "") or "")
        user_id = str(getattr(request, "user_id", "") or "")
        return self.to_handle_from_target(user_id=user_id, session_id=session_id)

    def build_agent_request_from_native(self, native_payload: Any):
        payload = native_payload if isinstance(native_payload, dict) else {}
        body = payload.get("body") or {}
        if not isinstance(body, dict):
            body = {}
        message = self._normalize_incoming_message(payload)
        if self._processed_ids.mark_seen(message["message_id"]):
            return None
        self._save_route(message)
        content_parts = self._build_content_parts(body)
        request = self.build_agent_request_from_user_content(
            channel_id=self.channel,
            sender_id=message["sender_id"],
            session_id=self.resolve_session_id(message["sender_id"], message),
            content_parts=content_parts,
            channel_meta=message,
        )
        request.channel_meta = message
        return request

    async def _consume_one_request(self, payload: Any) -> None:
        """Skip duplicate native payloads safely before delegating to BaseChannel."""

        request = self._payload_to_request(payload)
        if request is None:
            return
        await super()._consume_one_request(request)

    async def _run_process_loop(
        self,
        request: Any,
        to_handle: str,
        send_meta: Dict[str, Any],
    ) -> None:
        """Use waiting-first stream replies for WeCom passive responses."""

        if not self._should_stream_reply(send_meta):
            await super()._run_process_loop(request, to_handle, send_meta)
            return

        target = parse_send_target(to_handle)
        req_id = str(send_meta.get("req_id") or "").strip()
        stream_id = self._new_request_id()
        latest_text = ""
        last_response = None

        await self._dispatch_payload(
            target,
            build_stream_reply_command(
                req_id,
                stream_id=stream_id,
                content="正在生成回复...",
                finish=False,
            ),
        )

        try:
            async for event in self._process(request):
                obj = getattr(event, "object", None)
                status = getattr(event, "status", None)
                if obj == "message" and status == RunStatus.Completed:
                    if self._is_auxiliary_message(event):
                        await self.send_message_content(
                            to_handle,
                            event,
                            send_meta,
                        )
                        continue
                    text = self._extract_stream_text(event)
                    if text:
                        if latest_text:
                            await self._dispatch_payload(
                                target,
                                build_stream_reply_command(
                                    req_id,
                                    stream_id=stream_id,
                                    content=latest_text,
                                    finish=False,
                                ),
                            )
                        latest_text = text
                elif obj == "response":
                    last_response = event
                    await self.on_event_response(request, event)

            err_msg = self._get_response_error_message(last_response)
            if err_msg:
                latest_text = f"Error: {err_msg}"

            await self._dispatch_payload(
                target,
                build_stream_reply_command(
                    req_id,
                    stream_id=stream_id,
                    content=latest_text or "正在生成回复...",
                    finish=True,
                ),
            )
            if self._on_reply_sent:
                args = self.get_on_reply_sent_args(request, to_handle)
                self._on_reply_sent(self.channel, *args)
        except Exception:
            logger.exception("channel consume_one failed")
            await self._dispatch_payload(
                target,
                build_stream_reply_command(
                    req_id,
                    stream_id=stream_id,
                    content="An error occurred while processing your request.",
                    finish=True,
                ),
            )

    def _should_stream_reply(self, send_meta: Dict[str, Any]) -> bool:
        """Only passive WeCom replies use the waiting-first stream flow."""

        return bool(
            self.show_streaming_reply
            and self._transport is not None
            and str(send_meta.get("req_id") or "").strip()
            and str(send_meta.get("event_type") or "").strip() != "enter_chat"
        )

    def _extract_stream_text(self, event: Any) -> str:
        """Render assistant body text for streaming updates only."""

        if getattr(event, "type", None) != MessageType.MESSAGE:
            return ""
        parts = self._message_to_content_parts(event)
        text_parts = []
        for part in parts:
            part_type = getattr(part, "type", None)
            if part_type == ContentType.TEXT and getattr(part, "text", None):
                text_parts.append(part.text or "")
            elif (
                part_type == ContentType.REFUSAL
                and getattr(part, "refusal", None)
            ):
                text_parts.append(part.refusal or "")
        body = "\n".join(chunk for chunk in text_parts if chunk).strip()
        prefix = self.bot_prefix or ""
        if prefix and body:
            return f"{prefix}{body}"
        return body

    def _is_auxiliary_message(self, event: Any) -> bool:
        """Tool and reasoning events are sent as standalone replies."""

        return getattr(event, "type", None) in {
            MessageType.FUNCTION_CALL,
            MessageType.FUNCTION_CALL_OUTPUT,
            MessageType.PLUGIN_CALL,
            MessageType.PLUGIN_CALL_OUTPUT,
            MessageType.MCP_TOOL_CALL,
            MessageType.MCP_TOOL_CALL_OUTPUT,
            MessageType.REASONING,
        }

    def _normalize_incoming_message(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        headers = payload.get("headers") or {}
        body = payload.get("body") or {}
        from_user = body.get("from") or {}
        sender_id = str(from_user.get("userid") or "").strip()
        chat_type = str(body.get("chattype") or "single").strip() or "single"
        chat_id = str(body.get("chatid") or "").strip()
        msg_type = str(body.get("msgtype") or "").strip()
        message_id = str(body.get("msgid") or "").strip()
        return {
            "req_id": str(headers.get("req_id") or "").strip(),
            "message_id": message_id,
            "sender_id": sender_id,
            "chat_type": chat_type,
            "chat_id": chat_id,
            "msg_type": msg_type,
            "raw_body": body,
        }

    def _save_route(self, meta: Dict[str, Any]) -> None:
        session_id = self.resolve_session_id(meta["sender_id"], meta)
        chat_type = meta["chat_type"]
        target_type = "chat" if chat_type == "group" and meta["chat_id"] else "user"
        target_id = meta["chat_id"] if target_type == "chat" else meta["sender_id"]
        if not target_id:
            return
        self._route_store.save_route(
            WeComRoute(
                session_id=session_id,
                target_type=target_type,
                target_id=target_id,
                chat_type=chat_type,
                last_seen_at=int(time.time()),
            )
        )

    def _build_content_parts(self, body: Dict[str, Any]) -> list[TextContent]:
        msg_type = str(body.get("msgtype") or "").strip()
        if msg_type == "text":
            text = str(((body.get("text") or {}).get("content")) or "").strip()
            return [self._text_part(text)]
        if msg_type == "mixed":
            parts = []
            for item in extract_mixed_parts(body):
                item_type = str(item.get("type") or "").strip()
                if item_type == "text":
                    parts.append(self._text_part(str(item.get("text") or "").strip()))
                else:
                    parts.append(
                        self._text_part(
                            describe_media_fallback(
                                extract_media_descriptor(
                                    {"msgtype": item_type, item_type: item},
                                )
                            )
                        )
                    )
            return parts or [self._text_part("")]
        descriptor = extract_media_descriptor(body)
        if descriptor is not None:
            return [self._text_part(describe_media_fallback(descriptor))]
        return [self._text_part("")]

    def _text_part(self, text: str) -> TextContent:
        return TextContent(type=ContentType.TEXT, text=text)

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send one text body to an already-resolved WeCom target."""

        target = parse_send_target(to_handle)
        payload = self._build_outgoing_payload(target, text, meta)
        await self._dispatch_payload(target, payload)

    async def send_content_parts(
        self,
        to_handle: str,
        parts: list[Any],
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send text first, then media payloads, using the minimal sender."""

        target = parse_send_target(to_handle)
        text_chunks: list[str] = []
        for part in parts:
            part_type = getattr(part, "type", None)
            if part_type == ContentType.TEXT and getattr(part, "text", None):
                text_chunks.append(part.text or "")
            elif (
                part_type == ContentType.REFUSAL
                and getattr(part, "refusal", None)
            ):
                text_chunks.append(part.refusal or "")
        body = "\n".join(chunk for chunk in text_chunks if chunk).strip()
        if body:
            await self._dispatch_payload(
                target,
                self._build_outgoing_payload(target, body, meta),
            )
        for part in parts:
            payload = self._build_payload_from_part(part)
            if payload is None:
                continue
            await self._dispatch_payload(target, payload)

    async def _dispatch_payload(self, target: Any, payload: dict) -> None:
        """Send through transport when available, otherwise use in-memory sender."""

        logger.info(
            "wecom dispatch payload: cmd=%s req_id=%s msgtype=%s target_type=%s target_id=%s",
            payload.get("cmd") or "local",
            ((payload.get("headers") or {}).get("req_id") or ""),
            ((payload.get("body") or payload).get("msgtype") or ""),
            getattr(target, "target_type", ""),
            getattr(target, "target_id", ""),
        )
        if self._transport is not None:
            await self._transport.send_json(payload)
            return
        await self._sender.send_payload(target, payload)

    def _build_outgoing_payload(
        self,
        target: Any,
        text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> dict:
        """Choose the correct ws command or local payload for the outgoing text."""

        if self._transport is None:
            return self._build_local_text_payload(text, meta)
        return self._build_transport_payload(target, text, meta)

    def _build_local_text_payload(
        self,
        text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> dict:
        """Build payloads for the fallback in-memory sender."""

        send_meta = meta or {}
        prefix = send_meta.get("bot_prefix") or self.bot_prefix or ""
        body = f"{prefix}{text}" if text else prefix
        mentioned_list = send_meta.get("mentioned_list")
        msgtype = str(send_meta.get("msgtype") or "").strip().lower()
        if msgtype == "markdown":
            return build_markdown_message(body)
        return build_text_message(body, mentioned_list=mentioned_list)

    def _build_transport_payload(
        self,
        target: Any,
        text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> dict:
        """Build official WeCom long-connection command payloads."""

        send_meta = meta or {}
        prefix = send_meta.get("bot_prefix") or self.bot_prefix or ""
        body = f"{prefix}{text}" if text else prefix
        req_id = str(send_meta.get("req_id") or "").strip()
        if req_id:
            if str(send_meta.get("event_type") or "").strip() == "enter_chat":
                message_body = self._build_reply_message_body(body, send_meta)
                return build_welcome_command(req_id, message_body)
            return build_stream_reply_command(
                req_id,
                stream_id=self._new_request_id(),
                content=body,
                finish=True,
            )

        request_id = self._new_request_id()
        template_card = send_meta.get("template_card")
        if isinstance(template_card, dict):
            return build_active_template_card_command(
                request_id,
                chat_id=target.target_id,
                chat_type=target_to_chat_type(target),
                template_card=template_card,
            )
        markdown_body = self._build_active_markdown_body(body, send_meta)
        return build_active_markdown_command(
            request_id,
            chat_id=target.target_id,
            chat_type=target_to_chat_type(target),
            content=markdown_body["markdown"]["content"],
        )

    def _build_reply_message_body(
        self,
        text: str,
        meta: Dict[str, Any],
    ) -> dict:
        """Reply commands can send text or markdown bodies."""

        msgtype = str(meta.get("msgtype") or "").strip().lower()
        if msgtype == "markdown":
            return build_markdown_message(text)
        mentioned_list = meta.get("mentioned_list")
        return build_text_message(text, mentioned_list=mentioned_list)

    def _build_active_markdown_body(
        self,
        text: str,
        meta: Dict[str, Any],
    ) -> dict:
        """Active push only supports markdown/template_card in long connection mode."""

        msgtype = str(meta.get("msgtype") or "").strip().lower()
        if msgtype == "markdown":
            return build_markdown_message(text)
        return build_markdown_message(text)

    def _new_request_id(self) -> str:
        return uuid.uuid4().hex

    def _build_payload_from_part(self, part: Any) -> Optional[dict]:
        """Build a send payload from one non-text content part."""

        part_type = getattr(part, "type", None)
        if part_type == ContentType.IMAGE:
            media_id = self._resolve_image_media_id(part)
            if media_id:
                return build_image_message(media_id)
            return build_text_message("[Image]")
        if part_type == ContentType.FILE:
            media_id = self._resolve_file_media_id(part)
            if media_id:
                return build_file_message(media_id)
            fallback = getattr(part, "filename", None) or "[File]"
            return build_text_message(str(fallback))
        if part_type in (ContentType.TEXT, ContentType.REFUSAL):
            return None
        return build_text_message(f"[{str(part_type or 'content').title()}]")

    def _resolve_image_media_id(self, part: ImageContent) -> str:
        return str(
            getattr(part, "msg_id", None)
            or getattr(part, "image_url", None)
            or ""
        ).strip()

    def _resolve_file_media_id(self, part: FileContent) -> str:
        return str(
            getattr(part, "file_id", None)
            or getattr(part, "file_url", None)
            or getattr(part, "filename", None)
            or ""
        ).strip()
