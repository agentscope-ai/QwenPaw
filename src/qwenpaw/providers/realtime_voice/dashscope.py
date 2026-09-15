"""DashScope Qwen-Audio native realtime voice adapter."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from collections.abc import AsyncIterator, Iterable
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote
from uuid import uuid4

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from .contracts import (
    EffectiveRealtimeVoiceConfig,
    MediaConfig,
    ProviderEvent,
    ProviderResponseOrigin,
    ProviderResponseResult,
    RealtimeProviderRegistration,
    RealtimeSessionConfig,
    RealtimeVoiceModelConfig,
    RealtimeVoiceVadConfig,
    RegionOption,
    SpeechModelOption,
)

logger = logging.getLogger(__name__)

_REGION_DOMAINS = {
    "beijing": "dashscope.aliyuncs.com",
    "singapore": "dashscope-intl.aliyuncs.com",
}
_EVENTS_CLOSED = object()
_READY_TIMEOUT_SECONDS = 15
_COMMAND_TIMEOUT_SECONDS = 20
_RESPONSE_TIMEOUT_SECONDS = 90
_BARGE_IN_CANCEL_FALLBACK_SECONDS = 0.75
_INPUT_CLEANUP_FALLBACK_SECONDS = 2.0


def _event_id(payload: dict[str, Any]) -> str:
    return str(payload.get("event_id") or uuid4().hex)


def _is_response_busy_error(error: dict[str, Any]) -> bool:
    return str(error.get("code") or "") == "invalid_value" and (
        str(error.get("param") or "") == "response.create"
        or "response" in str(error.get("message") or "").lower()
    )


def _missing_deleted_item(
    error: dict[str, Any],
    pending_item_ids: Iterable[str],
) -> str | None:
    """Return a pending deletion that the Provider already removed."""
    if str(error.get("code") or "") != "invalid_value":
        return None
    message = str(error.get("message") or "")
    if "cannot find item" not in message.lower():
        return None
    return next((item_id for item_id in pending_item_ids if item_id in message), None)


def _endpoint(override: str | None, region: str, model: str) -> str:
    if override:
        separator = "&" if "?" in override else "?"
        if "model=" in override:
            return override
        return f"{override}{separator}model={quote(model, safe='')}"
    domain = _REGION_DOMAINS[region]
    return f"wss://{domain}/api-ws/v1/realtime?model={quote(model, safe='')}"


@dataclass
class _InputTurnState:
    item_ids: set[str] = field(default_factory=set)
    transcript_final: bool = False
    auto_response_terminal: bool = False
    cleanup_scheduled: bool = False


class DashScopeRealtimeSession:
    """One Qwen-Audio session with normalized commands and events."""

    def __init__(
        self,
        config: EffectiveRealtimeVoiceConfig,
        api_key: str,
    ) -> None:
        self._config = config
        self._api_key = api_key
        self._session_config: RealtimeSessionConfig | None = None
        self._socket: Any = None
        self._receiver: asyncio.Task[None] | None = None
        self._events: asyncio.Queue[ProviderEvent | object] = asyncio.Queue()
        self._ready = asyncio.Event()
        self._idle = asyncio.Event()
        self._idle.set()
        self._presentation_ready = asyncio.Event()
        self._presentation_ready.set()
        self._send_lock = asyncio.Lock()
        self._command_lock = asyncio.Lock()
        self._request_lock = asyncio.Lock()
        self._response_lock = asyncio.Lock()
        self._pending_items: dict[str, asyncio.Future[None]] = {}
        self._pending_deletions: dict[str, asyncio.Future[None]] = {}
        self._response_requested = False
        self._pending_response_origin: ProviderResponseOrigin | None = None
        self._active_response_id: str | None = None
        self._active_response_origin: ProviderResponseOrigin | None = None
        self._active_response_items: set[str] = set()
        self._application_response_done: (
            asyncio.Future[ProviderResponseResult] | None
        ) = None
        self._input_turn_sequence = 0
        self._active_input_turn = 0
        self._input_turns: dict[int, _InputTurnState] = {}
        self._input_item_turns: dict[str, int] = {}
        self._active_response_input_turn: int | None = None
        self._input_cleanup_tasks: set[asyncio.Task[None]] = set()
        self._input_cleanup_fallback_tasks: set[asyncio.Task[None]] = set()
        self._barge_cancel_task: asyncio.Task[None] | None = None
        self._output_started = False
        self._output_final_emitted = False
        self._active_output_text = ""
        self._drop_audio = False
        self._closed = False

    @property
    def endpoint(self) -> str:
        return _endpoint(
            self._config.endpoint,
            self._config.region,
            self._config.realtime_model,
        )

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    async def connect(self, session: RealtimeSessionConfig) -> None:
        if self._closed:
            raise RuntimeError("DashScope realtime session is closed")
        self._session_config = session
        self._socket = await connect(
            self.endpoint,
            additional_headers=self._headers,
            open_timeout=_READY_TIMEOUT_SECONDS,
            close_timeout=5,
            ping_interval=20,
            ping_timeout=20,
            max_size=16 * 1024 * 1024,
        )
        self._receiver = asyncio.create_task(self._receive())
        try:
            await asyncio.wait_for(
                self._ready.wait(),
                timeout=_READY_TIMEOUT_SECONDS,
            )
        except BaseException:
            await self.close()
            raise

    async def _send(self, payload: dict[str, Any]) -> None:
        if self._socket is None or self._closed:
            raise RuntimeError("DashScope realtime session is not connected")
        async with self._send_lock:
            await self._socket.send(json.dumps(payload, ensure_ascii=False))

    async def _configure(self) -> None:
        session = self._session_config
        if session is None:
            raise RuntimeError("Realtime Voice session configuration is missing")
        turn_detection: dict[str, Any] = {"type": self._config.vad_mode}
        if self._config.vad_mode == "server_vad":
            turn_detection.update(
                {
                    "threshold": self._config.vad_threshold,
                    "silence_duration_ms": (self._config.vad_silence_duration_ms),
                }
            )
        await self._send(
            {
                "event_id": uuid4().hex,
                "type": "session.update",
                "session": {
                    "modalities": ["text", "audio"],
                    "voice": self._config.voice,
                    "input_audio_format": "pcm",
                    "output_audio_format": "pcm",
                    "turn_detection": turn_detection,
                    "max_history_turns": self._config.max_history_turns,
                    "instructions": session.instructions,
                    "tools": [],
                },
            }
        )

    async def send_audio(self, pcm16: bytes) -> None:
        if not pcm16:
            return
        await self._send(
            {
                "event_id": uuid4().hex,
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(pcm16).decode("ascii"),
            }
        )

    async def create_message(self, role: str, text: str) -> str:
        """Create one acknowledged Provider-private conversation item."""
        text = text.strip()
        if role not in {"system", "user"} or not text:
            raise ValueError("realtime message requires a role and text")
        await self._presentation_ready.wait()
        async with self._command_lock:
            await self._presentation_ready.wait()
            await self._idle.wait()
            return await self._create_item(
                {
                    "type": "message",
                    "role": role,
                    "content": [{"type": "input_text", "text": text}],
                }
            )

    async def request_response(self) -> ProviderResponseResult:
        """Create one serialized application-owned speech response."""
        async with self._request_lock:
            response_done = await self._create_response()
            try:
                return await asyncio.wait_for(
                    asyncio.shield(response_done),
                    timeout=_RESPONSE_TIMEOUT_SECONDS,
                )
            except asyncio.CancelledError:
                await self.interrupt_output()
                with suppress(Exception):
                    await asyncio.wait_for(
                        asyncio.shield(response_done),
                        timeout=5,
                    )
                raise

    async def delete_items(self, item_ids: Iterable[str]) -> None:
        """Delete exact Provider-private items after response terminal."""
        normalized = {item_id for item_id in item_ids if item_id}
        if not normalized:
            return
        async with self._command_lock:
            await self._idle.wait()
            await self._delete_items_unlocked(normalized)

    async def _create_item(self, item: dict[str, Any]) -> str:
        item_id = f"item_{uuid4().hex}"
        item = {"id": item_id, **item}
        acknowledged = asyncio.get_running_loop().create_future()
        self._pending_items[item_id] = acknowledged
        try:
            await self._send(
                {
                    "event_id": uuid4().hex,
                    "type": "conversation.item.create",
                    "item": item,
                }
            )
            await asyncio.wait_for(
                acknowledged,
                timeout=_COMMAND_TIMEOUT_SECONDS,
            )
        finally:
            self._pending_items.pop(item_id, None)
        return item_id

    async def _delete_items_unlocked(self, item_ids: set[str]) -> None:
        for item_id in item_ids:
            acknowledged = asyncio.get_running_loop().create_future()
            self._pending_deletions[item_id] = acknowledged
            try:
                await self._send(
                    {
                        "event_id": uuid4().hex,
                        "type": "conversation.item.delete",
                        "item_id": item_id,
                    }
                )
                await asyncio.wait_for(
                    acknowledged,
                    timeout=_COMMAND_TIMEOUT_SECONDS,
                )
            finally:
                self._pending_deletions.pop(item_id, None)

    async def _create_response(
        self,
    ) -> asyncio.Future[ProviderResponseResult]:
        async with self._response_lock:
            await self._idle.wait()
            if self._closed:
                raise RuntimeError("DashScope realtime session is closed")
            response_done = asyncio.get_running_loop().create_future()
            self._application_response_done = response_done
            self._response_requested = True
            self._pending_response_origin = "application"
            self._idle.clear()
            try:
                await self._send(
                    {
                        "event_id": uuid4().hex,
                        "type": "response.create",
                        "response": {"modalities": ["audio", "text"]},
                    }
                )
            except BaseException:
                self._response_requested = False
                self._pending_response_origin = None
                self._application_response_done = None
                self._idle.set()
                raise
            return response_done

    async def interrupt_output(self) -> None:
        async with self._response_lock:
            if self._closed or (
                not self._response_requested and not self._active_response_id
            ):
                return
            self._drop_audio = True
            with suppress(ConnectionClosed):
                await self._send(
                    {
                        "event_id": uuid4().hex,
                        "type": "response.cancel",
                    }
                )

    async def _receive(self) -> None:
        try:
            async for raw in self._socket:
                if not isinstance(raw, str):
                    continue
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    await self._handle(payload)
        except asyncio.CancelledError:
            raise
        except ConnectionClosed as exc:
            if not self._closed:
                await self._emit_exception(exc, "connection", True)
        except Exception as exc:  # noqa: BLE001
            await self._emit_exception(exc, "protocol", False)
        finally:
            self._idle.set()
            self._presentation_ready.set()
            pending = (
                tuple(self._pending_items.values())
                + tuple(self._pending_deletions.values())
            )
            for future in pending:
                if not future.done():
                    future.set_exception(
                        ConnectionError("DashScope realtime session closed")
                    )
            response_done = self._application_response_done
            if response_done is not None and not response_done.done():
                response_done.set_exception(
                    ConnectionError("DashScope realtime session closed")
                )
            if not self._closed:
                await self._events.put(_EVENTS_CLOSED)

    async def _handle(self, payload: dict[str, Any]) -> None:
        kind = str(payload.get("type") or "")
        event_id = _event_id(payload)

        if kind == "session.created":
            await self._configure()
            return
        if kind == "session.updated":
            self._ready.set()
            await self._events.put(ProviderEvent("session.ready", event_id))
            return
        if kind == "conversation.item.created":
            item = payload.get("item")
            item_id = str(item.get("id") or "") if isinstance(item, dict) else ""
            future = self._pending_items.get(item_id)
            if future is not None and not future.done():
                future.set_result(None)
            elif isinstance(item, dict):
                role = str(item.get("role") or "")
                if role == "user" and item_id:
                    turn_id, turn = self._current_input_turn()
                    turn.item_ids.add(item_id)
                    self._input_item_turns[item_id] = turn_id
                elif role == "assistant" and item_id:
                    self._active_response_items.add(item_id)
            return
        if kind == "conversation.item.deleted":
            item_id = str(payload.get("item_id") or "")
            future = self._pending_deletions.get(item_id)
            if future is not None and not future.done():
                future.set_result(None)
            return
        if kind == "input_audio_buffer.speech_started":
            self._presentation_ready.clear()
            self._input_turn_sequence += 1
            self._active_input_turn = self._input_turn_sequence
            self._input_turns[self._active_input_turn] = _InputTurnState()
            response_id = self._active_response_id
            if self._response_requested or response_id:
                self._drop_audio = True
            await self._events.put(ProviderEvent("speech.started", event_id))
            if self._response_requested or response_id:
                self._schedule_barge_cancel(response_id)
            return
        if kind == "input_audio_buffer.speech_stopped":
            await self._events.put(ProviderEvent("speech.stopped", event_id))
            return
        if kind in {
            "conversation.item.input_audio_transcription.delta",
            "conversation.item.input_audio_transcription.text",
        }:
            # Both wire events carry a confirmed prefix plus a revisable suffix.
            text = str(payload.get("text") or "") + str(
                payload.get("stash") or "",
            )
            await self._events.put(
                ProviderEvent(
                    "input_transcript.partial",
                    event_id,
                    {"text": text},
                    correlation_id=(str(payload.get("item_id") or "") or None),
                )
            )
            return
        if kind == "conversation.item.input_audio_transcription.completed":
            text = str(payload.get("transcript") or payload.get("text") or "").strip()
            item_id = str(payload.get("item_id") or "")
            turn_id = self._input_item_turns.get(item_id)
            turn = self._input_turns.get(turn_id or -1)
            if turn is None:
                turn_id, turn = self._current_input_turn()
            if item_id:
                turn.item_ids.add(item_id)
                self._input_item_turns[item_id] = turn_id
            turn.transcript_final = True
            if text:
                await self._events.put(
                    ProviderEvent(
                        "input_transcript.final",
                        event_id,
                        {"text": text},
                        correlation_id=(item_id or None),
                    )
                )
            self._schedule_input_cleanup_if_ready(turn_id)
            self._schedule_input_cleanup_fallback(turn_id)
            return
        if kind == "response.created":
            response = payload.get("response")
            response_id = (
                str(response.get("id") or "") if isinstance(response, dict) else ""
            )
            origin = self._pending_response_origin or "provider_auto"
            self._response_requested = False
            self._pending_response_origin = None
            self._active_response_id = response_id or event_id
            self._active_response_origin = origin
            self._active_response_input_turn = (
                self._current_input_turn()[0]
                if origin == "provider_auto"
                else None
            )
            self._active_response_items.clear()
            self._output_started = False
            self._output_final_emitted = False
            self._active_output_text = ""
            self._drop_audio = origin != "application"
            self._idle.clear()
            await self._events.put(
                ProviderEvent(
                    "response.started",
                    event_id,
                    correlation_id=self._active_response_id,
                    response_origin=origin,
                )
            )
            if origin == "provider_auto":
                await self.interrupt_output()
            return
        if kind in {"response.output_item.added", "response.output_item.done"}:
            item = payload.get("item")
            item_id = str(item.get("id") or "") if isinstance(item, dict) else ""
            if item_id:
                self._active_response_items.add(item_id)
            return
        if kind in {
            "response.audio_transcript.delta",
            "response.text.delta",
            "response.output_text.delta",
        }:
            text = str(payload.get("delta") or "")
            if text and self._active_response_origin == "application":
                self._active_output_text += text
                await self._start_output(event_id)
                await self._events.put(
                    ProviderEvent(
                        "output_transcript.partial",
                        event_id,
                        {"text": text},
                        correlation_id=self._active_response_id,
                        response_origin=self._active_response_origin,
                    )
                )
            return
        if kind in {
            "response.audio_transcript.done",
            "response.text.done",
            "response.output_text.done",
        }:
            text = str(payload.get("transcript") or payload.get("text") or "").strip()
            if (
                text
                and not self._output_final_emitted
                and self._active_response_origin == "application"
            ):
                self._active_output_text = text
                self._output_final_emitted = True
                await self._events.put(
                    ProviderEvent(
                        "output_transcript.final",
                        event_id,
                        {"text": text},
                        correlation_id=self._active_response_id,
                        response_origin=self._active_response_origin,
                    )
                )
            return
        if kind == "response.audio.delta":
            encoded = payload.get("delta")
            if (
                self._active_response_origin == "application"
                and not self._drop_audio
                and isinstance(encoded, str)
            ):
                try:
                    audio = base64.b64decode(encoded, validate=True)
                except ValueError:
                    audio = b""
                if audio:
                    await self._start_output(event_id)
                    await self._events.put(
                        ProviderEvent(
                            "output.audio",
                            event_id,
                            audio=audio,
                            correlation_id=self._active_response_id,
                            response_origin=self._active_response_origin,
                        )
                    )
            return
        if kind == "response.done":
            response = payload.get("response")
            status = (
                str(response.get("status") or "completed")
                if isinstance(response, dict)
                else "completed"
            )
            correlation_id = self._active_response_id
            response_origin = self._active_response_origin or "provider_auto"
            had_output = self._output_started
            response_items = set(self._active_response_items)
            transcript = self._active_output_text.strip()
            if isinstance(response, dict):
                output = response.get("output")
                if isinstance(output, list):
                    for item in output:
                        if not isinstance(item, dict):
                            continue
                        item_id = str(item.get("id") or "")
                        if item_id:
                            response_items.add(item_id)
            response_done = self._application_response_done
            response_input_turn = self._active_response_input_turn
            self._response_requested = False
            self._pending_response_origin = None
            self._active_response_id = None
            self._active_response_origin = None
            self._active_response_input_turn = None
            self._active_response_items.clear()
            self._output_started = False
            self._output_final_emitted = False
            self._active_output_text = ""
            self._drop_audio = False
            self._idle.set()
            barge_cancel = self._barge_cancel_task
            self._barge_cancel_task = None
            if barge_cancel is not None:
                barge_cancel.cancel()
            if response_origin == "application":
                self._application_response_done = None
                if response_done is not None and not response_done.done():
                    response_done.set_result(
                        ProviderResponseResult(
                            status=status,
                            item_ids=tuple(sorted(response_items)),
                            transcript=transcript,
                        )
                    )
            else:
                turn_id = response_input_turn
                turn = self._input_turns.get(turn_id or -1)
                if turn is None:
                    turn_id, turn = self._current_input_turn()
                turn.item_ids.update(response_items)
                turn.auto_response_terminal = True
                self._schedule_input_cleanup_if_ready(turn_id)
            if had_output:
                await self._events.put(
                    ProviderEvent(
                        "output.stopped",
                        event_id,
                        {"status": status},
                        correlation_id=correlation_id,
                        response_origin=response_origin,
                    )
                )
            await self._events.put(
                ProviderEvent(
                    "response.finished",
                    event_id,
                    {"status": status},
                    correlation_id=correlation_id,
                    response_origin=response_origin,
                )
            )
            return
        if kind == "error":
            error = payload.get("error")
            if not isinstance(error, dict):
                error = {}
            missing_item = _missing_deleted_item(
                error,
                self._pending_deletions,
            )
            if missing_item:
                pending = self._pending_deletions.get(missing_item)
                if pending is not None and not pending.done():
                    pending.set_result(None)
                return
            if _is_response_busy_error(error):
                # Server VAD can attempt an automatic response while an
                # application response is active. Retrying it would create
                # duplicate speech, so this expected automatic response dies.
                return
            message = str(error.get("message") or "DashScope realtime error")
            code = str(error.get("code") or "provider_error")
            await self._events.put(
                ProviderEvent(
                    "error",
                    event_id,
                    {
                        "code": code,
                        "message": message[:500],
                        "recoverable": True,
                        "source": "provider",
                    },
                )
            )

    def _schedule_barge_cancel(self, response_id: str | None) -> None:
        task = self._barge_cancel_task
        if task is not None:
            task.cancel()
        self._barge_cancel_task = asyncio.create_task(
            self._cancel_after_barge_timeout(response_id)
        )

    async def _cancel_after_barge_timeout(
        self,
        response_id: str | None,
    ) -> None:
        try:
            await asyncio.sleep(_BARGE_IN_CANCEL_FALLBACK_SECONDS)
            if (
                self._response_requested
                or (
                    response_id is not None
                    and self._active_response_id == response_id
                )
            ):
                await self.interrupt_output()
        except asyncio.CancelledError:
            return

    def _current_input_turn(self) -> tuple[int, _InputTurnState]:
        turn_id = self._active_input_turn
        turn = self._input_turns.get(turn_id)
        if turn is not None:
            return turn_id, turn
        self._input_turn_sequence += 1
        turn_id = self._input_turn_sequence
        self._active_input_turn = turn_id
        turn = _InputTurnState()
        self._input_turns[turn_id] = turn
        self._presentation_ready.clear()
        return turn_id, turn

    def _schedule_input_cleanup_if_ready(self, turn_id: int) -> None:
        turn = self._input_turns.get(turn_id)
        if (
            turn is None
            or not turn.transcript_final
            or not turn.auto_response_terminal
            or turn.cleanup_scheduled
        ):
            return
        turn.cleanup_scheduled = True
        task = asyncio.create_task(
            self._cleanup_input_turn(turn_id, set(turn.item_ids))
        )
        self._input_cleanup_tasks.add(task)
        task.add_done_callback(self._input_cleanup_tasks.discard)

    def _schedule_input_cleanup_fallback(self, turn_id: int) -> None:
        task = asyncio.create_task(
            self._finish_input_without_auto_response(turn_id)
        )
        self._input_cleanup_fallback_tasks.add(task)
        task.add_done_callback(self._input_cleanup_fallback_tasks.discard)

    async def _finish_input_without_auto_response(self, turn_id: int) -> None:
        try:
            await asyncio.sleep(_INPUT_CLEANUP_FALLBACK_SECONDS)
            turn = self._input_turns.get(turn_id)
            if (
                turn is not None
                and turn.transcript_final
                and not turn.auto_response_terminal
                and self._active_response_origin != "provider_auto"
            ):
                turn.auto_response_terminal = True
                self._schedule_input_cleanup_if_ready(turn_id)
        except asyncio.CancelledError:
            return

    async def _cleanup_input_turn(
        self,
        turn_id: int,
        item_ids: set[str],
    ) -> None:
        try:
            async with self._command_lock:
                await self._idle.wait()
                await self._delete_items_unlocked(item_ids)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            await self._emit_exception(exc, "cleanup", True)
        finally:
            self._input_turns.pop(turn_id, None)
            for item_id in item_ids:
                self._input_item_turns.pop(item_id, None)
            if turn_id == self._active_input_turn:
                self._presentation_ready.set()

    async def _start_output(self, event_id: str) -> None:
        if self._output_started or self._active_response_origin != "application":
            return
        self._output_started = True
        await self._events.put(
            ProviderEvent(
                "output.started",
                event_id,
                correlation_id=self._active_response_id,
                response_origin=self._active_response_origin,
            )
        )

    async def _emit_exception(
        self,
        exc: Exception,
        source: str,
        recoverable: bool,
    ) -> None:
        if self._closed:
            return
        await self._events.put(
            ProviderEvent(
                "error",
                uuid4().hex,
                {
                    "code": f"{source}_error",
                    "message": str(exc)[:500],
                    "recoverable": recoverable,
                    "source": source,
                },
            )
        )

    async def events(self) -> AsyncIterator[ProviderEvent]:
        while True:
            event = await self._events.get()
            if event is _EVENTS_CLOSED:
                return
            if isinstance(event, ProviderEvent):
                yield event

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        background = tuple(
            task
            for task in (
                *self._input_cleanup_tasks,
                *self._input_cleanup_fallback_tasks,
                self._barge_cancel_task,
            )
            if task is not None and not task.done()
        )
        for task in background:
            task.cancel()
        if background:
            await asyncio.gather(*background, return_exceptions=True)
        self._input_cleanup_tasks.clear()
        self._input_cleanup_fallback_tasks.clear()
        self._input_turns.clear()
        self._input_item_turns.clear()
        self._barge_cancel_task = None
        socket = self._socket
        self._socket = None
        if socket is not None:
            with suppress(Exception):
                await socket.close()
        if self._receiver is not None:
            self._receiver.cancel()
            await asyncio.gather(self._receiver, return_exceptions=True)
            self._receiver = None
        self._idle.set()
        self._presentation_ready.set()
        await self._events.put(_EVENTS_CLOSED)


def create_dashscope_session(
    config: EffectiveRealtimeVoiceConfig,
    api_key: str,
) -> DashScopeRealtimeSession:
    return DashScopeRealtimeSession(config, api_key)


DASHSCOPE_REGISTRATION = RealtimeProviderRegistration(
    provider_id="dashscope",
    models=(
        RealtimeVoiceModelConfig(
            id="qwen-audio-realtime",
            name="Qwen Audio Realtime",
            region="beijing",
            realtime_model="qwen-audio-3.0-realtime-flash",
            voice="longanqian",
            language="zh",
            vad=RealtimeVoiceVadConfig(
                mode="server_vad",
                threshold=0.5,
                silence_duration_ms=800,
            ),
            max_history_turns=20,
            max_session_seconds=3600,
        ),
    ),
    regions=(
        RegionOption(id="beijing", label="China (Beijing)"),
        RegionOption(id="singapore", label="International (Singapore)"),
    ),
    vad_modes=("server_vad", "smart_turn"),
    speech_models=(
        SpeechModelOption(
            id="qwen-audio-3.0-realtime-flash",
            label="Qwen Audio 3 Realtime Flash",
        ),
        SpeechModelOption(
            id="qwen-audio-3.0-realtime-plus",
            label="Qwen Audio 3 Realtime Plus",
        ),
    ),
    media=MediaConfig(
        input_sample_rate=16000,
        output_sample_rate=24000,
        channels=1,
    ),
    factory=create_dashscope_session,
    context_max_chars=1800,
)

__all__ = ["DASHSCOPE_REGISTRATION", "DashScopeRealtimeSession"]
