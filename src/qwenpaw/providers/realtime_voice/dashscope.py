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
_EXPECTED_CLOSE_REASONS = {
    "response_idle_timeout": "idle_timeout",
}


def _field(data: Any, key: str) -> str:
    return str(data.get(key) or "") if isinstance(data, dict) else ""


def _is_response_busy_error(error: dict[str, Any]) -> bool:
    return _field(error, "code") == "invalid_value" and (
        _field(error, "param") == "response.create"
        or "response" in _field(error, "message").lower()
    )


def _missing_deleted_item(
    error: dict[str, Any],
    pending_item_ids: Iterable[str],
) -> str | None:
    """Return a pending deletion that the Provider already removed."""
    if _field(error, "code") != "invalid_value":
        return None
    message = _field(error, "message")
    if "cannot find item" not in message.lower():
        return None
    return next(
        (item_id for item_id in pending_item_ids if item_id in message), None
    )


def _endpoint(override: str | None, region: str, model: str) -> str:
    if override and "model=" in override:
        return override
    query = f"model={quote(model, safe='')}"
    if override:
        separator = "&" if "?" in override else "?"
        return f"{override}{separator}{query}"
    return f"wss://{_REGION_DOMAINS[region]}/api-ws/v1/realtime?{query}"


@dataclass
class _InputTurnState:
    item_ids: set[str] = field(default_factory=set)
    source_item_id: str = ""
    speech_started: bool = False
    transcript_final: bool = False
    auto_response_terminal: bool = False
    cleanup_scheduled: bool = False
    pending_call_ids: set[str] = field(default_factory=set)


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
        self._active_response_input_item_id: str | None = None
        self._active_response_had_tool_call = False
        self._tool_call_turns: dict[str, int] = {}
        self._input_cleanup_tasks: set[asyncio.Task[None]] = set()
        self._input_cleanup_fallback_tasks: set[asyncio.Task[None]] = set()
        self._barge_cancel_task: asyncio.Task[None] | None = None
        self._output_started = False
        self._output_final_emitted = False
        self._active_output_text = ""
        self._drop_audio = False
        self._expected_close_reason: str | None = None
        self._closed = False

    @property
    def endpoint(self) -> str:
        return _endpoint(
            self._config.endpoint,
            self._config.region,
            self._config.realtime_model,
        )

    @property
    def _has_tools(self) -> bool:
        return bool(self._session_config and self._session_config.tools)

    def _should_emit_active_output(self) -> bool:
        return self._active_response_origin == "application" or self._has_tools

    async def connect(self, session: RealtimeSessionConfig) -> None:
        if self._closed:
            raise RuntimeError("DashScope realtime session is closed")
        self._session_config = session
        self._socket = await connect(
            self.endpoint,
            additional_headers={"Authorization": f"Bearer {self._api_key}"},
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

    async def _send(self, event_type: str, **fields: Any) -> None:
        if self._socket is None or self._closed:
            raise RuntimeError("DashScope realtime session is not connected")
        payload = {"event_id": uuid4().hex, "type": event_type, **fields}
        async with self._send_lock:
            await self._socket.send(json.dumps(payload, ensure_ascii=False))

    async def _configure(self) -> None:
        session = self._session_config
        if session is None:
            raise RuntimeError(
                "Realtime Voice session configuration is missing"
            )
        turn_detection: dict[str, Any] = {"type": self._config.vad_mode}
        if self._config.vad_mode == "server_vad":
            turn_detection.update(
                {
                    "threshold": self._config.vad_threshold,
                    "silence_duration_ms": (
                        self._config.vad_silence_duration_ms
                    ),
                }
            )
        tools = [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in session.tools
        ]
        settings: dict[str, Any] = {
            "modalities": ["text", "audio"],
            "voice": self._config.voice,
            "input_audio_format": "pcm",
            "output_audio_format": "pcm",
            "turn_detection": turn_detection,
            "max_history_turns": self._config.max_history_turns,
            "instructions": session.instructions,
        }
        if tools:
            settings["tools"] = tools
        await self._send("session.update", session=settings)

    async def send_audio(self, pcm16: bytes) -> None:
        if not pcm16:
            return
        await self._send(
            "input_audio_buffer.append",
            audio=base64.b64encode(pcm16).decode("ascii"),
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
            # A user turn always owns the native response lane.  In particular,
            # do not let an application status response race the provider's
            # server-VAD response after speech has already started.
            await self._presentation_ready.wait()
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

    async def complete_tool_call(
        self,
        call_id: str,
        output: dict[str, Any],
    ) -> str:
        """Acknowledge one native call without waiting for task completion."""
        call_id = call_id.strip()
        if not call_id:
            raise ValueError("realtime tool call id is empty")
        async with self._command_lock:
            await self._idle.wait()
            item_id = await self._create_item(
                {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps(output, ensure_ascii=False),
                }
            )
        turn_id = self._tool_call_turns.pop(call_id, None)
        turn = self._input_turns.get(turn_id or -1)
        if turn is not None:
            turn.item_ids.add(item_id)
            turn.pending_call_ids.discard(call_id)
            self._schedule_input_cleanup_if_ready(turn_id or -1)
        return item_id

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
        acknowledged = asyncio.get_running_loop().create_future()
        self._pending_items[item_id] = acknowledged
        try:
            await self._send(
                "conversation.item.create",
                item={"id": item_id, **item},
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
                await self._send("conversation.item.delete", item_id=item_id)
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
            await self._presentation_ready.wait()
            await self._idle.wait()
            # ``_idle.wait`` can yield while a new speech turn starts.
            # Re-check the gate before creating an application response.
            await self._presentation_ready.wait()
            if self._closed:
                raise RuntimeError("DashScope realtime session is closed")
            response_done = asyncio.get_running_loop().create_future()
            self._application_response_done = response_done
            self._response_requested = True
            self._pending_response_origin = "application"
            self._idle.clear()
            try:
                await self._send(
                    "response.create",
                    response={"modalities": ["audio", "text"]},
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
                await self._send("response.cancel")

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
            if not self._closed and self._expected_close_reason is None:
                await self._emit_exception(exc, "connection", True)
        except Exception as exc:  # noqa: BLE001
            await self._emit_exception(exc, "protocol", False)
        finally:
            self._idle.set()
            self._presentation_ready.set()
            for future in (
                *self._pending_items.values(),
                *self._pending_deletions.values(),
                self._application_response_done,
            ):
                if future is not None and not future.done():
                    future.set_exception(
                        ConnectionError("DashScope realtime session closed")
                    )
            if not self._closed:
                await self._events.put(_EVENTS_CLOSED)

    async def _handle(self, payload: dict[str, Any]) -> None:
        kind = _field(payload, "type")
        event_id = _field(payload, "event_id") or uuid4().hex

        if kind == "session.created":
            await self._configure()
            return
        if kind == "session.updated":
            self._ready.set()
            await self._events.put(ProviderEvent("session.ready", event_id))
            return
        if kind == "conversation.item.created":
            item = payload.get("item")
            item_id = _field(item, "id")
            future = self._pending_items.get(item_id)
            if future is not None and not future.done():
                future.set_result(None)
            elif isinstance(item, dict):
                role = _field(item, "role")
                if role == "user" and item_id:
                    self._input_turn_for_item(item_id)
                elif role == "assistant" and item_id:
                    self._active_response_items.add(item_id)
            return
        if kind == "conversation.item.deleted":
            item_id = _field(payload, "item_id")
            future = self._pending_deletions.get(item_id)
            if future is not None and not future.done():
                future.set_result(None)
            return
        if kind == "input_audio_buffer.speech_started":
            item_id = _field(payload, "item_id")
            turn_id, turn = self._input_turn_for_item(item_id)
            if turn is None or turn.speech_started or turn.transcript_final:
                return
            turn.speech_started = True
            self._presentation_ready.clear()
            self._active_input_turn = turn_id
            response_id = self._active_response_id
            if self._response_requested or response_id:
                self._drop_audio = True
            await self._events.put(
                ProviderEvent(
                    "speech.started",
                    event_id,
                    correlation_id=item_id or None,
                )
            )
            # Always arm the fallback.  An application response.create may
            # already be in flight and become active only after this server-VAD
            # event; capturing ``None`` is how the timeout detects that race.
            self._schedule_barge_cancel(response_id)
            return
        if kind == "input_audio_buffer.speech_stopped":
            await self._events.put(
                ProviderEvent(
                    "speech.stopped",
                    event_id,
                    correlation_id=_field(payload, "item_id") or None,
                )
            )
            return
        if kind in {
            "conversation.item.input_audio_transcription.delta",
            "conversation.item.input_audio_transcription.text",
        }:
            # Both wire events carry a confirmed prefix plus a revisable
            # suffix.
            text = _field(payload, "text") + _field(payload, "stash")
            await self._events.put(
                ProviderEvent(
                    "input_transcript.partial",
                    event_id,
                    {"text": text},
                    correlation_id=_field(payload, "item_id") or None,
                )
            )
            return
        if kind in {
            "conversation.item.input_audio_transcription.completed",
            "conversation.item.input_audio_transcription.failed",
        }:
            text = (
                _field(payload, "transcript") or _field(payload, "text")
            ).strip()
            item_id = _field(payload, "item_id")
            turn_id, turn = self._input_turn_for_item(item_id)
            if turn is None or turn.transcript_final:
                return
            turn.transcript_final = True
            failed = kind.endswith(".failed")
            await self._events.put(
                ProviderEvent(
                    "input_transcript.failed"
                    if failed
                    else "input_transcript.final",
                    event_id,
                    {"code": "voice_transcription_failed"}
                    if failed
                    else {"text": text},
                    correlation_id=item_id or None,
                )
            )
            self._schedule_input_cleanup_if_ready(turn_id)
            self._schedule_input_cleanup_fallback(turn_id)
            return
        if kind == "response.created":
            response_id = _field(payload.get("response"), "id")
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
            response_turn = self._input_turns.get(
                self._active_response_input_turn or -1
            )
            self._active_response_input_item_id = (
                response_turn.source_item_id if response_turn else None
            )
            self._active_response_had_tool_call = False
            self._active_response_items.clear()
            self._output_started = False
            self._output_final_emitted = False
            self._active_output_text = ""
            self._drop_audio = not self._should_emit_active_output()
            self._idle.clear()
            await self._events.put(
                ProviderEvent(
                    "response.started",
                    event_id,
                    correlation_id=self._active_response_id,
                    data={
                        "input_item_id": (
                            self._active_response_input_item_id or ""
                        )
                    },
                    response_origin=origin,
                )
            )
            if origin == "provider_auto" and not self._has_tools:
                await self.interrupt_output()
            return
        if kind in {"response.output_item.added", "response.output_item.done"}:
            item = payload.get("item")
            item_id = _field(item, "id")
            if item_id:
                self._active_response_items.add(item_id)
            return
        if kind == "response.function_call_arguments.done":
            call_id = _field(payload, "call_id").strip()
            name = _field(payload, "name").strip()
            tools = self._session_config.tools if self._session_config else ()
            if not call_id or name not in {tool.name for tool in tools}:
                await self._emit_error(
                    event_id,
                    "unsupported_realtime_tool_call",
                    "The realtime provider requested an unsupported tool.",
                )
                return
            turn_id = self._active_response_input_turn
            turn = self._input_turns.get(turn_id or -1)
            source_item_id = turn.source_item_id if turn else ""
            if turn is None or not source_item_id:
                await self._emit_error(
                    event_id,
                    "missing_realtime_tool_input",
                    "The realtime tool call could not be matched to its "
                    "input.",
                )
                return
            self._active_response_had_tool_call = True
            turn.pending_call_ids.add(call_id)
            self._tool_call_turns[call_id] = turn_id or -1
            await self._events.put(
                ProviderEvent(
                    "tool.call",
                    event_id,
                    {
                        "call_id": call_id,
                        "name": name,
                        "arguments": _field(payload, "arguments"),
                        "item_id": _field(payload, "item_id"),
                        "input_item_id": source_item_id,
                    },
                    correlation_id=call_id,
                    response_origin="provider_auto",
                )
            )
            return
        if kind in {
            "response.audio_transcript.delta",
            "response.text.delta",
            "response.output_text.delta",
        }:
            text = _field(payload, "delta")
            if text and self._should_emit_active_output():
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
            text = (
                _field(payload, "transcript") or _field(payload, "text")
            ).strip()
            if (
                text
                and not self._output_final_emitted
                and self._should_emit_active_output()
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
                self._should_emit_active_output()
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
            status = _field(response, "status") or "completed"
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
                        if item_id := _field(item, "id"):
                            response_items.add(item_id)
            response_done = self._application_response_done
            response_input_turn = self._active_response_input_turn
            response_input_item_id = self._active_response_input_item_id
            response_had_tool_call = self._active_response_had_tool_call
            self._response_requested = False
            self._pending_response_origin = None
            self._active_response_id = None
            self._active_response_origin = None
            self._active_response_input_turn = None
            self._active_response_input_item_id = None
            self._active_response_had_tool_call = False
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
                    {
                        "status": status,
                        "input_item_id": response_input_item_id or "",
                        "had_tool_call": response_had_tool_call,
                        "transcript": transcript,
                    },
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
            message = _field(error, "message") or "DashScope realtime error"
            code = _field(error, "code") or "provider_error"
            close_reason = _EXPECTED_CLOSE_REASONS.get(code)
            if close_reason is not None:
                self._expected_close_reason = close_reason
                await self._events.put(
                    ProviderEvent(
                        "session.closed",
                        event_id,
                        {
                            "reason": close_reason,
                            "recoverable": True,
                        },
                    )
                )
                return
            await self._emit_error(event_id, code, message[:500])

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
                or (
                    response_id is None
                    and self._active_response_origin == "application"
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
        turn_id, turn = self._new_input_turn()
        self._active_input_turn = turn_id
        self._presentation_ready.clear()
        return turn_id, turn

    def _new_input_turn(self) -> tuple[int, _InputTurnState]:
        self._input_turn_sequence += 1
        turn_id = self._input_turn_sequence
        turn = self._input_turns[turn_id] = _InputTurnState()
        return turn_id, turn

    def _input_turn_for_item(
        self,
        item_id: str,
    ) -> tuple[int, _InputTurnState | None]:
        if item_id in self._input_item_turns:
            turn_id = self._input_item_turns[item_id]
            return turn_id, self._input_turns.get(turn_id)
        turn_id, turn = self._new_input_turn()
        if item_id:
            turn.source_item_id = item_id
            self._input_item_turns[item_id] = turn_id
            turn.item_ids.add(item_id)
        if self._active_input_turn not in self._input_turns:
            self._active_input_turn = turn_id
            self._presentation_ready.clear()
        return turn_id, turn

    def _schedule_input_cleanup_if_ready(self, turn_id: int) -> None:
        turn = self._input_turns.get(turn_id)
        if (
            turn is None
            or not turn.transcript_final
            or not turn.auto_response_terminal
            or turn.pending_call_ids
            or turn.cleanup_scheduled
        ):
            return
        turn.cleanup_scheduled = True
        if self._has_tools:
            self._input_turns.pop(turn_id, None)
            if not self._input_turns:
                self._presentation_ready.set()
            return
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
            # Keep identity tombstones until close: a duplicate/late event
            # must not recreate a cleaned input or attach it to newer speech.
            if turn_id == self._active_input_turn:
                self._presentation_ready.set()

    async def _start_output(self, event_id: str) -> None:
        if self._output_started or not self._should_emit_active_output():
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
        await self._emit_error(
            uuid4().hex,
            f"{source}_error",
            str(exc)[:500],
            recoverable=recoverable,
            source=source,
        )

    async def _emit_error(
        self,
        event_id: str,
        code: str,
        message: str,
        *,
        recoverable: bool = True,
        source: str = "provider",
    ) -> None:
        await self._events.put(
            ProviderEvent(
                "error",
                event_id,
                {
                    "code": code,
                    "message": message,
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
        self._tool_call_turns.clear()
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


DASHSCOPE_REGISTRATION = RealtimeProviderRegistration(
    provider_id="dashscope",
    supports_native_tools=True,
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
    factory=DashScopeRealtimeSession,
)

__all__ = ["DASHSCOPE_REGISTRATION", "DashScopeRealtimeSession"]
