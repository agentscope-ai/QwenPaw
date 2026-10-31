# -*- coding: utf-8 -*-
"""Instance-owned dual-WS A2A transport, native routing and media effects."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from contextlib import asynccontextmanager
import hashlib
import json
import logging
from pathlib import Path, PureWindowsPath
import uuid

import aiohttp

from qwenpaw.utils.media_paths import local_media_path

from .codec import (
    build_artifact_msg,
    build_completed_msg,
    build_control_response,
)
from .connection import XiaoYiConnection
from .constants import (
    DEFAULT_TASK_TIMEOUT_MS,
    DEFAULT_WS_URL,
    DEFAULT_WS_URL_BACKUP,
    MAX_RECONNECT_ATTEMPTS,
    RECONNECT_DELAYS,
    TEXT_CHUNK_LIMIT,
)
from .errors import XiaoYiDeliveryError
from .utils import chunk_text, download_file

logger = logging.getLogger(__name__)
_SESSION_MAP_MAX = 4096


def native_session_id(value):
    return value.split(":", 1)[1] if value.startswith("xiaoyi:") else value


def _bounded_map_put(store, key, value, max_items=_SESSION_MAP_MAX):
    store[key] = value
    store.move_to_end(key)
    while len(store) > max_items:
        store.popitem(last=False)


class XiaoYiPlatform:
    def __init__(self, config, on_event, on_state):
        self.config = dict(config)
        self.on_event, self.on_state = on_event, on_state
        self.ak, self.sk = config.get("ak", ""), config.get("sk", "")
        self.agent_id = config.get("agent_id", "")
        self.ws_url = (config.get("ws_url") or "").strip()
        # Legacy configuration stores this value; it did not create a timer.
        self.task_timeout_ms = config.get(
            "task_timeout_ms",
            DEFAULT_TASK_TIMEOUT_MS,
        )
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

            self._media_dir = DEFAULT_MEDIA_DIR / "xiaoyi"
        self._conn_primary = self._conn_backup = None
        self._media_session = self._reconnect_task = None
        self._session_server_map = OrderedDict()
        self._session_task_map = OrderedDict()
        self._seen_events = OrderedDict()
        self._admission_lock = asyncio.Lock()
        self._connect_lock = asyncio.Lock()
        self._tasks, self._operations = set(), set()
        self._stopping = False
        self._generation = self._reconnect_attempts = 0
        self._last_state = None

    @property
    def connected(self):
        return not self._stopping and any(
            conn is not None and conn.connected
            for conn in (self._conn_primary, self._conn_backup)
        )

    async def health_check(self):
        primary = bool(self._conn_primary and self._conn_primary.connected)
        backup = bool(self._conn_backup and self._conn_backup.connected)
        return {
            "channel": "xiaoyi",
            "status": "healthy" if self.connected else "unhealthy",
            "detail": (
                f"primary={'ok' if primary else 'down'}, "
                f"backup={'ok' if backup else 'down'}"
                if self.connected
                else "No WebSocket connections active."
            ),
        }

    def _spawn(self, coroutine):
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)

        def done(finished):
            self._tasks.discard(finished)
            if not finished.cancelled() and finished.exception() is not None:
                logger.error("xiaoyi: background operation failed")

        task.add_done_callback(done)
        return task

    @asynccontextmanager
    async def _effect(self):
        if self._stopping:
            raise XiaoYiDeliveryError("XIAOYI_STOPPING")
        owner = asyncio.current_task()
        self._operations.add(owner)
        try:
            yield
        finally:
            self._operations.discard(owner)

    async def _publish_state(self, state):
        if self._last_state != state:
            await self.on_state(state)
            self._last_state = state

    async def start(self):
        for name, label in (
            ("ak", "AK"),
            ("sk", "SK"),
            ("agent_id", "Agent ID"),
        ):
            if not getattr(self, name):
                raise ValueError(f"XiaoYi {label} is required")
        self._media_dir.mkdir(parents=True, exist_ok=True)
        async with self._effect():
            await self._start_connections()

    async def _close_connections(self):
        failures = []
        for name in ("_conn_primary", "_conn_backup"):
            conn = getattr(self, name)
            if conn is not None:
                try:
                    await conn.disconnect()
                except Exception as exc:
                    failures.append(exc)
                else:
                    setattr(self, name, None)
        if failures:
            raise RuntimeError("XIAOYI_CONNECTIONS_REMAIN") from failures[0]

    async def _start_connections(self):
        async with self._connect_lock:
            if self._stopping:
                return
            self._generation += 1
            generation = self._generation
            await self._close_connections()
            await self._publish_state("connecting")

            async def message(value, server):
                if generation == self._generation and not self._stopping:
                    await self._handle_incoming_message(value, server)

            async def disconnected(server):
                if generation == self._generation and not self._stopping:
                    await self._handle_disconnect(server)

            def create(server, url):
                return XiaoYiConnection(
                    server,
                    url,
                    self.ak,
                    self.sk,
                    self.agent_id,
                    message,
                    disconnected,
                )

            self._conn_primary = create(
                "primary",
                self.ws_url or DEFAULT_WS_URL,
            )
            if DEFAULT_WS_URL_BACKUP and not self.ws_url:
                self._conn_backup = create("backup", DEFAULT_WS_URL_BACKUP)

            async def connect(conn):
                if await conn.connect() and not self._stopping:
                    await self._publish_state("connected")

            await asyncio.gather(
                *(
                    connect(conn)
                    for conn in (self._conn_primary, self._conn_backup)
                    if conn is not None
                ),
                return_exceptions=True,
            )
            if self._stopping:
                return
            if self.connected:
                self._reconnect_attempts = 0
                await self._publish_state("connected")
            else:
                self._schedule_reconnect()

    async def _handle_disconnect(self, server_name):
        if self._stopping:
            return
        for session, server in tuple(self._session_server_map.items()):
            if server == server_name:
                self._session_server_map.pop(session, None)
        if not self.connected:
            await self._publish_state("connecting")
            self._schedule_reconnect()

    def _schedule_reconnect(self):
        if self._stopping or (
            self._reconnect_task is not None
            and not self._reconnect_task.done()
        ):
            return
        self._reconnect_task = self._spawn(self._reconnect())

    async def _reconnect(self):
        while not self._stopping and not self.connected:
            if self._reconnect_attempts >= MAX_RECONNECT_ATTEMPTS:
                await self._publish_state("failed")
                return
            delay = RECONNECT_DELAYS[
                min(self._reconnect_attempts, len(RECONNECT_DELAYS) - 1)
            ]
            self._reconnect_attempts += 1
            await asyncio.sleep(delay)
            if self._stopping or self.connected:
                return
            try:
                await self._start_connections()
            except Exception:
                logger.warning("xiaoyi: reconnect failed")

    async def stop(self):
        self._stopping = True
        self._generation += 1
        current = asyncio.current_task()
        tasks = (self._tasks | self._operations) - {current}
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._reconnect_task = None
        failures = []
        try:
            await self._close_connections()
        except Exception as exc:
            failures.append(exc)
        if self._media_session is not None:
            try:
                await self._media_session.close()
            except Exception as exc:
                failures.append(exc)
            else:
                self._media_session = None
        if failures:
            raise RuntimeError("XIAOYI_STOP_INCOMPLETE") from failures[0]
        await self._publish_state("disconnected")

    def resolve_target(self, session, meta):
        session = native_session_id(str(meta.get("session_id") or session))
        task_id = meta.get("task_id") or self._session_task_map.get(session)
        if not session or not task_id:
            raise XiaoYiDeliveryError("XIAOYI_TASK_UNKNOWN")
        message_id = meta.get("message_id") or str(uuid.uuid4())
        return {
            "session_id": session,
            "task_id": str(task_id),
            "task_id_json": json.dumps(task_id),
            "message_id": str(message_id),
            "message_id_json": json.dumps(message_id),
            "server_name": str(
                meta.get("server_name")
                or self._session_server_map.get(session, "primary"),
            ),
        }

    async def _send_to_route(self, route, message):
        if self._stopping:
            raise XiaoYiDeliveryError("XIAOYI_STOPPING")
        connections = (self._conn_primary, self._conn_backup)
        if route.get("server_name") == "backup":
            connections = tuple(reversed(connections))
        for conn in connections:
            if conn is None:
                continue
            try:
                if await conn.send_json(message):
                    return
            except XiaoYiDeliveryError:
                raise
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                raise XiaoYiDeliveryError(
                    "PLATFORM_RESULT_UNKNOWN",
                    side_effect_possible=True,
                ) from exc
        raise XiaoYiDeliveryError("NOT_CONNECTED", retryable=True)

    async def _handle_incoming_message(self, message, server_name):
        if self._stopping or not isinstance(message, dict):
            return
        if message.get("agentId") and message["agentId"] != self.agent_id:
            return
        async with self._effect():
            params = message.get("params")
            params = params if isinstance(params, dict) else {}
            session = params.get("sessionId") or message.get("sessionId")
            if session:
                _bounded_map_put(
                    self._session_server_map,
                    str(session),
                    server_name,
                )
            method, action = message.get("method"), message.get("action")
            if method == "clearContext" or action == "clear":
                await self._handle_clear_context(message, server_name)
            elif method == "tasks/cancel" or action == "tasks/cancel":
                await self._handle_tasks_cancel(message, server_name)
            elif method == "message/stream":
                await self._handle_a2a_request(message, server_name)

    async def _handle_clear_context(self, message, server_name="primary"):
        session, request_id = (
            message.get("sessionId") or "",
            message.get("id") or "",
        )
        await self._send_control_response(
            request_id,
            session,
            "cleared",
            server_name,
        )
        if session:
            self._session_task_map.pop(session, None)

    async def _handle_tasks_cancel(self, message, server_name="primary"):
        # The old protocol only acknowledges cancel; it does not cancel Agent work.
        await self._send_control_response(
            message.get("id") or "",
            message.get("sessionId") or "",
            "canceled",
            server_name,
        )

    async def _send_control_response(self, request_id, session, state, server):
        if not self.connected:
            return
        try:
            await self._send_to_route(
                {"server_name": server},
                build_control_response(
                    self.agent_id,
                    request_id,
                    session,
                    state,
                ),
            )
        except XiaoYiDeliveryError:
            # Legacy control acknowledgements are best effort. Clear still
            # removes its mapping after the acknowledgement attempt; cancel
            # never removes it. An uncertain write does not select a fallback.
            logger.warning("xiaoyi: control acknowledgement failed")

    @staticmethod
    def _event_id(message, native_message, session):
        request_id = message.get("id")
        native_id = native_message.get("messageId")
        stable = native_id if native_id not in (None, "") else request_id
        if stable is None or stable == "":
            # No platform ID means no cross-push deduplication promise.
            return "xiaoyi:event:" + uuid.uuid4().hex
        return (
            "xiaoyi:event:"
            + hashlib.sha256(
                json.dumps(
                    [
                        session,
                        "message"
                        if native_id not in (None, "")
                        else "request",
                        stable,
                    ],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode(),
            ).hexdigest()
        )

    async def _handle_a2a_request(self, message, server_name="primary"):
        params = message.get("params") or {}
        session = params.get("sessionId") or message.get("sessionId")
        if not session:
            return
        session = str(session)
        task_id = params.get("id") or message.get("id")
        native_message = params.get("message") or {}
        event_id = self._event_id(message, native_message, session)
        async with self._admission_lock:
            if self._stopping:
                return
            previous = self._seen_events.get(event_id)
            if previous is not None:
                self._seen_events.move_to_end(event_id)
                if previous["accepted"]:
                    return
                value = previous["value"]
            else:
                _bounded_map_put(
                    self._session_task_map,
                    session,
                    task_id or "",
                )
                texts, parts = [], []
                for part in native_message.get("parts") or []:
                    if not isinstance(part, dict):
                        continue
                    if part.get("kind") == "text" and part.get("text"):
                        texts.append(str(part["text"]))
                    elif part.get("kind") == "file":
                        await self._process_file_part(part, texts, parts)
                text = " ".join(texts).strip()
                if text:
                    parts.insert(0, {"type": "text", "text": text})
                if not parts:
                    return
                message_id = message.get("id")
                if message_id is None:
                    message_id = str(uuid.uuid4())
                value = {
                    "event_id": event_id,
                    "session_id": session,
                    "content_parts": parts,
                    "route": {
                        "session_id": session,
                        "task_id": str(task_id or ""),
                        "task_id_json": json.dumps(task_id or ""),
                        "message_id": str(message_id),
                        "message_id_json": json.dumps(message_id),
                        "server_name": server_name,
                    },
                    "meta": {
                        "native_session_id": session,
                        "task_id": task_id,
                        "request_id": message.get("id"),
                        "message_id": message.get("id"),
                        "native_message_id": native_message.get("messageId"),
                        "server_name": server_name,
                    },
                }
                _bounded_map_put(
                    self._seen_events,
                    event_id,
                    {"value": value, "accepted": False},
                )
            # Retain the original value/route after uncertain admission; every
            # IPC retry and repeated push uses the exact same event identity.
            accepted = bool(await self.on_event(value))
            if accepted:
                # Accepted IDs need no retained text or media payload. Only
                # uncertain admissions keep the original value for retry.
                self._seen_events[event_id] = {"accepted": True}

    async def _process_file_part(self, part, texts, parts):
        file = part.get("file") or {}
        if not file.get("uri"):
            return
        filename = str(file.get("name") or "file")
        if self._media_session is None:
            self._media_session = aiohttp.ClientSession()
        local = await download_file(
            file["uri"],
            self._media_dir,
            filename,
            session=self._media_session,
        )
        if not local:
            texts.append(f"[{filename}: download failed]")
        elif str(file.get("mimeType") or "").startswith("image/"):
            parts.append({"type": "image", "image_url": local})
        else:
            parts.append(
                {"type": "file", "file_url": local, "filename": filename},
            )

    def _media_part(self, part):
        kind = part.get("type")
        defaults = {
            "image": ("image_url", "image", "image/png"),
            "video": ("video_url", "video", "video/mp4"),
            "audio": ("data", "audio", part.get("format") or "audio/mpeg"),
            "file": ("file_url", "file", "application/octet-stream"),
        }
        if kind not in defaults:
            return None
        field, name, mime = defaults[kind]
        uri = part.get(field, "")
        local_path = local_media_path(uri)
        local = None
        if local_path is not None and (
            kind != "audio"
            or uri.startswith(("file://", "/", "~", "./", "../"))
            or Path(local_path).is_absolute()
            or PureWindowsPath(local_path).is_absolute()
        ):
            local = Path(local_path).expanduser()
        if local is not None:
            roots = [self._media_dir.resolve()]
            if self._workspace_dir is not None:
                roots.append(self._workspace_dir.resolve())
            if not any(local.resolve().is_relative_to(root) for root in roots):
                raise XiaoYiDeliveryError("MEDIA_PATH_UNAUTHORIZED")
        return {
            "kind": "file",
            "file": {
                "name": part.get("filename") or name,
                "mimeType": part.get("mime_type") or mime,
                "uri": uri,
            },
        }

    @staticmethod
    def _text_parts(part, semantic):
        text = part.get("text") or ""
        if not text:
            return None
        role = part.get("role") if semantic else None
        if role == "reasoning":
            return {"kind": "reasoningText", "reasoningText": text + "\n"}
        if role == "message" and not text.startswith("\n"):
            text = "\n\n" + text
        return {"kind": "text", "text": text}

    def _artifact_frames(self, route, parts):
        if not parts:
            return []
        if any(
            len(part.get("text") or part.get("reasoningText") or "")
            > TEXT_CHUNK_LIMIT
            for part in parts
        ):
            frames = []
            for part in parts:
                kind = part["kind"]
                for chunk in chunk_text(
                    part.get("text") or part.get("reasoningText") or "",
                ):
                    frames.append(
                        build_artifact_msg(
                            self.agent_id,
                            route,
                            [{"kind": kind, kind: chunk}],
                        ),
                    )
            return frames
        return [build_artifact_msg(self.agent_id, route, parts)]

    def _outbound_frames(self, route, parts, source):
        source = getattr(source, "value", source)
        parts = list(parts)
        if source == "event" and any(
            part.get("type") == "text"
            and part.get("text")
            and part.get("role") in {"message", "reasoning", "refusal"}
            for part in parts
        ):
            parts = [
                part
                for part in parts
                if not (
                    part.get("type") == "text"
                    and part.get("role") == "rendered"
                )
            ]
        if source == "event":
            # Legacy completed events publish their text artifact before media.
            parts = [part for part in parts if part.get("type") == "text"] + [
                part for part in parts if part.get("type") != "text"
            ]
        if source == "content_parts":
            texts = [
                part.get("text", "")
                for part in parts
                if part.get("type") == "text"
            ]
            body = "\n".join(texts)
            for part in parts:
                kind = part.get("type")
                field = {
                    "image": "image_url",
                    "video": "video_url",
                    "file": "file_url",
                }.get(kind)
                if field and part.get(field):
                    body += f"\n[{kind.title()}: {part[field]}]"
                elif kind == "audio" and part.get("data"):
                    body += "\n[Audio]"
            parts = (
                [{"type": "text", "text": body.strip()}]
                if body.strip()
                else []
            ) + [part for part in parts if part.get("type") != "text"]
        frames, text_parts = [], []
        for part in parts:
            if part.get("type") == "text":
                value = self._text_parts(part, source == "event")
                if value and (
                    source == "event"
                    or value.get(
                        "text",
                        value.get("reasoningText", ""),
                    ).strip()
                ):
                    text_parts.append(value)
                continue
            if source == "event" and part.get("role") != "rendered":
                continue
            media = self._media_part(part)
            if media is not None:
                frames.extend(self._artifact_frames(route, text_parts))
                text_parts = []
                frames.append(
                    build_artifact_msg(
                        self.agent_id,
                        route,
                        [media],
                        final=True,
                    ),
                )
        frames.extend(self._artifact_frames(route, text_parts))
        return frames

    async def send_parts(self, route, parts, source):
        if not route.get("task_id"):
            raise XiaoYiDeliveryError("XIAOYI_TASK_UNKNOWN")
        async with self._effect():
            frames = self._outbound_frames(route, parts, source)
            sent = 0
            try:
                for message in frames:
                    await self._send_to_route(route, message)
                    sent += 1
            except XiaoYiDeliveryError as exc:
                if sent and not exc.side_effect_possible:
                    raise XiaoYiDeliveryError(
                        "PARTIAL_DELIVERY",
                        side_effect_possible=True,
                    ) from exc
                raise
            return {
                "transport_written": "true" if sent else "false",
                "frame_count": str(sent),
            }

    async def send_finish_step(self, route, step):
        if not route.get("task_id"):
            raise XiaoYiDeliveryError("XIAOYI_TASK_UNKNOWN")
        async with self._effect():
            message = (
                build_completed_msg(self.agent_id, route)
                if step == "completed"
                else build_artifact_msg(
                    self.agent_id,
                    route,
                    [{"kind": "text", "text": ""}],
                    final=True,
                )
            )
            await self._send_to_route(route, message)
