# -*- coding: utf-8 -*-
"""Instance-owned dual-WS A2A transport, native routing and media effects."""

from __future__ import annotations

import asyncio
from collections import OrderedDict, deque
from contextlib import asynccontextmanager
from dataclasses import dataclass
import hashlib
import json
import logging
from pathlib import Path, PureWindowsPath
import uuid

import aiohttp

from qwenpaw.constant import DEFAULT_MEDIA_DIR
from qwenpaw.utils.io_utils import make_dirs_async
from qwenpaw.utils.media_paths import local_media_path

from .codec import (
    build_artifact_msg,
    build_control_response,
    build_status_msg,
    new_artifact_id,
)
from .connection import XiaoYiConnection
from .constants import (
    DEFAULT_TASK_TIMEOUT_MS,
    DEFAULT_WS_URL,
    DEFAULT_WS_URL_BACKUP,
    MAX_CONCURRENT_DOWNLOADS,
    MAX_PENDING_MESSAGES,
    MAX_RECONNECT_ATTEMPTS,
    RECONNECT_DELAYS,
    RECONNECT_STABLE_SECONDS,
)
from .errors import XiaoYiDeliveryError
from .utils import chunk_text, download_file

logger = logging.getLogger(__name__)
_SESSION_MAP_MAX = 4096


