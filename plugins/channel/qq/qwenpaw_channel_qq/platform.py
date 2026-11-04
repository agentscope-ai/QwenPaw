# -*- coding: utf-8 -*-
"""Native QQ HTTP and gateway transport owned by one shared-worker instance."""

from __future__ import annotations

import asyncio
from collections import deque
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import hashlib
import json
import os
import threading
import time
import uuid

import httpx

from qwenpaw.app.channels.utils import split_text
from qwenpaw.channel_protocol.models import ContentSource

from .cards.dispatcher import QQCardHandler
from .cards.tool_guard import (
    ApprovalCardBinding,
    CardCache,
    build_approval_keyboard,
    build_resolved_text,
)
from .errors import QQApiError, QQDeliveryError
from .formatting import (
    _IMAGE_TAG_PATTERN,
    _aggressive_sanitize_qq_text,
    _as_bool,
    _find_quoted_element,
    _is_url_content_error,
    _resolve_send_path,
    _sanitize_qq_text,
    _should_plaintext_fallback_from_markdown,
    resolve_session_id,
)
from .media import QQMedia

OP_DISPATCH, OP_HEARTBEAT, OP_IDENTIFY = 0, 1, 2
OP_RESUME, OP_RECONNECT, OP_INVALID_SESSION = 6, 7, 9
OP_HELLO, OP_HEARTBEAT_ACK = 10, 11
INTENT_PUBLIC_GUILD_MESSAGES = 1 << 30
INTENT_DIRECT_MESSAGE = 1 << 12
INTENT_GROUP_AND_C2C = 1 << 25
INTENT_GUILD_MEMBERS = 1 << 1
INTENT_INTERACTION = 1 << 26
RECONNECT_DELAYS = [1, 2, 5, 10, 30, 60]
RATE_LIMIT_DELAY, QUICK_DISCONNECT_THRESHOLD, MAX_QUICK_DISCONNECT_COUNT = (
    60,
    5,
    3,
)
DEFAULT_API_BASE = "https://api.sgroup.qq.com"
TOKEN_URL = "https://bots.qq.com/app/getAppAccessToken"
_MESSAGE_EVENT_SPECS = {
    "C2C_MESSAGE_CREATE": ("c2c", ("user_openid", "id"), ()),
    "GROUP_AT_MESSAGE_CREATE": (
        "group",
        ("member_openid", "id"),
        ("group_openid",),
    ),
    "AT_MESSAGE_CREATE": (
        "guild",
        ("id", "username"),
        ("channel_id", "guild_id"),
    ),
    "DIRECT_MESSAGE_CREATE": (
        "dm",
        ("id", "username"),
        ("channel_id", "guild_id"),
    ),
}


def _get_api_base():
    return os.getenv("QQ_API_BASE", DEFAULT_API_BASE).rstrip("/")


def _get_token_url():
    return os.getenv("QQ_TOKEN_URL", TOKEN_URL)


def _is_recoverable_ws_os_error(exc):
    return isinstance(
        exc,
        (ConnectionAbortedError, ConnectionResetError, BrokenPipeError),
    ) or getattr(exc, "winerror", None) in {10053, 10054, 10060}


@dataclass
class _WSState:
    session_id: str | None = None
    last_seq: int | None = None
    reconnect_attempts: int = 0
    last_connect_time: float = 0.0
    quick_disconnect_count: int = 0
    identify_fail_count: int = 0
    should_refresh_token: bool = False


class _HeartbeatController:
    """Retain timers until their actual thread exit, including a racing ping."""

    def __init__(self, ws, stop_event, state):
        self._ws, self._stop_event, self._state = ws, stop_event, state
        self._interval = None
        self._timer = None
        self._timers = set()
        self._lock = threading.RLock()
        self._closed = False

    def start(self, interval_ms):
        self._interval = float(interval_ms)
        if self._interval <= 0:
            raise ValueError("INVALID_HEARTBEAT_INTERVAL")
        self._schedule()

    def _schedule(self):
        with self._lock:
            if self._closed or self._stop_event.is_set():
                return
            self._timers = {t for t in self._timers if t.is_alive()}
            timer = threading.Timer(self._interval / 1000, self._send_ping)
            timer.daemon = True
            self._timer = timer
            self._timers.add(timer)
            timer.start()

    def _send_ping(self):
        try:
            if (
                not self._closed
                and not self._stop_event.is_set()
                and self._ws.connected
            ):
                self._ws.send(
                    json.dumps(
                        {"op": OP_HEARTBEAT, "d": self._state.last_seq},
                    ),
                )
        except Exception:
            pass
        finally:
            self._schedule()

    def stop(self):
        with self._lock:
            self._closed = True
            for timer in self._timers:
                timer.cancel()

    def join(self, timeout=2):
        self.stop()
        deadline = time.monotonic() + timeout
        for timer in tuple(self._timers):
            if timer is not threading.current_thread():
                timer.join(max(0, deadline - time.monotonic()))
        if any(timer.is_alive() for timer in self._timers):
            raise RuntimeError("QQ_HEARTBEAT_STOP_INCOMPLETE")


