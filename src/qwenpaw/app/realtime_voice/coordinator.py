# -*- coding: utf-8 -*-
"""Application control and speech presentation for one Voice session."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections import deque
from collections.abc import AsyncIterator, Coroutine
from contextlib import suppress
from dataclasses import replace
from typing import Any
from uuid import uuid4

from ...providers.realtime_voice import (
    ProviderEvent,
    ProviderResponseResult,
    RealtimeProviderSession,
)
from ..chats.replies import ChatReply
from ..chats.timeline import ChatTimelineJournal
from .contracts import (
    RealtimeVoiceServiceError,
    VoiceTaskEvent,
    VoiceTaskReceipt,
    VoiceTaskSnapshot,
)
from .handoff import (
    VoiceHandoffController,
    VoiceHandoffError,
    VoiceWorkInput,
)
from .presentation import OutputCredit, PresentationIntent, PresentationQueue
from .prompts import (
    build_language_instruction,
    build_presentation_session_config,
    build_session_config,
    build_update_instruction,
    static_presentation_instruction,
)
from .task_bridge import VoiceTaskBridge

_EVENTS_CLOSED = object()
_INPUT_EVENTS = {
    "speech.started",
    "speech.stopped",
    "input_transcript.partial",
    "input_transcript.final",
    "input_transcript.failed",
}
_RESPONSE_EVENTS = {
    "response.started",
    "response.finished",
    "output.started",
    "output.stopped",
    "output.audio",
    "output_transcript.partial",
    "output_transcript.final",
}
_TERMINAL_TASK_STATUSES = {"responded", "failed", "cancelled"}


def _history_unavailable() -> RealtimeVoiceServiceError:
    return RealtimeVoiceServiceError(
        "voice_history_unavailable",
        "Could not restore conversation history. Retry Voice Chat.",
        503,
    )


def _has_content(reply: ChatReply) -> bool:
    return reply.phase != "incomplete" and bool(reply.text or reply.media_refs)


def _dialogue_turn_id(source_id: str) -> str:
    digest = hashlib.sha256(source_id.encode()).hexdigest()
    return f"voice_dialogue_{digest[:32]}"


class VoiceCoordinator:
    """Keep application control durable while speech remains interruptible."""

    # Keep the per-session lifecycle state together.
    # pylint: disable-next=too-many-statements
    def __init__(
        self,
        provider: RealtimeProviderSession,
        bridge: VoiceTaskBridge,
        timeline: ChatTimelineJournal,
        *,
        presentation_provider: RealtimeProviderSession | None = None,
        language: str = "zh",
        presentation_capacity: int = 32,
        playback_timeout_seconds: float = 90,
        max_history_turns: int = 20,
        history_timeout_seconds: float = 5,
    ) -> None:
        self._provider = provider
        self._presenter = presentation_provider or provider
        self._dedicated_presenter = self._presenter is not provider
        self._language_instruction = build_language_instruction(language)
        self._session_config = build_session_config(language)
        self._presentation_session_config = build_presentation_session_config(
            language,
        )
        self._bridge = bridge
        self._handoff = VoiceHandoffController(provider, bridge)
        self._timeline = timeline
        self._events: asyncio.Queue[ProviderEvent | object] = asyncio.Queue()
        self._presentation_queue = PresentationQueue(presentation_capacity)
        self._playback_timeout = playback_timeout_seconds
        self._output_credit: OutputCredit | None = None
        self._recent_outputs: deque[OutputCredit] = deque(maxlen=3)
        self._latest_user_transcript = ""
        self._recent_user_transcripts: deque[str] = deque(
            maxlen=max_history_turns,
        )
        self._auto_response_credit: OutputCredit | None = None
        self._auto_credits: dict[str, OutputCredit] = {}
        self._auto_begun: set[str] = set()
        self._auto_output_idle = asyncio.Event()
        self._auto_output_idle.set()
        self._user_speech_idle = asyncio.Event()
        self._user_speech_idle.set()
        self._latest_source_id = ""
        self._latest_input_id = ""
        self._input_response_ready = asyncio.Event()
        self._input_response_ready.set()
        self._seen_responses: set[str] = set()
        self._presentation_failed = False
        self._active_presentation_task: asyncio.Task[None] | None = None
        self._history_tasks: set[asyncio.Task[Any]] = set()
        self._bridge_events = bridge.subscribe()
        self._tasks: set[asyncio.Task[Any]] = set()
        self._conversation_lock = asyncio.Lock()
        self._state_changed = asyncio.Event()
        self._task_snapshots: dict[str, VoiceTaskSnapshot] = {}
        self._announce_changes: set[str] = set()
        self._input_transcripts: dict[str, str] = {}
        self._auto_responses: dict[str, dict[str, Any]] = {}
        self._persisted_auto_sources: set[str] = set()
        self._handoff_sources: set[str] = set()
        self._style_inputs: dict[str, VoiceWorkInput] = {}
        self._style_call_ids: set[str] = set()
        self._chat_owned_sources: set[str] = set()
        self._chat_owned_responses: dict[str, str] = {}
        self._chat_mode_active = False
        self._closed = False
        self._close_task: asyncio.Task[None] | None = None
        self._history_errors: dict[str, Exception] = {}
        self._live_sources: set[str] = set()
        self._max_history_turns = max_history_turns
        self._history_timeout = history_timeout_seconds

    async def start(self) -> None:
        try:
            history = await asyncio.wait_for(
                self._timeline.read_context(
                    max_turns=self._max_history_turns,
                    max_chars=12000,
                ),
                timeout=self._history_timeout,
            )
            context = json.loads(history)
            if not context.get("available"):
                raise ValueError("Conversation history is unavailable")
        except Exception as exc:
            raise _history_unavailable() from exc
        await self._provider.connect(self._session_config)
        if context.get("messages"):
            try:
                await asyncio.wait_for(
                    self._provider.create_message(
                        "user",
                        f"<startup_history>\n{history}\n</startup_history>",
                    ),
                    timeout=self._history_timeout,
                )
            except Exception as exc:
                raise _history_unavailable() from exc
        if self._dedicated_presenter:
            await self._presenter.connect(self._presentation_session_config)
        snapshots = await self._bridge.presentation_snapshots()
        # Restore Chat ownership from public Agent replies when process-local
        # task snapshots are gone; incomplete history also needs Chat context.
        self._chat_mode_active = (
            bool(snapshots)
            or bool(context.get("omitted"))
            or any(
                message.get("source") == "agent"
                for message in context.get("messages", [])
            )
        )
        self._task_snapshots.update((s.task_id, s) for s in snapshots)
        self._start(self._pump_provider())
        if self._dedicated_presenter:
            self._start(self._pump_presenter())
        self._start(self._pump_presentation())
        self._start(self._pump_bridge_events())
        self._start(self._pump_task_state())
        self._start(self._reconcile_timeline())

    def _start(
        self,
        coroutine: Coroutine[Any, Any, Any],
    ) -> asyncio.Task[Any]:
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def _start_history(
        self,
        coroutine: Coroutine[Any, Any, Any],
    ) -> asyncio.Task[Any]:
        """Start a durable write that close() awaits instead of cancelling."""
        task = self._start(coroutine)
        self._history_tasks.add(task)
        task.add_done_callback(self._history_finished)
        return task

    def _history_finished(self, task: asyncio.Task[Any]) -> None:
        self._history_tasks.discard(task)
        if not task.cancelled() and (error := task.exception()) is not None:
            self._history_errors[f"save:{id(task)}"] = error

    def _emit(
        self,
        kind: str,
        data: dict[str, Any],
        **fields: Any,
    ) -> None:
        self._events.put_nowait(
            ProviderEvent(kind, uuid4().hex, data, **fields),
        )

    def _emit_error(
        self,
        code: str,
        message: str,
        *,
        source: str,
        correlation_id: str | None = None,
    ) -> None:
        self._emit(
            "error",
            {
                "code": code,
                "message": message,
                "recoverable": True,
                "source": source,
            },
            correlation_id=correlation_id,
        )

    async def send_audio(self, pcm16: bytes) -> None:
        await self._provider.send_audio(pcm16)

    async def interrupt(self) -> None:
        self._preempt_presentation("interrupt")
        await self._provider.interrupt_output()
        if self._dedicated_presenter:
            await self._presenter.interrupt_output()

    def playback_feedback(self, output_id: str, status: str) -> None:
        """The relay has already checked the connection generation."""
        if self._output_credit is not None:
            self._output_credit.acknowledge(output_id, status)
        credit = self._auto_credits.get(output_id)
        if credit is not None:
            credit.acknowledge(output_id, status)

    async def observe_agent_run(self) -> None:
        run_id = await self._bridge.observe_active_run()
        if run_id:
            self._emit(
                "agent.run.started",
                {"run_id": run_id, "status": "observing"},
            )

    # Provider events share ordered input and response state transitions.
    # pylint: disable-next=too-many-branches
    async def _pump_provider(self) -> None:
        try:
            async for event in self._provider.events():
                kind = event.kind
                source_id = str(event.correlation_id or "")
                if kind in _INPUT_EVENTS and not source_id:
                    self._emit_error(
                        "missing_turn_identity",
                        "The speech provider did not supply a stable input "
                        "item identifier.",
                        source="coordinator",
                    )
                    continue
                if kind in {
                    "input_transcript.partial",
                    "input_transcript.final",
                }:
                    text = str(event.data.get("text") or "").strip()
                    self._bridge.observe_transcript(
                        source_id,
                        text,
                        final=kind == "input_transcript.final",
                    )
                if kind == "input_transcript.final":
                    self._latest_user_transcript = text[:4000]
                    if text:
                        self._recent_user_transcripts.append(text[:1000])
                    self._start_history(
                        self._persist_handoff_transcript(source_id),
                    )
                    self._live_sources.add(source_id)
                    self._input_transcripts[source_id] = text
                    if self._chat_mode_active:
                        self._chat_owned_sources.add(source_id)
                    self._start(self._persist_auto_exchange(source_id))
                elif kind == "input_transcript.failed":
                    self._input_transcripts[source_id] = ""
                    self._start(self._persist_auto_exchange(source_id))
                elif kind == "speech.started":
                    self._latest_user_transcript = ""
                    self._latest_source_id = source_id
                    self._latest_input_id = ""
                    self._input_response_ready.clear()
                    self._user_speech_idle.clear()
                    self._live_sources.add(source_id)
                    if self._chat_mode_active:
                        self._chat_owned_sources.add(source_id)
                    self._preempt_presentation("barge_in")
                elif kind == "speech.stopped":
                    self._user_speech_idle.set()
                if kind == "tool.call":
                    self._start(self._handle_tool_call(event))
                elif kind in _RESPONSE_EVENTS:
                    self._handle_response_event(event)
                else:
                    self._events.put_nowait(event)
        finally:
            self._events.put_nowait(_EVENTS_CLOSED)

    async def _pump_presenter(self) -> None:
        async for event in self._presenter.events():
            if event.kind in _RESPONSE_EVENTS:
                self._handle_response_event(event)

    async def _handle_tool_call(self, event: ProviderEvent) -> None:
        try:
            work = self._handoff.parse(event)
            if work.source_id not in self._live_sources:
                raise VoiceHandoffError(
                    "Work must belong to a live speech input",
                )
            if work.action == "update_response_style":
                if work.call_id in self._style_call_ids:
                    return
                self._style_call_ids.add(work.call_id)
                self._style_inputs.setdefault(work.source_id, work)
                self._start(self._persist_auto_exchange(work.source_id))
                await self._provider.complete_tool_call(
                    work.call_id,
                    {"accepted": True, "action": work.action},
                )
                return
            # Admission belongs to the bridge and may finish after this
            # connection closes, even if its receipt has not arrived yet.
            self._handoff_sources.add(work.source_id)
            self._start(self._persist_auto_exchange(work.source_id))
            result = await self._handoff.handle(event)
        except VoiceHandoffError as exc:
            self._release_input_response(
                str(event.data.get("input_item_id") or ""),
            )
            call_id = str(
                event.data.get("call_id") or event.correlation_id or "",
            )
            if call_id:
                with suppress(Exception):
                    await self._provider.complete_tool_call(
                        call_id,
                        {"accepted": False, "message": str(exc)},
                    )
            self._emit_error(
                "invalid_voice_handoff",
                str(exc),
                source="coordinator",
                correlation_id=call_id or None,
            )
            return
        except Exception as exc:  # noqa: BLE001
            self._release_input_response(
                str(event.data.get("input_item_id") or ""),
            )
            self._emit_error(
                "voice_handoff_failed",
                str(exc)[:500] or "The voice request could not be admitted.",
                source="coordinator",
                correlation_id=event.correlation_id,
            )
            return
        if not result.replayed:
            await self._publish_handoff(result.work, result.receipt)

    async def _publish_handoff(
        self,
        work: VoiceWorkInput,
        receipt: VoiceTaskReceipt,
    ) -> None:
        if receipt.accepted:
            self._chat_mode_active = True
        self._emit(
            "input_turn.committed"
            if receipt.accepted
            else "input_turn.rejected",
            {
                "turn_id": work.input_id,
                "source_count": 1,
                "origin": "native",
                "action": work.action,
                **({"message": receipt.message} if receipt.message else {}),
            },
            correlation_id=work.input_id,
        )
        await self._publish_admission(work, receipt)
        await self._queue_admission(work, receipt)
        if work.source_id == self._latest_source_id:
            if receipt.accepted:
                self._latest_input_id = receipt.input_id or receipt.task_id
                self._state_changed.set()
            else:
                self._release_input_response(work.source_id)

    def _release_input_response(self, source_id: str) -> None:
        if source_id == self._latest_source_id:
            self._input_response_ready.set()

    def _refresh_input_response(self) -> None:
        """Release old speech only after the latest input has a response."""
        if not self._latest_input_id:
            return
        for snapshot in self._task_snapshots.values():
            if any(
                self._latest_input_id in reply.input_ids
                and _has_content(reply)
                for reply in snapshot.replies
            ) or dict(snapshot.input_states).get(self._latest_input_id) in {
                "completed",
                "failed",
                "cancelled",
            }:
                self._input_response_ready.set()
                return

    def _handle_response_event(self, event: ProviderEvent) -> None:
        if event.response_origin == "provider_auto":
            self._handle_auto_response_event(event)
            return
        if event.response_origin != "application":
            return
        credit = self._output_credit
        response_id = event.correlation_id or ""
        # Bind only a new response belonging to the current requested output.
        if (  # pylint: disable=too-many-boolean-expressions
            event.kind == "response.started"
            and credit is not None
            and credit.requested
            and not credit.provider_id
            and response_id
            and response_id not in self._seen_responses
        ):
            credit.provider_id = response_id
            self._seen_responses.add(response_id)
        if (
            credit is None
            or credit.sealed
            or response_id != credit.provider_id
        ):
            return
        if not credit.cancelled:
            if event.kind in {
                "output_transcript.partial",
                "output_transcript.final",
            }:
                credit.observe_transcript(
                    str(event.data.get("text") or ""),
                    final=event.kind == "output_transcript.final",
                )
            self._events.put_nowait(
                replace(
                    event,
                    data={**event.data, "output_id": credit.output_id},
                ),
            )
        if event.kind == "response.finished":
            credit.seal()
            if not credit.cancelled:
                self._emit("output.sealed", {"output_id": credit.output_id})

    # Keep native response ownership and credit completion in one handler.
    # pylint: disable-next=too-many-branches
    def _handle_auto_response_event(self, event: ProviderEvent) -> None:
        response_id = str(event.correlation_id or "")
        source_id = str(event.data.get("input_item_id") or "")
        if event.kind == "response.started" and source_id:
            self._chat_owned_responses[response_id] = source_id
        owned_source = self._chat_owned_responses.get(response_id, source_id)
        if owned_source in self._chat_owned_sources:
            if event.kind == "response.finished":
                self._chat_owned_responses.pop(response_id, None)
                self._record_auto_response(owned_source, response_id, event)
            return
        if event.kind == "response.started":
            if not response_id or response_id in self._seen_responses:
                return
            self._seen_responses.add(response_id)
            self._auto_response_credit = OutputCredit(provider_id=response_id)
            self._auto_credits[
                self._auto_response_credit.output_id
            ] = self._auto_response_credit
        credit = self._auto_response_credit
        if (
            credit is None
            or credit.provider_id != response_id
            or credit.sealed
        ):
            return
        if (
            event.kind == "output.started"
            and credit.output_id not in self._auto_begun
        ):
            self._auto_begun.add(credit.output_id)
            self._recent_outputs.append(credit)
            self._auto_output_idle.clear()
            self._emit("output.begin", {"output_id": credit.output_id})
        if event.kind in {
            "output_transcript.partial",
            "output_transcript.final",
        }:
            credit.observe_transcript(
                str(event.data.get("text") or ""),
                final=event.kind == "output_transcript.final",
            )
        self._events.put_nowait(
            replace(event, data={**event.data, "output_id": credit.output_id}),
        )
        if event.kind != "response.finished":
            return
        if source_id:
            self._record_auto_response(source_id, response_id, event)
        credit.seal()
        if credit.output_id in self._auto_begun:
            self._emit("output.sealed", {"output_id": credit.output_id})
            self._start(self._settle_auto_credit(credit))
        else:
            self._auto_credits.pop(credit.output_id, None)
        self._auto_response_credit = None
        if not self._auto_credits:
            self._auto_output_idle.set()

    def _record_auto_response(
        self,
        source_id: str,
        response_id: str,
        event: ProviderEvent,
    ) -> None:
        self._auto_responses[source_id] = {
            "response_id": response_id,
            "status": str(event.data.get("status") or "completed"),
            "transcript": str(event.data.get("transcript") or "").strip(),
            "had_tool_call": bool(event.data.get("had_tool_call")),
        }
        self._start(self._persist_auto_exchange(source_id))

    async def _settle_auto_credit(self, credit: OutputCredit) -> None:
        try:
            await credit.wait(self._playback_timeout)
        except Exception as exc:  # noqa: BLE001
            self._emit_error(
                "voice_playback_failed",
                str(exc)[:500] or "Speech playback confirmation timed out",
                source="presentation",
                correlation_id=credit.provider_id or None,
            )
        finally:
            self._auto_credits.pop(credit.output_id, None)
            self._auto_begun.discard(credit.output_id)
            if not self._auto_credits:
                self._auto_output_idle.set()

    async def _persist_auto_exchange(self, source_id: str) -> None:
        if (
            not source_id
            or source_id in self._persisted_auto_sources
            or source_id not in self._input_transcripts
            or source_id not in self._auto_responses
        ):
            return
        style = self._style_inputs.get(source_id)
        # A terminal response can arrive before its tool handler runs.
        # Wait for the validated call instead of discarding the ASR evidence.
        if (
            self._auto_responses[source_id]["had_tool_call"]
            and style is None
            and source_id not in self._handoff_sources
        ):
            return
        self._persisted_auto_sources.add(source_id)
        response = self._auto_responses.pop(source_id)
        user_text = self._input_transcripts.pop(source_id).strip()
        chat_owned = source_id in self._chat_owned_sources
        self._chat_owned_sources.discard(source_id)
        self._style_inputs.pop(source_id, None)
        if style is not None and source_id not in self._handoff_sources:
            # Keep the final recognized words; the native request is only a
            # fallback when transcription failed. No Chat task is admitted.
            await asyncio.shield(
                self._start_history(
                    self._queue_presentation(
                        PresentationIntent(
                            "style",
                            turn_id=_dialogue_turn_id(source_id),
                            user_text=user_text or style.request_text,
                        ),
                        persist_exchange=True,
                    ),
                ),
            )
            self._release_input_response(source_id)
            return
        if response["had_tool_call"] or not user_text:
            if not response["had_tool_call"]:
                self._release_input_response(source_id)
            return
        if not chat_owned:
            self._release_input_response(source_id)
            await asyncio.shield(
                self._start_history(
                    self._save_direct_exchange(
                        source_id,
                        user_text,
                        response["transcript"],
                        response["status"],
                    ),
                ),
            )
            return
        try:
            self._handoff_sources.add(source_id)
            result = await self._handoff.handle_transcript(
                source_id,
                user_text,
            )
        except Exception as exc:  # noqa: BLE001
            self._release_input_response(source_id)
            self._emit_error(
                "voice_handoff_failed",
                str(exc)[:500] or "The voice request could not be admitted.",
                source="coordinator",
                correlation_id=source_id,
            )
            return
        await self._publish_handoff(result.work, result.receipt)

    async def _persist_handoff_transcript(self, source_id: str) -> None:
        try:
            await self._bridge.persist_transcript(source_id)
        except Exception as exc:  # noqa: BLE001
            self._emit_error(
                "voice_history_commit_failed",
                str(exc)[:500],
                source="coordinator",
                correlation_id=source_id,
            )
            raise
        if not self._closed:
            self._start(self._reconcile_timeline())

    async def _save_direct_exchange(
        self,
        source_id: str,
        user_text: str,
        assistant_text: str = "",
        status: str = "",
    ) -> None:
        turn_id = _dialogue_turn_id(source_id)
        timeline_order = await self._timeline.reserve_order()
        self._timeline.observe_voice_exchange(
            turn_id,
            user_text,
            assistant_text,
            timeline_order=timeline_order,
            generation_status=status,
        )
        await self._save_exchange(
            turn_id,
            user_text,
            assistant_text,
            timeline_order,
            generation_status=status,
        )

    async def _flush_transcript_tail(self) -> None:
        """Save received final user speech without admitting any new work."""
        tails = dict(self._input_transcripts)
        for source_id, style in self._style_inputs.items():
            tails[source_id] = tails.get(source_id) or style.request_text
        for source_id, user_text in tails.items():
            response = self._auto_responses.get(source_id, {})
            if (
                not user_text
                or source_id in self._persisted_auto_sources
                or source_id in self._handoff_sources
                or (
                    response.get("had_tool_call")
                    and source_id not in self._style_inputs
                )
            ):
                continue
            try:
                await self._save_direct_exchange(source_id, user_text)
            except Exception as exc:  # noqa: BLE001
                # A failed order reservation must not prevent the remaining
                # tail or provider connections from being closed.
                self._emit_error(
                    "voice_history_commit_failed",
                    str(exc)[:500],
                    source="coordinator",
                    correlation_id=source_id,
                )
                continue
            self._persisted_auto_sources.add(source_id)
        self._input_transcripts.clear()
        self._auto_responses.clear()
        self._style_inputs.clear()

    async def _queue_admission(
        self,
        turn: VoiceWorkInput,
        receipt: VoiceTaskReceipt,
    ) -> None:
        # Successful admission is already visible via committed/accepted
        # events. A mandatory spoken receipt delays every actual answer.
        if receipt.accepted:
            return
        await self._queue_presentation(
            PresentationIntent(
                "rejected",
                turn_id=turn.input_id,
                user_text="请告知用户本轮请求接收结果。",
                task_ref=receipt.task_ref,
            ),
            persist_exchange=True,
            history_user_text=turn.request_text,
        )

    async def _queue_presentation(
        self,
        intent: PresentationIntent,
        *,
        persist_exchange: bool,
        history_user_text: str = "",
    ) -> None:
        user_text = history_user_text or intent.user_text
        completion: asyncio.Future[ProviderResponseResult] | None = None
        timeline_order = 0
        if persist_exchange:
            timeline_order = await self._timeline.reserve_order()
            # User text survives generation failure, interruption and overload.
            self._timeline.observe_voice_exchange(
                intent.turn_id,
                user_text,
                "",
                timeline_order=timeline_order,
            )
            completion = asyncio.get_running_loop().create_future()
            self._start_history(
                self._persist_exchange(
                    intent.turn_id,
                    user_text,
                    completion,
                    timeline_order,
                ),
            )
        queued = replace(
            intent,
            completion=completion,
            timeline_order=timeline_order,
            history_user_text=user_text,
        )
        if not self._presentation_queue.put(queued):
            self._emit(
                "presentation.rejected",
                {
                    "turn_id": intent.turn_id,
                    "code": (
                        "voice_output_unavailable"
                        if self._presentation_failed
                        else "voice_output_busy"
                    ),
                    "task_admitted": intent.system_feedback,
                },
            )

    async def _pump_presentation(self) -> None:
        while await self._presentation_queue.wait():
            # Any gate can close while we await another. The presenter
            # has its own provider session and cannot observe microphone VAD.
            while True:
                await self._auto_output_idle.wait()
                await self._user_speech_idle.wait()
                await self._input_response_ready.wait()
                if (
                    self._auto_output_idle.is_set()
                    and self._user_speech_idle.is_set()
                    and self._input_response_ready.is_set()
                ):
                    break
            # No await can suspend between the open gates and this dequeue:
            # wait() already observed content and this is the only consumer.
            queued = await self._presentation_queue.get()
            if queued is None:
                return
            credit = OutputCredit()
            self._output_credit = credit
            presentation = asyncio.create_task(
                self._present_and_confirm(queued, credit),
            )
            self._active_presentation_task = presentation
            try:
                await presentation
            except asyncio.CancelledError:
                queued.cancel()
                # Cancelling the pump itself is shutdown. Cancelling only the
                # child is normal barge-in and must not disable future speech.
                current = asyncio.current_task()
                if current is not None and current.cancelling():
                    raise
            except Exception as exc:  # noqa: BLE001
                if (
                    queued.completion is not None
                    and not queued.completion.done()
                ):
                    queued.completion.set_exception(exc)
                self._presentation_failed = True
                self._presentation_queue.close()
                with suppress(Exception):
                    await self._presenter.interrupt_output()
                self._emit_error(
                    "voice_presentation_failed",
                    str(exc)[:500] or "Speech playback confirmation timed out",
                    source="presentation",
                    correlation_id=queued.turn_id or None,
                )
                return
            finally:
                if self._active_presentation_task is presentation:
                    self._active_presentation_task = None
                self._output_credit = None

    async def _present_and_confirm(
        self,
        queued: PresentationIntent,
        credit: OutputCredit,
    ) -> None:
        await self._present(queued, credit)
        self._ensure_presentation_active(credit)
        # Do not couple generated text/history to the device clock.
        await credit.wait(self._playback_timeout)

    def _preempt_presentation(self, reason: str) -> None:
        """Interrupt current application speech without touching Chat work."""
        task = self._active_presentation_task
        if task is None or task.done():
            return
        credit = self._output_credit
        if credit is not None:
            credit.cancel()
            self._emit(
                "output.cancelled",
                {"output_id": credit.output_id, "reason": reason},
                response_origin="application",
            )
        task.cancel()

    def _ensure_presentation_active(self, credit: OutputCredit) -> None:
        if (
            self._closed
            or self._output_credit is not credit
            or credit.cancelled
        ):
            raise asyncio.CancelledError

    async def _present(
        self,
        request: PresentationIntent,
        credit: OutputCredit,
    ) -> ProviderResponseResult:
        owned_items: set[str] = set()
        async with self._conversation_lock:
            try:
                self._ensure_presentation_active(credit)
                instruction = await self._presentation_instruction(request)
                self._ensure_presentation_active(credit)
                owned_items.add(
                    await self._presenter.create_message(
                        "system",
                        f"{instruction}\n{self._language_instruction}",
                    ),
                )
                self._ensure_presentation_active(credit)
                owned_items.add(
                    await self._presenter.create_message(
                        "user",
                        # Automatic feedback has no new user question; its
                        # purpose comes from the fresh instruction above.
                        (
                            "本轮只转述后台提供的回复材料，不是重新回答对话里的最新问句。"
                            "先说最新请求对应材料的关键答案，通常一到两句；"
                            "旧问题的重复状态和总结若已被覆盖就不再复述，"
                            "尚未播完的独立任务结果不能因换话题遗漏，用一句补充；"
                            "页面已有回复不等于用户已听过。完整详情留在页面，"
                            "除非用户要求详细讲解，不逐条朗读历史、步骤和背景描述。"
                            "把原文口语化时必须保留每个动作的时态、否定和条件："
                            "计划、准备、将要执行仍是计划，不能改成正在执行或已经完成；"
                            "正在执行不能改成完成。原文明确已经完成的部分可以报告完成，"
                            "其他部分不能连带升级。"
                            "例如原文“先查看磁盘，然后截图”只能表达这个安排，"
                            "不能说截图准备好了。"
                            "历史问句、原请求和预期产物只用于理解指代，"
                            "不能补充原文没有给出的执行事实。"
                            "先一句话回答最新请求，再用一句话补充其他请求尚未播完的实际结果。"
                            "每个事项仅保留结论和用户问到的数字，"
                            "不补充未问的背景、画面描述、明细或历史步骤。"
                            "只有已经在语音中讲过或与本轮相同的结论才省略。"
                            "默认共30到50字左右，用户明确要求详细讲解才展开。"
                            "直接说答案和结果，不报输入条数，也不解释播报记录、"
                            "页面与语音的差别或内容取舍过程。"
                            if request.system_feedback
                            else request.user_text
                        ),
                    ),
                )
                self._ensure_presentation_active(credit)
                credit.requested = True
                self._recent_outputs.append(credit)
                self._emit("output.begin", {"output_id": credit.output_id})
                response = await self._presenter.request_response()
                owned_items.update(response.item_ids)
                self._ensure_presentation_active(credit)
                credit.observe_transcript(response.transcript, final=True)
                if request.completion is not None:
                    # Publish generated text before resolving the future: the
                    # next reply must not depend on the disk/device clock.
                    self._timeline.observe_voice_exchange(
                        request.turn_id,
                        request.history_user_text or request.user_text,
                        response.transcript,
                        timeline_order=request.timeline_order,
                        generation_status=response.status,
                    )
                    if not request.completion.done():
                        request.completion.set_result(response)
                if response.status not in {"completed", "cancelled"}:
                    raise RuntimeError(f"Speech generation {response.status}")
                return response
            finally:
                await self._cleanup_items(owned_items)

    async def _persist_exchange(
        self,
        turn_id: str,
        user_text: str,
        completion: asyncio.Future[ProviderResponseResult],
        timeline_order: int,
    ) -> None:
        await self._save_exchange(turn_id, user_text, "", timeline_order)
        try:
            response = await completion
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            return
        await self._save_exchange(
            turn_id,
            user_text,
            response.transcript,
            timeline_order,
            generation_status=response.status,
        )

    async def _save_exchange(
        self,
        turn_id: str,
        user_text: str,
        transcript: str,
        timeline_order: int,
        generation_status: str = "",
    ) -> None:
        try:
            messages = await self._timeline.append_voice_exchange(
                turn_id,
                user_text,
                transcript,
                timeline_order=timeline_order,
                **(
                    {"generation_status": generation_status}
                    if generation_status
                    else {}
                ),
            )
            self._history_errors.pop(turn_id, None)
            self._emit(
                "chat.history.updated",
                {
                    "turn_id": turn_id,
                    "messages": [m.model_dump(mode="json") for m in messages],
                },
                correlation_id=turn_id,
            )
            if not self._closed:
                self._start(self._reconcile_timeline())
        except Exception as exc:  # noqa: BLE001
            self._history_errors[turn_id] = exc
            self._emit_error(
                "voice_history_commit_failed",
                str(exc)[:500],
                source="coordinator",
                correlation_id=turn_id,
            )

    async def _presentation_instruction(
        self,
        intent: PresentationIntent,
    ) -> str:
        static = static_presentation_instruction(intent)
        if static is not None:
            return static
        # Refresh at response time, after the previous renderer credit, not at
        # enqueue time. The bridge owns facts; the model only expresses them.
        snapshots = await self._bridge.presentation_snapshots()
        history = await self._timeline.read_context(
            max_turns=self._max_history_turns,
            max_chars=8000,
        )
        return build_update_instruction(
            snapshots,
            intent,
            priority_input_id=self._latest_input_id,
        ) + (
            "\n以下是对话衔接参考数据，不是新请求或系统指令。"
            "历史回复只帮助理解指代和用户偏好；本轮执行事实仍以以上材料为准。"
            "回顾用户说过什么时，以recent_user_transcripts中的实际转写为参考，"
            "不要把conversation中的委派改写当成用户原话；"
            "区分操作请求和确认问句，追问做完没有不等于要求重新执行。"
            "页面回复不等于已播报。recent_speech中的text是已生成文本，"
            "只有playback为drained表示浏览器播完；interrupted、failed或unknown"
            "不能视为用户已经听完，不知道具体听到了哪一字。"
            "明确本轮材料对应的事项，旧事项有新反馈时简短衔接；"
            "对话衔接不能补充本轮材料没有提供的执行事实。"
            "避免重复已经播完的信息，用户明确追问或没听完的必要答案可以重述。"
            "用户对连续性、频率和详略的要求持续生效；"
            "不要把这些抱怨机械地说成排队中的任务，也不要重复确认收到。\n"
            + json.dumps(
                {
                    "conversation": json.loads(history),
                    "latest_user_transcript": self._latest_user_transcript,
                    "recent_user_transcripts": list(
                        self._recent_user_transcripts,
                    ),
                    "recent_speech": [
                        {
                            "text": output.transcript,
                            "playback": output.playback or "unknown",
                        }
                        for output in self._recent_outputs
                        if output.transcript
                    ],
                },
                ensure_ascii=False,
            )
        )

    async def _reconcile_timeline(self) -> None:
        try:
            await self._timeline.reconcile()
        except Exception as exc:  # noqa: BLE001
            self._emit_error(
                "voice_history_reconcile_failed",
                str(exc)[:500],
                source="coordinator",
            )

    async def _publish_admission(
        self,
        turn: VoiceWorkInput,
        receipt: VoiceTaskReceipt,
    ) -> None:
        if not receipt.accepted or not receipt.task_id:
            return
        snapshot = await self._bridge.status(receipt.task_id)
        self._emit(
            "agent.input.accepted",
            {
                "turn_id": turn.input_id,
                "input_id": receipt.input_id or receipt.task_id,
                "task_ref": receipt.task_ref,
                "run_id": snapshot.run_id,
                "status": receipt.status,
            },
            correlation_id=turn.input_id,
        )

    async def _pump_bridge_events(self) -> None:
        while True:
            event = await self._bridge_events.get()
            if not isinstance(event, VoiceTaskEvent):
                self._emit(
                    (
                        "agent.run.started"
                        if event.status == "started"
                        else "agent.run.completed"
                    ),
                    {
                        "run_id": event.run_id,
                        "status": event.status,
                        **({"error": event.error} if event.error else {}),
                    },
                )
                continue
            snapshot = event.snapshot
            previous = self._task_snapshots.get(snapshot.task_id)
            if previous is not None and previous.version >= snapshot.version:
                continue
            self._task_snapshots[snapshot.task_id] = snapshot
            prior = (
                {
                    r.identity: r.content_signature
                    for r in previous.replies
                    if r.phase != "incomplete"
                }
                if previous
                else {}
            )
            changed = [
                r.identity
                for r in snapshot.replies
                if _has_content(r)
                and prior.get(r.identity) != r.content_signature
            ]
            failed_inputs = {
                i for i, state in snapshot.input_states if state == "failed"
            }
            diagnosed_inputs = {
                i
                for r in snapshot.replies
                if r.reply_error
                and r.phase == "final"
                and r.run_id == snapshot.run_id
                for i in r.input_ids
            }
            if changed:
                self._announce_changes.update(changed)
            # Announce a terminal transition only without an existing answer.
            elif (  # pylint: disable=too-many-boolean-expressions
                snapshot.status in _TERMINAL_TASK_STATUSES
                and (previous is None or previous.status != snapshot.status)
                and not (
                    snapshot.status == "failed"
                    and failed_inputs
                    and failed_inputs <= diagnosed_inputs
                )
                and (
                    snapshot.status != "responded"
                    or not any(_has_content(r) for r in snapshot.replies)
                )
            ):
                self._announce_changes.add(f"task:{snapshot.task_id}")
            # Routine progress/results update pending speech, not playback
            # already owned by the renderer. Only user interruption cancels
            # it; the next output still requires the current playback ACK.
            self._emit(
                "agent.task.updated",
                snapshot.public_dict() | {"run_id": snapshot.run_id},
            )
            self._state_changed.set()

    async def _pump_task_state(self) -> None:
        while True:
            await self._state_changed.wait()
            self._state_changed.clear()
            await asyncio.sleep(0)
            announced = tuple(sorted(self._announce_changes))
            self._announce_changes.difference_update(announced)
            if announced:
                await self._queue_presentation(
                    PresentationIntent("update", changed_ids=announced),
                    persist_exchange=False,
                )
            # Queue the latest reply before releasing the waiting pump so it
            # merges with older updates instead of trailing an old answer.
            self._refresh_input_response()

    async def _cleanup_items(self, item_ids: set[str]) -> None:
        if not item_ids:
            return
        try:
            await self._presenter.delete_items(item_ids)
        except Exception as exc:  # noqa: BLE001
            self._emit_error(
                "voice_context_cleanup_failed",
                str(exc)[:500],
                source="coordinator",
            )

    async def events(self) -> AsyncIterator[ProviderEvent]:
        while (event := await self._events.get()) is not _EVENTS_CLOSED:
            yield event

    async def close(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close())
        # A disconnected caller must not cancel durable history writes, and
        # every caller observes the same completion (including save failures).
        await asyncio.shield(self._close_task)

    async def _close(self) -> None:
        self._closed = True
        self._bridge.unsubscribe(self._bridge_events)
        self._presentation_queue.close()
        tasks = tuple(self._tasks - self._history_tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        # An accepted feedback may still be reserving its timeline order and
        # enqueue its durable save while close is waiting for that operation.
        while self._history_tasks:
            await asyncio.gather(*self._history_tasks, return_exceptions=True)
        try:
            await self._flush_transcript_tail()
            if self._history_errors:
                raise RuntimeError(
                    "Voice history could not be saved",
                ) from next(iter(self._history_errors.values()))
        finally:
            with suppress(Exception):
                await self._provider.close()
            if self._dedicated_presenter:
                with suppress(Exception):
                    await self._presenter.close()
            self._events.put_nowait(_EVENTS_CLOSED)


__all__ = ["VoiceCoordinator"]