@dataclass(frozen=True, slots=True)
class _Inbound:
    message: dict
    server: str
    event_id: str | None
    control_state: str | None


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
            self._media_dir = DEFAULT_MEDIA_DIR / "xiaoyi"
        self._connections: dict[str, XiaoYiConnection] = {}
        self._exhausted: set[str] = set()
        self._media_session = None
        self._session_server_map = OrderedDict()
        self._session_task_map = OrderedDict()
        self._seen_events = OrderedDict()
        self._pending_events: set[str] = set()
        self._inbound: dict[str, deque[_Inbound]] = {}
        self._inbound_slots = asyncio.BoundedSemaphore(MAX_PENDING_MESSAGES)
        self._download_slots = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
        self._state_lock = asyncio.Lock()
        self._tasks, self._operations = set(), set()
        self._stopping = False
        self._last_state = None

    @property
    def connected(self):
        return not self._stopping and any(
            conn.connected for conn in self._connections.values()
        )

    async def health_check(self):
        primary = self._connections.get(f"primary")
        backup = self._connections.get(f"backup")
        primary_state = f"ok" if primary and primary.connected else f"down"
        backup_state = f"ok" if backup and backup.connected else f"down"
        return {
            "channel": "xiaoyi",
            "status": "healthy" if self.connected else "unhealthy",
            "detail": (
                f"primary={primary_state}, backup={backup_state}"
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

    async def _publish_state(self):
        async with self._state_lock:
            if self._stopping:
                state = f"disconnected"
            elif self.connected:
                state = f"connected"
            elif self._exhausted == self._connections.keys():
                state = f"failed"
            else:
                state = f"connecting"
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
        async with self._effect():
            await make_dirs_async(self._media_dir)
            urls = {f"primary": self.ws_url or DEFAULT_WS_URL}
            if DEFAULT_WS_URL_BACKUP and not self.ws_url:
                urls[f"backup"] = DEFAULT_WS_URL_BACKUP
            for name, url in urls.items():
                self._connections[name] = XiaoYiConnection(
                    name,
                    url,
                    self.ak,
                    self.sk,
                    self.agent_id,
                    self._handle_incoming_message,
                )
            await self._publish_state()
            started = []
            for conn in self._connections.values():
                first_attempt = asyncio.Event()
                started.append(first_attempt)
                self._spawn(self._supervise_connection(conn, first_attempt))
            await asyncio.gather(*(ready.wait() for ready in started))

    async def _close_connections(self):
        failures = []
        for name, conn in tuple(self._connections.items()):
            try:
                await conn.disconnect()
            except Exception as exc:
                failures.append(exc)
            else:
                self._connections.pop(name)
        if failures:
            raise RuntimeError(f"XIAOYI_CONNECTIONS_REMAIN") from failures[0]

    async def _supervise_connection(self, conn, first_attempt):
        name = conn.server_name
        attempt = 0
        try:
            while not self._stopping and attempt <= MAX_RECONNECT_ATTEMPTS:
                if attempt:
                    delay = RECONNECT_DELAYS[
                        min(attempt - 1, len(RECONNECT_DELAYS) - 1)
                    ]
                    logger.info(
                        f"xiaoyi [%s]: reconnecting in %ss (attempt %s)",
                        name,
                        delay,
                        attempt,
                    )
                    await asyncio.sleep(delay)
                try:
                    if await conn.connect():
                        await self._publish_state()
                        first_attempt.set()
                        if not await conn.wait_disconnected(
                            timeout=RECONNECT_STABLE_SECONDS,
                        ):
                            attempt = 0
                            await conn.wait_disconnected()
                        for session, server in tuple(
                            self._session_server_map.items(),
                        ):
                            if server == name:
                                self._session_server_map.pop(session, None)
                        await self._publish_state()
                        await conn.disconnect()
                except Exception as exc:
                    logger.warning(
                        f"xiaoyi [%s]: connection supervisor failed (%s)",
                        name,
                        type(exc).__name__,
                    )
                finally:
                    first_attempt.set()
                attempt += 1
        finally:
            first_attempt.set()
        self._exhausted.add(name)
        await self._publish_state()

    async def stop(self):
        self._stopping = True
        current = asyncio.current_task()
        tasks = (self._tasks | self._operations) - {current}
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for queue in self._inbound.values():
            while queue:
                self._release_inbound(queue.popleft())
        self._inbound.clear()
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
        await self._publish_state()

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
        servers = (f"primary", f"backup")
        if route.get("server_name") == "backup":
            servers = (f"backup", f"primary")
        for name in servers:
            conn = self._connections.get(name)
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
        params = message.get(f"params")
        params = params if isinstance(params, dict) else {}
        session = str(
            params.get(f"sessionId") or message.get(f"sessionId") or f"",
        )
        method, action = message.get(f"method"), message.get(f"action")
        event_id = control_state = None
        if method == f"clearContext" or action == f"clear":
            control_state = f"cleared"
        elif method == f"tasks/cancel" or action == f"tasks/cancel":
            control_state = f"canceled"
        elif method == f"message/stream" and session:
            native = params.get(f"message")
            if not isinstance(native, dict):
                return
            event_id = self._event_id(message, native, session)
        else:
            return
        job = _Inbound(message, server_name, event_id, control_state)
        await self._enqueue_inbound(session, job)

    def _is_duplicate_event(self, event_id):
        if event_id in self._pending_events:
            return True
        previous = self._seen_events.get(event_id)
        if previous is None or not previous[f"accepted"]:
            return False
        self._seen_events.move_to_end(event_id)
        return True

    async def _enqueue_inbound(self, session, job):
        if self._is_duplicate_event(job.event_id):
            return
        await self._inbound_slots.acquire()
        if self._stopping or self._is_duplicate_event(job.event_id):
            self._inbound_slots.release()
            return
        if job.event_id is not None:
            self._pending_events.add(job.event_id)
        queue = self._inbound.get(session)
        if queue is None:
            queue = self._inbound[session] = deque([job])
            self._spawn(self._process_inbound(session, queue))
        else:
            queue.append(job)

    def _release_inbound(self, job):
        self._pending_events.discard(job.event_id)
        self._inbound_slots.release()

    async def _process_inbound(self, session, queue):
        try:
            while queue:
                job = queue.popleft()
                try:
                    await self._process_message(session, job)
                except Exception:
                    logger.exception(f"xiaoyi: inbound message failed")
                finally:
                    self._release_inbound(job)
        finally:
            self._inbound.pop(session)
            while queue:
                self._release_inbound(queue.popleft())

    async def _process_message(self, session, job):
        if session:
            _bounded_map_put(self._session_server_map, session, job.server)
        if job.control_state is None:
            await self._admit_message(session, job)
            return
        await self._send_control_response(
            job.message.get(f"id") or f"",
            session,
            job.control_state,
            job.server,
        )
        if job.control_state == f"cleared":
            self._session_task_map.pop(session, None)

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
                        (
                            f"message"
                            if native_id not in (None, f"")
                            else f"request"
                        ),
                        stable,
                    ],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode(),
            ).hexdigest()
        )

    async def _admit_message(self, session, job):
        event_id = job.event_id
        previous = self._seen_events.get(event_id)
        if previous is not None:
            self._seen_events.move_to_end(event_id)
            value = previous[f"value"]
        else:
            value = await self._prepare_message(session, job)
            if value is None:
                return
            # Reuse the prepared content and route if admission is uncertain.
            _bounded_map_put(
                self._seen_events,
                event_id,
                {f"value": value, f"accepted": False},
            )
        if await self.on_event(value):
            _bounded_map_put(self._seen_events, event_id, {f"accepted": True})

    async def _prepare_message(self, session, job):
        params = job.message[f"params"]
        native = params[f"message"]
        request_id = job.message.get(f"id")
        task_id = params.get(f"id") or request_id
        _bounded_map_put(self._session_task_map, session, task_id or f"")
        texts, parts = [], []
        for part in native.get(f"parts") or []:
            if not isinstance(part, dict):
                continue
            if part.get(f"kind") == f"text" and part.get(f"text"):
                texts.append(str(part[f"text"]))
            elif part.get(f"kind") == f"file":
                await self._process_file_part(part, texts, parts)
        text = f" ".join(texts).strip()
        if text:
            parts.insert(0, {f"type": f"text", f"text": text})
        if not parts:
            return None
        message_id = (
            request_id if request_id is not None else str(uuid.uuid4())
        )
        return {
            f"event_id": job.event_id,
            f"session_id": session,
            f"content_parts": parts,
            f"route": {
                f"origin": f"inbound",
                f"session_id": session,
                f"task_id": str(task_id or f""),
                f"task_id_json": json.dumps(task_id or f""),
                f"message_id": str(message_id),
                f"message_id_json": json.dumps(message_id),
                f"server_name": job.server,
            },
            f"meta": {
                f"native_session_id": session,
                f"task_id": task_id,
                f"request_id": request_id,
                f"message_id": request_id,
                f"native_message_id": native.get(f"messageId"),
                f"server_name": job.server,
            },
        }

    async def _process_file_part(self, part, texts, parts):
        file = part.get("file") or {}
        if not file.get("uri"):
            return
        filename = str(file.get("name") or "file")
        async with self._download_slots:
            if self._media_session is None:
                self._media_session = aiohttp.ClientSession()
            local = await download_file(
                file[f"uri"],
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
        if role == f"rendered":
            text = f"\n\n{text}\n\n"
        elif role == "message" and not text.startswith("\n"):
            text = "\n\n" + text
        return {"kind": "text", "text": text}

    def _artifact_frames(self, route, parts, *, append):
        text_by_kind = {}
        for part in parts:
            kind = part[f"kind"]
            text_by_kind.setdefault(kind, []).append(part[kind])

        frames = []
        for kind, texts in text_by_kind.items():
            chunks = chunk_text(f"".join(texts))
            artifact_id = new_artifact_id()
            for index, chunk in enumerate(chunks):
                frames.append(
                    build_artifact_msg(
                        self.agent_id,
                        route,
                        [{f"kind": kind, kind: chunk}],
                        artifact_id=artifact_id,
                        append=append or index > 0,
                        last_chunk=index == len(chunks) - 1,
                    ),
                )
        return frames

    def _outbound_frames(
        self,
        route,
        parts,
        source,
        *,
        replace_event_text,
        media_final,
    ):
        source = getattr(source, "value", source)
        semantic = source == f"event"
        append = not (semantic and replace_event_text)
        parts = list(parts)
        if semantic and any(
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
        if semantic:
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
                value = self._text_parts(part, semantic)
                if value and (
                    semantic
                    or value.get(
                        "text",
                        value.get("reasoningText", ""),
                    ).strip()
                ):
                    text_parts.append(value)
                continue
            if semantic and part.get("role") != "rendered":
                continue
            media = self._media_part(part)
            if media is not None:
                frames.extend(
                    self._artifact_frames(route, text_parts, append=append),
                )
                text_parts = []
                frames.append(
                    build_artifact_msg(
                        self.agent_id,
                        route,
                        [media],
                        final=media_final,
                    ),
                )
        frames.extend(self._artifact_frames(route, text_parts, append=append))
        return frames

    async def send_parts(
        self,
        route,
        parts,
        source,
        *,
        replace_event_text=False,
        media_final=True,
    ):
        if not route.get("task_id"):
            raise XiaoYiDeliveryError("XIAOYI_TASK_UNKNOWN")
        async with self._effect():
            frames = self._outbound_frames(
                route,
                parts,
                source,
                replace_event_text=replace_event_text,
                media_final=media_final,
            )
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

    async def send_status(self, route, state, text=f""):
        async with self._effect():
            await self._send_to_route(
                route,
                build_status_msg(self.agent_id, route, state, text),
            )

    async def send_stream_part(
        self,
        route,
        artifact_id,
        kind,
        text,
        *,
        append,
        last_chunk,
    ):
        async with self._effect():
            await self._send_to_route(
                route,
                build_artifact_msg(
                    self.agent_id,
                    route,
                    [{f"kind": kind, kind: text}],
                    artifact_id=artifact_id,
                    append=append,
                    last_chunk=last_chunk,
                ),
            )

    async def send_finish_step(self, route, step, state):
        if not route.get("task_id"):
            raise XiaoYiDeliveryError("XIAOYI_TASK_UNKNOWN")
        if step == f"completed":
            text = f"Done" if state == f"completed" else f""
            await self.send_status(route, state, text)
            return
        async with self._effect():
            await self._send_to_route(
                route,
                build_artifact_msg(
                    self.agent_id,
                    route,
                    [{"kind": "text", "text": ""}],
                    final=True,
                ),
            )