class SequenceRegistry:
    def __init__(self):
        self._msg_seq = {}
        self._lock = threading.Lock()

    def next(self, key):
        with self._lock:
            value = self._msg_seq.get(key, 0) + 1
            self._msg_seq[key] = value
            if len(self._msg_seq) > 1000:
                for old in list(self._msg_seq)[:500]:
                    del self._msg_seq[old]
            return value


@dataclass
class _NativePlan:
    delivery_id: str
    record: object
    attempts: list = field(default_factory=list)
    effected: bool = False


class QQPlatform:
    def __init__(self, config, on_event, on_state, on_callback=None):
        self.config = dict(config)
        self.on_event, self.on_state = on_event, on_state
        self.on_callback = on_callback or on_event
        self._loop = None
        self._http = None
        self._sync_http = None
        self._ws_thread = None
        self._ws = None
        self._stop_event = threading.Event()
        self._stopping = False
        self._epoch = 0
        self._state = _WSState()
        self._heartbeats = set()
        self._heartbeat_lock = threading.Lock()
        self._tasks, self._io_tasks, self._callbacks, self._ack_tasks = (
            set(),
            set(),
            set(),
            set(),
        )
        self._cancelled_tasks = set()
        self._bridges = set()
        self._bridge_lock = threading.Lock()
        self._close_errors = []
        self._stop_task = None
        self._http_close_error = None
        self._http_closed = False
        self._thread_error = None
        self._token_cache = None
        self._token_lock = threading.Lock()
        self._seen_event_ids = deque(maxlen=256)
        self._sequences = SequenceRegistry()
        self._plan = ContextVar("qq_native_plan", default=None)
        self._cards = CardCache()
        self._staged_cards = {}
        self._identity = None
        self._card_handler = QQCardHandler(self)
        self.media = QQMedia(self, self.config)

    async def start(self):
        if not self.config.get("app_id") or not self.config.get(
            "client_secret",
        ):
            raise ValueError("QQ_CREDENTIALS_REQUIRED")
        self._loop = asyncio.get_running_loop()
        self._http = httpx.AsyncClient(timeout=30)
        self._stop_event.clear()
        self._ws_thread = threading.Thread(
            target=self._run_ws_forever,
            name="qq-gateway",
            daemon=True,
        )
        self._ws_thread.start()

    @staticmethod
    async def _settle(task):
        cancelled = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled = True
            except BaseException:
                break
        if cancelled:
            # Retrieve a task exception without masking cancellation.
            if task.done() and not task.cancelled():
                task.exception()
            raise asyncio.CancelledError
        return task.result()

    async def _owned(self, awaitable, group, *, cancel=True):
        task = asyncio.create_task(awaitable)
        group.add(task)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if (
                cancel
                and not task.done()
                and task not in self._cancelled_tasks
            ):
                self._cancelled_tasks.add(task)
                task.cancel()
            try:
                await self._settle(task)
            except BaseException:
                pass
            raise
        finally:
            if task.done():
                group.discard(task)
                self._cancelled_tasks.discard(task)

    async def _file_io(self, function, *args):
        return await self._owned(
            asyncio.to_thread(function, *args),
            self._io_tasks,
            cancel=False,
        )

    async def _request(self, method, url, **kwargs):
        if self._stopping or self._http is None:
            raise QQDeliveryError("NOT_CONNECTED")
        try:
            request = self._http.build_request(method, url, **kwargs)
            plan = self._plan.get()
            if plan is not None and method not in {"GET", "HEAD"}:
                content = request.read()
                native = {
                    "method": method,
                    "path": request.url.raw_path.decode("ascii"),
                    "body_sha256": hashlib.sha256(content).hexdigest(),
                    "body_bytes": str(len(content)),
                    "content_type": request.headers.get("Content-Type", ""),
                    "delivery_id": plan.delivery_id,
                }
                body = kwargs.get("json")
                if isinstance(body, dict):
                    for key in ("msg_id", "msg_seq", "msg_type", "file_type"):
                        if key in body:
                            native[key] = str(body[key])
                # Freeze the exact built native bytes before effects. Only digests,
                # never secrets or large base64 payloads, go in durable receipts.
                plan.attempts.append((native, content))
                try:
                    await plan.record(len(plan.attempts), native)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    raise QQDeliveryError("LOCAL_ADMISSION_FAILED") from exc
            response = await self._owned(self._http.send(request), self._tasks)
            return response
        except QQDeliveryError:
            raise
        except httpx.RequestError as exc:
            raise QQDeliveryError(
                "PLATFORM_RESULT_UNKNOWN",
                side_effect_possible=True,
            ) from exc

    async def _api_request_async(self, method, path, body=None, **kwargs):
        token = await self._get_access_token_async()
        headers = {"Authorization": f"QQBot {token}"}
        if body is not None:
            kwargs["json"] = body
        response = await self._request(
            method,
            _get_api_base() + path,
            headers=headers,
            **kwargs,
        )
        try:
            data = response.json() if response.content.strip() else {}
        except ValueError:
            data = {}
        if response.status_code >= 400:
            raise QQApiError(path=path, status=response.status_code, data=data)
        if not isinstance(data, dict):
            raise QQDeliveryError(
                "PLATFORM_RESULT_UNKNOWN",
                side_effect_possible=True,
            )
        plan = self._plan.get()
        if plan is not None and method not in {"GET", "HEAD"}:
            plan.effected = True
        return data

    def _cached_token(self):
        with self._token_lock:
            cached = self._token_cache
            return (
                cached["token"]
                if cached and time.time() < cached["expires_at"] - 300
                else None
            )

    def _save_token(self, data):
        token = data.get("access_token")
        if not isinstance(token, str) or not token:
            raise QQDeliveryError("QQ_TOKEN_INVALID")
        expires = int(data.get("expires_in", 7200))
        with self._token_lock:
            self._token_cache = {
                "token": token,
                "expires_at": time.time() + expires,
            }
        return token

    def _get_access_token_sync(self):
        token = self._cached_token()
        if token:
            return token
        response = self._sync_http.post(
            _get_token_url(),
            json={
                "appId": self.config["app_id"],
                "clientSecret": self.config["client_secret"],
            },
        )
        response.raise_for_status()
        return self._save_token(response.json())

    async def _get_access_token_async(self):
        token = self._cached_token()
        if token:
            return token
        # Token preparation is not a native message attempt in a delivery plan.
        plan_token = self._plan.set(None)
        try:
            response = await self._request(
                "POST",
                _get_token_url(),
                json={
                    "appId": self.config["app_id"],
                    "clientSecret": self.config["client_secret"],
                },
            )
            if response.status_code >= 400:
                raise QQDeliveryError("QQ_TOKEN_REJECTED")
            try:
                return self._save_token(response.json())
            except (ValueError, TypeError, AttributeError) as exc:
                raise QQDeliveryError("QQ_TOKEN_INVALID") from exc
        finally:
            self._plan.reset(plan_token)

    def _clear_token_cache(self):
        with self._token_lock:
            self._token_cache = None

    def _next_seq(self, route, msg_id, fallback):
        key = (
            ("reply", msg_id)
            if msg_id
            else (
                "proactive",
                route.get("message_type"),
                route.get("sender_id"),
                route.get("group_openid"),
                route.get("channel_id"),
                route.get("guild_id"),
                route.get("response_handle"),
                fallback,
            )
        )
        return self._sequences.next(key)

    @asynccontextmanager
    async def delivery(self, delivery_id, record):
        plan = _NativePlan(delivery_id, record)
        token = self._plan.set(plan)
        try:
            yield plan
        except QQDeliveryError as exc:
            if plan.effected and not exc.side_effect_possible:
                raise QQDeliveryError(
                    exc.reason_code,
                    side_effect_possible=True,
                ) from exc
            raise
        finally:
            self._plan.reset(token)

    async def _dispatch_text(self, route, text, markdown):
        path, use_seq, key = _resolve_send_path(
            route["message_type"],
            route.get("sender_id"),
            route.get("channel_id"),
            route.get("group_openid"),
            route.get("guild_id"),
        )
        body = (
            {"markdown": {"content": text}} if markdown else {"content": text}
        )
        msg_id = route.get("message_id")
        if use_seq:
            body.update(
                msg_type=2 if markdown else 0,
                msg_seq=self._next_seq(route, msg_id, key),
            )
        if msg_id:
            body["msg_id"] = msg_id
        return await self._api_request_async("POST", path, body)

    async def _send_text_with_fallback(self, route, text, markdown):
        try:
            return await self._dispatch_text(route, text, markdown)
        except QQApiError as exc:
            if exc.side_effect_possible:
                raise
            if markdown and not _should_plaintext_fallback_from_markdown(exc):
                raise
            if markdown:
                plain, _ = _sanitize_qq_text(text)
                try:
                    return await self._dispatch_text(route, plain, False)
                except QQApiError as second:
                    exc = second
            if 400 <= exc.status < 500 and _is_url_content_error(exc):
                plain, _ = _aggressive_sanitize_qq_text(text)
                return await self._dispatch_text(route, plain, False)
            raise exc

    @staticmethod
    def _receipt(route, ids):
        return {
            "message_ids": json.dumps(ids),
            "message_type": route["message_type"],
        }

    @staticmethod
    def _append_id(ids, value):
        if isinstance(value, dict) and value.get("id") is not None:
            ids.append(str(value["id"]))

    async def send_parts(self, route, parts, source=None):
        source = getattr(source, "value", source) or "content_parts"
        texts = [
            p.get("text") or p.get("refusal")
            for p in parts
            if p.get("type") in {"text", "refusal"}
            and (p.get("text") or p.get("refusal"))
        ]
        media = [
            p
            for p in parts
            if p.get("type") in {"image", "audio", "video", "file"}
        ]
        if any(
            p.get("type")
            not in {"text", "refusal", "image", "audio", "video", "file"}
            for p in parts
        ):
            raise QQDeliveryError("CONTENT_TYPE_UNSUPPORTED")
        markdown = _as_bool(
            route.get(
                "markdown_enabled",
                self.config.get("markdown_enabled", True),
            ),
        )
        body = "\n".join(texts).strip()
        inline = []
        if source == "direct":
            if not markdown:
                body, _ = _sanitize_qq_text(body)
            inline = _IMAGE_TAG_PATTERN.findall(body)
            body = _IMAGE_TAG_PATTERN.sub("", body).strip()
        ids = []
        sent = False
        for chunk in split_text(body) if body else ():
            self._append_id(
                ids,
                await self._send_text_with_fallback(route, chunk, markdown),
            )
            sent = True
        for url in inline:
            if route["message_type"] not in {"c2c", "group"}:
                raise QQDeliveryError("MEDIA_TYPE_UNSUPPORTED")
            self._append_id(
                ids,
                await self.media.send(
                    route,
                    {"type": "image", "image_url": url},
                    reply=not sent,
                    inline=True,
                ),
            )
            # Legacy direct inline images all share the text-sent flag.
        for part in media:
            self._append_id(
                ids,
                await self.media.send(
                    route,
                    part,
                    reply=source != "media" and not sent,
                ),
            )
            sent = True
        return self._receipt(route, ids)

    async def send_approval(self, route, params, identity):
        approval = params.approval
        nonce = uuid.uuid4().hex
        self._identity = identity
        keyboard = build_approval_keyboard(
            request_id=approval.request_id,
            tool_name=approval.tool_name,
            severity=approval.severity.value,
            session_ctx={"bid": nonce},
        )
        body_text = "".join(
            p.get("text", "")
            for p in params.content_parts
            if p.get("type") == "text"
        )
        path, use_seq, fallback = _resolve_send_path(
            route["message_type"],
            route.get("sender_id"),
            route.get("channel_id"),
            route.get("group_openid"),
            route.get("guild_id"),
        )
        body = {
            "markdown": {"content": body_text or "🛡️ Tool Approval Required"},
            "keyboard": keyboard,
            "msg_type": 2,
        }
        msg_id = route.get("message_id")
        if use_seq:
            body["msg_seq"] = self._next_seq(route, msg_id, fallback)
        if msg_id:
            body["msg_id"] = msg_id
        value = await self._api_request_async("POST", path, body)
        native_id = value.get("id")
        if (
            not isinstance(native_id, (str, int))
            or isinstance(native_id, bool)
            or not str(native_id)
        ):
            raise QQDeliveryError(
                "APPROVAL_SOURCE_UNKNOWN",
                side_effect_possible=True,
            )
        binding = ApprovalCardBinding(
            nonce,
            approval.request_id,
            approval.tool_name,
            str(native_id),
            tuple(sorted(route.items())),
            params.to_handle,
            params.delivery_id,
            identity.instance_id,
            identity.generation,
        )
        self._staged_cards[params.delivery_id] = binding
        return self._receipt(route, [str(native_id)])

    def complete_card_delivery(self, delivery_id, acknowledged):
        binding = self._staged_cards.pop(delivery_id, None)
        if binding is not None and acknowledged:
            self._cards.register(binding)

    @staticmethod
    def _operator(event):
        data = event.get("data") or {}
        resolved = data.get("resolved") if isinstance(data, dict) else None
        resolved = resolved if isinstance(resolved, dict) else {}
        return str(
            event.get("group_member_openid")
            or event.get("user_openid")
            or resolved.get("user_id")
            or "",
        )

    async def _ack_interaction(self, interaction_id, code=0):
        if not interaction_id:
            return
        try:
            await self._api_request_async(
                "PUT",
                f"/interactions/{interaction_id}",
                {"code": code},
            )
        except QQDeliveryError:
            pass

    def _native_callback_route(self, event, actor):
        if event.get("group_openid"):
            kind = "group"
        elif event.get("guild_id"):
            kind = "dm" if event.get("chat_type") in {2, "dm"} else "guild"
        else:
            kind = "c2c"
        route = {"message_type": kind, "sender_id": actor}
        route.update(
            {
                k: str(event[k])
                for k in ("group_openid", "channel_id", "guild_id")
                if event.get(k)
            },
        )
        _resolve_send_path(
            kind,
            actor,
            route.get("channel_id"),
            route.get("group_openid"),
            route.get("guild_id"),
        )
        route["session_id"] = resolve_session_id(actor, route)
        route["root_session_id"] = route["session_id"]
        return route

    async def _handle_approval(self, event, parsed):
        actor = self._operator(event)
        if not actor:
            await self._ack_interaction(str(event.get("id") or ""), 4)
            return False
        nonce = str(parsed["session_ctx"].get("bid") or "")
        binding = self._cards.bindings.get(nonce)
        valid = (
            binding is not None
            and self._identity is not None
            and binding.request_id == parsed["request_id"]
            and binding.instance_id == self._identity.instance_id
            and binding.generation == self._identity.generation
        )
        if valid:
            route = dict(binding.route)
            # Compare all native source coordinates actually supplied by QQ.
            native_data = event.get("data")
            resolved = (
                native_data.get("resolved")
                if isinstance(native_data, dict)
                else None
            )
            for native_source in (event, native_data, resolved):
                if not isinstance(native_source, dict):
                    continue
                for key in ("group_openid", "channel_id", "guild_id"):
                    if native_source.get(key) and str(
                        native_source[key],
                    ) != route.get(key):
                        valid = False
                native_mid = native_source.get("message_id")
                if native_mid and str(native_mid) != binding.message_id:
                    valid = False
        if valid and nonce in self._cards._processed_requests:
            await self._ack_interaction(str(event.get("id") or ""), 3)
            return True
        await self._ack_interaction(str(event.get("id") or ""))
        if not valid:
            try:
                route = self._native_callback_route(event, actor)
            except ValueError:
                return False
        meta = {
            **route,
            "is_group": route["message_type"] in {"group", "guild"},
            "bot_mentioned": True,
            "has_bot_command": True,
            "operator_display": actor[-6:],
        }
        value = {
            "event_id": event.get("_qq_event_id")
            or "interaction:" + str(event.get("id") or uuid.uuid4().hex),
            "event_kind": "callback",
            "sender_id": actor,
            "acl_sender_id": actor,
            "user_id": actor,
            "session_id": route["session_id"],
            "meta": meta,
            "content_parts": [
                {
                    "type": "text",
                    "text": f"/approval {parsed['action']} {parsed['request_id']}",
                },
            ],
        }
        if valid:
            value.update(approval_binding_id=nonce, approval_actor_id=actor)
        return await self.on_callback(value)

    async def resolve_approval(self, route, params):
        result = params.approval_resolution
        nonce = route.get("approval_binding_id")
        binding = self._cards.bindings.get(nonce)
        valid = (
            binding is not None
            and binding.request_id == result.request_id
            and result.actor_user_id == route.get("approval_actor_id")
            and binding.instance_id == params.instance_id
            and binding.generation == params.generation
        )
        if valid:
            source = dict(binding.route)
            valid = all(
                source.get(k, "") == route.get(k, "")
                for k in (
                    "message_type",
                    "group_openid",
                    "channel_id",
                    "guild_id",
                    "session_id",
                    "root_session_id",
                )
            )
        if not valid or result.outcome.value not in {"approved", "denied"}:
            return await self.send_parts(
                route,
                params.content_parts,
                ContentSource.DIRECT,
            )
        action = "approve" if result.outcome.value == "approved" else "deny"
        if self._cards._mark_processed(nonce, action):
            return await self.send_parts(
                route,
                params.content_parts,
                ContentSource.DIRECT,
            )
        text = build_resolved_text(
            result.tool_name,
            action,
            route.get("operator_display") or result.actor_user_id[-6:],
        )
        # The decision stays committed even if this separate presentation is unknown.
        return await self.send_parts(
            {**source, "response_handle": params.to_handle},
            [{"type": "text", "text": text}],
            ContentSource.DIRECT,
        )

    async def _message(self, event_type, data, epoch):
        self._check_epoch(epoch)
        data = dict(data)
        sequence = data.pop("_qq_seq", None)
        kind, sender_keys, extra_keys = _MESSAGE_EVENT_SPECS[event_type]
        text = (data.get("content") or "").strip()
        if (not text and not data.get("attachments")) or (
            self.config.get("bot_prefix")
            and text.startswith(self.config["bot_prefix"])
        ):
            return True
        author = data.get("author") or {}
        actor = next(
            (str(author[k]) for k in sender_keys if author.get(k)),
            "",
        )
        if not actor:
            return True
        msg_id = str(data.get("id") or "")
        event_id = (
            "message:" + msg_id
            if msg_id
            else (
                "sequence:" + str(self._state.session_id) + ":" + str(sequence)
                if sequence is not None
                else "message:" + uuid.uuid4().hex
            )
        )
        if event_id in self._seen_event_ids:
            return True
        meta = {
            "message_type": kind,
            "message_id": msg_id,
            "sender_id": actor,
            "user_name": author.get("username", ""),
            "is_group": kind in {"group", "guild"},
            "incoming_raw": data,
            "attachments": data.get("attachments") or [],
        }
        meta.update({k: str(data.get(k) or "") for k in extra_keys})
        parts, texts = [], []
        quoted = _find_quoted_element(data)
        if quoted is not None:
            quoted_text = (quoted.get("content") or "").strip()
            attachments = quoted.get("attachments") or []
            if quoted_text:
                texts.insert(0, f"[quoted message: {quoted_text}]")
            if attachments:
                quoted_media = await self.media.parse_attachments(attachments)
                if quoted_media:
                    parts.extend(quoted_media)
                else:
                    texts.insert(0, "[quoted media: download failed]")
            if not quoted_text and not attachments:
                texts.insert(0, "[quoted message]")
        if text:
            texts.append(text)
        body = "\n".join(texts).strip()
        if body:
            parts.insert(0, {"type": "text", "text": body})
        parts.extend(
            await self.media.parse_attachments(data.get("attachments")),
        )
        self._check_epoch(epoch)
        session = resolve_session_id(actor, meta)
        accepted = await self.on_event(
            {
                "event_id": event_id,
                "event_kind": "message",
                "sender_id": actor,
                "acl_sender_id": actor,
                "user_id": actor,
                "session_id": session,
                "meta": meta,
                "content_parts": parts,
            },
        )
        self._check_epoch(epoch)
        if accepted:
            self._seen_event_ids.append(event_id)
            if self.config.get("ack_message"):
                if len(self._ack_tasks) >= 256:
                    await asyncio.wait(
                        self._ack_tasks,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                self._check_epoch(epoch)
                task = asyncio.create_task(
                    self._ack_message(
                        {
                            **meta,
                            "session_id": session,
                            "response_handle": session,
                        },
                        epoch,
                    ),
                )
                self._ack_tasks.add(task)
                task.add_done_callback(self._ack_done)
        return accepted

    async def _ack_message(self, route, epoch):
        self._check_epoch(epoch)
        await self._dispatch_text(route, self.config["ack_message"], False)

    def _ack_done(self, task):
        self._ack_tasks.discard(task)
        self._cancelled_tasks.discard(task)
        if not task.cancelled():
            task.exception()

    def _check_epoch(self, epoch):
        if self._stopping or self._stop_event.is_set() or epoch != self._epoch:
            raise RuntimeError("STALE_CONNECTION_CALLBACK")

    async def _callback_owned(self, awaitable, epoch):
        task = asyncio.current_task()
        self._callbacks.add(task)
        entered = False
        try:
            self._check_epoch(epoch)
            entered = True
            result = await awaitable
            self._check_epoch(epoch)
            return result
        finally:
            if not entered:
                awaitable.close()
            self._callbacks.discard(task)

    def _bridge(self, awaitable, epoch):
        wrapper = self._callback_owned(awaitable, epoch)
        try:
            future = asyncio.run_coroutine_threadsafe(wrapper, self._loop)
        except BaseException:
            wrapper.close()
            awaitable.close()
            raise
        with self._bridge_lock:
            self._bridges.add(future)
        try:
            return future.result()
        finally:
            with self._bridge_lock:
                self._bridges.discard(future)

    def _handle_ws_payload(self, payload, ws, token, state, hb, epoch):
        self._check_epoch(epoch)
        op, data, seq, event_type = (
            payload.get("op"),
            payload.get("d"),
            payload.get("s"),
            payload.get("t"),
        )
        if (
            op == OP_DISPATCH
            and seq is not None
            and state.last_seq is not None
            and seq <= state.last_seq
        ):
            return None
        if op == OP_HELLO:
            if state.session_id and state.last_seq is not None:
                ws.send(
                    json.dumps(
                        {
                            "op": OP_RESUME,
                            "d": {
                                "token": f"QQBot {token}",
                                "session_id": state.session_id,
                                "seq": state.last_seq,
                            },
                        },
                    ),
                )
            else:
                state.last_seq = None
                intents = (
                    INTENT_PUBLIC_GUILD_MESSAGES
                    | INTENT_GUILD_MEMBERS
                    | INTENT_INTERACTION
                )
                if state.identify_fail_count < 3:
                    intents |= INTENT_DIRECT_MESSAGE | INTENT_GROUP_AND_C2C
                ws.send(
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
            hb.start((data or {}).get("heartbeat_interval", 45000))
        elif op == OP_DISPATCH:
            accepted = True
            if event_type in {"READY", "RESUMED"}:
                if event_type == "READY":
                    state.session_id = (data or {}).get("session_id")
                state.identify_fail_count = state.reconnect_attempts = 0
                state.last_connect_time = time.time()
                self._bridge(self.on_state("connected"), epoch)
            elif event_type == "INTERACTION_CREATE":
                ident = (data or {}).get("id")
                event_id = (
                    "interaction:" + str(ident)
                    if ident
                    else (
                        "interaction-seq:"
                        + str(state.session_id)
                        + ":"
                        + str(seq)
                        if seq is not None
                        else "interaction:" + uuid.uuid4().hex
                    )
                )
                if event_id not in self._seen_event_ids:
                    accepted = self._bridge(
                        self._card_handler.handle_interaction_event(
                            {**(data or {}), "_qq_event_id": event_id},
                        ),
                        epoch,
                    )
                    if accepted:
                        self._seen_event_ids.append(event_id)
            elif event_type in _MESSAGE_EVENT_SPECS:
                accepted = self._bridge(
                    self._message(
                        event_type,
                        {**(data or {}), "_qq_seq": seq},
                        epoch,
                    ),
                    epoch,
                )
            self._check_epoch(epoch)
            if not accepted:
                return "break"
            if seq is not None:
                state.last_seq = seq
        elif op == OP_RECONNECT:
            return "break"
        elif op == OP_INVALID_SESSION:
            if not data:
                state.session_id = state.last_seq = None
                state.identify_fail_count += 1
                state.should_refresh_token = True
            return "break"
        return None

    def _compute_reconnect_delay(self, state):
        elapsed = (
            time.time() - state.last_connect_time
            if state.last_connect_time
            else None
        )
        if elapsed is not None and elapsed < QUICK_DISCONNECT_THRESHOLD:
            state.quick_disconnect_count += 1
            if state.quick_disconnect_count >= MAX_QUICK_DISCONNECT_COUNT:
                state.session_id = state.last_seq = None
                state.should_refresh_token = True
                state.quick_disconnect_count = 0
                state.reconnect_attempts = min(
                    state.reconnect_attempts,
                    len(RECONNECT_DELAYS) - 1,
                )
                return RATE_LIMIT_DELAY
        else:
            state.quick_disconnect_count = 0
        return RECONNECT_DELAYS[
            min(state.reconnect_attempts, len(RECONNECT_DELAYS) - 1)
        ]

    def _wait_and_check_reconnect(self, state):
        delay = RECONNECT_DELAYS[
            min(state.reconnect_attempts, len(RECONNECT_DELAYS) - 1)
        ]
        state.reconnect_attempts += 1
        maximum = self.config.get("max_reconnect_attempts", 100)
        if maximum != -1 and state.reconnect_attempts >= maximum:
            return False
        return not self._stop_event.wait(delay)

    def _ws_connect_once(self, state, websocket):
        if self._stop_event.is_set():
            return False
        if state.should_refresh_token:
            self._clear_token_cache()
            state.should_refresh_token = False
        try:
            token = self._get_access_token_sync()
            response = self._sync_http.get(
                _get_api_base() + "/gateway",
                headers={
                    "Authorization": f"QQBot {token}",
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            url = response.json().get("url")
            if not url:
                raise ValueError("QQ_GATEWAY_INVALID")
            ws = websocket.create_connection(
                url,
                timeout=15,
                enable_multithread=True,
            )
            ws.settimeout(1)
        except Exception:
            return self._wait_and_check_reconnect(state)
        self._epoch += 1
        epoch = self._epoch
        self._ws = ws
        hb = _HeartbeatController(ws, self._stop_event, state)
        with self._heartbeat_lock:
            self._heartbeats.add(hb)
        try:
            while not self._stop_event.is_set():
                try:
                    raw = ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                if (
                    not raw
                    or self._handle_ws_payload(
                        json.loads(raw),
                        ws,
                        token,
                        state,
                        hb,
                        epoch,
                    )
                    == "break"
                ):
                    break
        except websocket.WebSocketConnectionClosedException:
            pass
        except OSError as exc:
            if (
                not self._stop_event.is_set()
                and not _is_recoverable_ws_os_error(exc)
            ):
                raise
        except Exception:
            # Admission failure fences the rest of this connection. Resume from
            # the last committed disposition; never skip the failed sequence.
            pass
        finally:
            try:
                hb.join()
            except Exception as exc:
                self._close_errors.append(exc)
            else:
                with self._heartbeat_lock:
                    self._heartbeats.discard(hb)
            try:
                ws.close()
                if ws.connected:
                    raise RuntimeError("QQ_SOCKET_STOP_INCOMPLETE")
            except Exception as exc:
                self._close_errors.append(exc)
            else:
                self._ws = None
            if not self._stop_event.is_set():
                self._bridge(self.on_state("disconnected"), epoch)
        if self._close_errors:
            return False
        delay = self._compute_reconnect_delay(state)
        state.reconnect_attempts += 1
        maximum = self.config.get("max_reconnect_attempts", 100)
        if maximum != -1 and state.reconnect_attempts >= maximum:
            return False
        return not self._stop_event.wait(delay)

    def _run_ws_forever(self):
        try:
            import websocket

            self._sync_http = httpx.Client(timeout=15)
            while self._ws_connect_once(self._state, websocket):
                pass
        except Exception as exc:
            self._thread_error = exc
        finally:
            if self._sync_http is not None:
                try:
                    self._sync_http.close()
                except Exception as exc:
                    self._close_errors.append(exc)
            if not self._stop_event.is_set() and self._loop is not None:
                try:
                    self._bridge(self.on_state("failed"), self._epoch)
                except Exception:
                    pass
            self._stop_event.set()

    async def stop(self):
        if self._stop_task is None or (
            self._stop_task.done() and not self._close_errors
        ):
            self._stop_task = asyncio.create_task(self._stop_owned())
        return await self._settle(self._stop_task)

    async def _stop_owned(self):
        self._stopping = True
        self._stop_event.set()
        self._epoch += 1
        with self._heartbeat_lock:
            for heartbeat in self._heartbeats:
                heartbeat.stop()
        pending = (
            set(self._tasks) | set(self._ack_tasks) | set(self._callbacks)
        )
        pending.discard(asyncio.current_task())
        for task in pending:
            if not task.done() and task not in self._cancelled_tasks:
                self._cancelled_tasks.add(task)
                task.cancel()
        if self._ws is not None:
            try:
                # Public abort interrupts native recv; close completes handshake.
                self._ws.abort()
            except Exception as exc:
                self._close_errors.append(exc)
        if pending or self._io_tasks:
            _, unfinished = await asyncio.wait(
                pending | set(self._io_tasks),
                timeout=5,
            )
            if unfinished:
                raise RuntimeError("QQ_TASK_STOP_INCOMPLETE")
        thread = self._ws_thread
        if thread is not None:
            await self._file_io(thread.join, 16)
            if thread.is_alive():
                raise RuntimeError("QQ_THREAD_STOP_INCOMPLETE")
        with self._heartbeat_lock:
            heartbeats = tuple(self._heartbeats)
        for heartbeat in heartbeats:
            await self._file_io(heartbeat.join)
        if (
            self._http is not None
            and not self._http_closed
            and self._http_close_error is None
        ):
            try:
                await self._http.aclose()
            except BaseException as exc:
                self._http_close_error = exc
                self._close_errors.append(exc)
            else:
                self._http_closed = True
        if self._close_errors:
            raise RuntimeError("QQ_NATIVE_CLOSE_FAILED")
        if self._sync_http is not None and not self._sync_http.is_closed:
            raise RuntimeError("QQ_HTTP_STOP_INCOMPLETE")
        with self._bridge_lock:
            if any(not future.done() for future in self._bridges):
                raise RuntimeError("QQ_CALLBACK_STOP_INCOMPLETE")
        self._http = self._sync_http = self._ws_thread = None
        self._heartbeats.clear()
