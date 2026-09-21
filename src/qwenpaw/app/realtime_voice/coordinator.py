"""Application control and speech presentation for one Voice session."""

from __future__ import annotations

import asyncio
import hashlib
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
from ..chats.timeline import ChatTimelineJournal
from .contracts import (
    VoiceRunEvent,
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


class VoiceCoordinator:
    """Keep application control durable while speech remains interruptible."""

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
    ) -> None:
        self._provider = provider
        self._presenter = presentation_provider or provider
        self._language_instruction = build_language_instruction(language)
        self._session_config = build_session_config(language)
        self._presentation_session_config = build_presentation_session_config(language)
        self._bridge = bridge
        self._handoff = VoiceHandoffController(provider, bridge)
        self._timeline = timeline
        self._events: asyncio.Queue[ProviderEvent | object] = asyncio.Queue()
        self._presentation_queue = PresentationQueue(presentation_capacity)
        self._playback_timeout = playback_timeout_seconds
        self._output_credit: OutputCredit | None = None
        self._auto_response_credit: OutputCredit | None = None
        self._auto_credits: dict[str, OutputCredit] = {}
        self._auto_begun: set[str] = set()
        self._auto_output_idle = asyncio.Event()
        self._auto_output_idle.set()
        self._seen_responses: set[str] = set()
        self._presentation_failed = False
        self._active_presentation_task: asyncio.Task[None] | None = None
        self._active_presentation_intent: PresentationIntent | None = None
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
        self._chat_owned_sources: set[str] = set()
        self._chat_owned_responses: dict[str, str] = {}
        self._chat_mode_active = False
        self._closed = False

    async def start(self) -> None:
        await self._provider.connect(self._session_config)
        if self._presenter is not self._provider:
            await self._presenter.connect(self._presentation_session_config)
        snapshots = await self._bridge.presentation_snapshots()
        self._chat_mode_active = bool(snapshots)
        for snapshot in snapshots:
            self._task_snapshots[snapshot.task_id] = snapshot
        self._start(self._pump_provider())
        if self._presenter is not self._provider:
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

    async def send_audio(self, pcm16: bytes) -> None:
        await self._provider.send_audio(pcm16)

    async def interrupt(self) -> None:
        await self._provider.interrupt_output()
        if self._presenter is not self._provider:
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
            await self._events.put(
                ProviderEvent(
                    "agent.run.started",
                    uuid4().hex,
                    {"run_id": run_id, "status": "observing"},
                )
            )

    async def _pump_provider(self) -> None:
        try:
            async for event in self._provider.events():
                if (
                    event.kind
                    in {
                        "speech.started",
                        "speech.stopped",
                        "input_transcript.partial",
                        "input_transcript.final",
                        "input_transcript.failed",
                    }
                    and not event.correlation_id
                ):
                    await self._emit_error(
                        "missing_turn_identity",
                        "The speech provider did not supply a stable input item "
                        "identifier.",
                        source="coordinator",
                    )
                    continue
                if event.kind == "input_transcript.final":
                    source_id = str(event.correlation_id or "")
                    self._input_transcripts[source_id] = str(
                        event.data.get("text") or ""
                    ).strip()
                    if self._chat_mode_active:
                        self._chat_owned_sources.add(source_id)
                    self._start(self._persist_auto_exchange(source_id))
                elif event.kind == "input_transcript.failed":
                    self._input_transcripts[str(event.correlation_id or "")] = ""
                if event.kind == "speech.started":
                    if self._chat_mode_active:
                        self._chat_owned_sources.add(str(event.correlation_id or ""))
                    self._preempt_presentation("barge_in")
                if event.kind == "tool.call":
                    self._start(self._handle_tool_call(event))
                    continue
                if event.kind in _RESPONSE_EVENTS:
                    await self._handle_response_event(event)
                    continue
                await self._events.put(event)
        finally:
            await self._events.put(_EVENTS_CLOSED)

    async def _pump_presenter(self) -> None:
        async for event in self._presenter.events():
            if event.kind in _RESPONSE_EVENTS:
                await self._handle_response_event(event)

    async def _handle_tool_call(self, event: ProviderEvent) -> None:
        try:
            result = await self._handoff.handle(event)
        except VoiceHandoffError as exc:
            call_id = str(event.data.get("call_id") or event.correlation_id or "")
            if call_id:
                with suppress(Exception):
                    await self._provider.complete_tool_call(
                        call_id,
                        {"accepted": False, "message": str(exc)},
                    )
            await self._emit_error(
                "invalid_voice_handoff",
                str(exc),
                source="coordinator",
                correlation_id=call_id or None,
            )
            return
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            await self._emit_error(
                "voice_handoff_failed",
                str(exc)[:500] or "The voice request could not be admitted.",
                source="coordinator",
                correlation_id=event.correlation_id,
            )
            return

        if result.replayed:
            return
        work, receipt = result.work, result.receipt
        if receipt.accepted:
            self._chat_mode_active = True
        await self._publish_handoff(work, receipt)

    async def _publish_handoff(
        self,
        work: VoiceWorkInput,
        receipt: VoiceTaskReceipt,
    ) -> None:
        await self._events.put(
            ProviderEvent(
                "input_turn.committed" if receipt.accepted else "input_turn.rejected",
                uuid4().hex,
                {
                    "turn_id": work.input_id,
                    "source_count": 1,
                    "origin": "native",
                    "action": work.action,
                    **({"message": receipt.message} if receipt.message else {}),
                },
                correlation_id=work.input_id,
            )
        )
        await self._publish_admission(work, receipt)
        await self._queue_admission(work, receipt)

    async def _handle_response_event(self, event: ProviderEvent) -> None:
        if event.response_origin == "provider_auto":
            await self._handle_auto_response_event(event)
            return
        if event.response_origin != "application":
            return
        credit = self._output_credit
        response_id = event.correlation_id or ""
        if (
            event.kind == "response.started"
            and credit is not None
            and not credit.provider_id
            and response_id
            and response_id not in self._seen_responses
        ):
            credit.provider_id = response_id
            self._seen_responses.add(response_id)
        if credit is None or credit.sealed or response_id != credit.provider_id:
            return
        event = replace(
            event,
            data={**event.data, "output_id": credit.output_id},
        )
        if event.kind == "response.finished":
            await self._events.put(event)
            credit.seal()
            await self._events.put(
                ProviderEvent(
                    "output.sealed",
                    uuid4().hex,
                    {"output_id": credit.output_id},
                )
            )
            return
        await self._events.put(event)

    async def _handle_auto_response_event(self, event: ProviderEvent) -> None:
        response_id = str(event.correlation_id or "")
        source_id = str(event.data.get("input_item_id") or "")
        if event.kind == "response.started" and source_id:
            self._chat_owned_responses[response_id] = source_id
        owned_source = self._chat_owned_responses.get(response_id, source_id)
        if owned_source in self._chat_owned_sources:
            if event.kind == "response.finished":
                self._auto_responses[owned_source] = {
                    "response_id": response_id,
                    "status": str(event.data.get("status") or "completed"),
                    "transcript": str(event.data.get("transcript") or "").strip(),
                    "had_tool_call": bool(event.data.get("had_tool_call")),
                }
                self._chat_owned_responses.pop(response_id, None)
                self._start(self._persist_auto_exchange(owned_source))
            return
        if event.kind == "response.started":
            if not response_id or response_id in self._seen_responses:
                return
            self._seen_responses.add(response_id)
            credit = OutputCredit(provider_id=response_id)
            self._auto_response_credit = credit
            self._auto_credits[credit.output_id] = credit
        credit = self._auto_response_credit
        if credit is None or credit.provider_id != response_id or credit.sealed:
            return
        if event.kind == "output.started" and credit.output_id not in self._auto_begun:
            self._auto_begun.add(credit.output_id)
            self._auto_output_idle.clear()
            await self._events.put(
                ProviderEvent(
                    "output.begin",
                    uuid4().hex,
                    {"output_id": credit.output_id},
                )
            )
        event = replace(
            event,
            data={**event.data, "output_id": credit.output_id},
        )
        if event.kind != "response.finished":
            await self._events.put(event)
            return

        source_id = str(event.data.get("input_item_id") or "")
        if source_id:
            self._auto_responses[source_id] = {
                "response_id": response_id,
                "status": str(event.data.get("status") or "completed"),
                "transcript": str(event.data.get("transcript") or "").strip(),
                "had_tool_call": bool(event.data.get("had_tool_call")),
            }
            self._start(self._persist_auto_exchange(source_id))
        await self._events.put(event)
        credit.seal()
        began = credit.output_id in self._auto_begun
        if began:
            await self._events.put(
                ProviderEvent(
                    "output.sealed",
                    uuid4().hex,
                    {"output_id": credit.output_id},
                )
            )
            self._start(self._settle_auto_credit(credit))
        else:
            self._auto_credits.pop(credit.output_id, None)
        self._auto_response_credit = None
        if not self._auto_credits:
            self._auto_output_idle.set()

    async def _settle_auto_credit(self, credit: OutputCredit) -> None:
        try:
            await credit.wait(self._playback_timeout)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            await self._emit_error(
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
        self._persisted_auto_sources.add(source_id)
        response = self._auto_responses.pop(source_id)
        user_text = self._input_transcripts.pop(source_id).strip()
        if source_id in self._chat_owned_sources:
            self._chat_owned_sources.discard(source_id)
            if response["had_tool_call"] or not user_text:
                return
            try:
                result = await self._handoff.handle_transcript(source_id, user_text)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                await self._emit_error(
                    "voice_handoff_failed",
                    str(exc)[:500] or "The voice request could not be admitted.",
                    source="coordinator",
                    correlation_id=source_id,
                )
                return
            if result.receipt.accepted:
                self._chat_mode_active = True
            await self._publish_handoff(result.work, result.receipt)
            return
        if response["had_tool_call"] or not user_text:
            return
        turn_id = (
            "voice_dialogue_" + hashlib.sha256(source_id.encode()).hexdigest()[:32]
        )
        timeline_order = await self._timeline.reserve_order()
        assistant_text = str(response["transcript"] or "").strip()
        status = str(response["status"] or "completed")
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

    async def _queue_admission(
        self,
        turn: VoiceWorkInput,
        receipt: VoiceTaskReceipt,
    ) -> None:
        await self._queue_presentation(
            PresentationIntent(
                "admission" if receipt.accepted else "rejected",
                turn_id=turn.input_id,
                admission_turn_ids=(turn.input_id,) if receipt.accepted else (),
                user_text=(
                    "请告知用户本轮请求接收结果。" if not receipt.accepted else ""
                ),
                task_ref=receipt.task_ref,
            ),
            persist_exchange=not receipt.accepted,
            # Accepted text already belongs to the ordinary Chat task. Keep it
            # out of speech rendering so receipt wording cannot imply results.
            history_user_text="" if receipt.accepted else turn.request_text,
        )

    async def _queue_presentation(
        self,
        intent: PresentationIntent,
        *,
        persist_exchange: bool,
        history_user_text: str = "",
    ) -> None:
        completion: asyncio.Future[ProviderResponseResult] | None = None
        timeline_order = 0
        if persist_exchange:
            timeline_order = await self._timeline.reserve_order()
            # User text survives generation failure, interruption and overload.
            self._timeline.observe_voice_exchange(
                intent.turn_id,
                history_user_text or intent.user_text,
                "",
                timeline_order=timeline_order,
            )
            completion = asyncio.get_running_loop().create_future()
            history_task = self._start(
                self._persist_exchange(
                    intent.turn_id,
                    history_user_text or intent.user_text,
                    completion,
                    timeline_order,
                )
            )
            self._history_tasks.add(history_task)
            history_task.add_done_callback(self._history_tasks.discard)
        queued = replace(
            intent,
            completion=completion,
            timeline_order=timeline_order,
            history_user_text=history_user_text or intent.user_text,
        )
        if not self._presentation_queue.put(queued):
            await self._events.put(
                ProviderEvent(
                    "presentation.rejected",
                    uuid4().hex,
                    {
                        "turn_id": intent.turn_id,
                        "code": "voice_output_unavailable"
                        if self._presentation_failed
                        else "voice_output_busy",
                        "task_admitted": intent.system_feedback,
                    },
                )
            )

    async def _pump_presentation(self) -> None:
        while True:
            queued = await self._presentation_queue.get()
            if queued is None:
                return
            await self._auto_output_idle.wait()
            credit = OutputCredit()
            self._output_credit = credit
            self._active_presentation_intent = queued
            presentation = asyncio.create_task(
                self._present_and_confirm(queued, credit)
            )
            self._active_presentation_task = presentation
            try:
                await presentation
            except asyncio.CancelledError:
                if queued.completion is not None and not queued.completion.done():
                    queued.completion.cancel()
                # Cancelling the pump itself is shutdown.  Cancelling only the
                # child is normal barge-in/supersession and must not disable
                # future application speech.
                current = asyncio.current_task()
                if current is not None and current.cancelling():
                    raise
                continue
            except Exception as exc:  # noqa: BLE001
                if queued.completion is not None and not queued.completion.done():
                    queued.completion.set_exception(exc)
                self._presentation_failed = True
                self._presentation_queue.close()
                with suppress(Exception):
                    await self._presenter.interrupt_output()
                await self._emit_error(
                    "voice_presentation_failed",
                    str(exc)[:500] or "Speech playback confirmation timed out",
                    source="presentation",
                    correlation_id=queued.turn_id or None,
                )
                return
            finally:
                if self._active_presentation_task is presentation:
                    self._active_presentation_task = None
                    self._active_presentation_intent = None
                self._output_credit = None

    async def _present_and_confirm(
        self,
        queued: PresentationIntent,
        credit: OutputCredit,
    ) -> None:
        await self._present(queued)
        # Do not couple generated text/history to the device clock.
        await credit.wait(self._playback_timeout)

    def _preempt_presentation(self, reason: str) -> None:
        """Cancel replaceable application speech without touching Chat work."""
        task = self._active_presentation_task
        if task is None or task.done():
            return
        credit = self._output_credit
        if credit is not None:
            self._events.put_nowait(
                ProviderEvent(
                    "output.cancelled",
                    uuid4().hex,
                    {"output_id": credit.output_id, "reason": reason},
                    response_origin="application",
                )
            )
            credit.acknowledge(credit.output_id, "interrupted")
        task.cancel()

    async def _present(self, request: PresentationIntent) -> ProviderResponseResult:
        owned_items: set[str] = set()
        async with self._conversation_lock:
            try:
                instruction = (
                    await self._presentation_instruction(request)
                    + "\n"
                    + self._language_instruction
                )
                owned_items.add(
                    await self._presenter.create_message(
                        "system",
                        instruction,
                    )
                )
                owned_items.add(
                    await self._presenter.create_message(
                        "user",
                        # Automatic feedback has no new user question. Its
                        # purpose comes from the fresh instruction above,
                        # not a stale status question frozen at enqueue time.
                        "请按本轮反馈目的，用自然口语向用户反馈以上信息。"
                        if request.system_feedback
                        else request.user_text,
                    )
                )
                credit = self._output_credit
                if credit is not None:
                    await self._events.put(
                        ProviderEvent(
                            "output.begin",
                            uuid4().hex,
                            {"output_id": credit.output_id},
                        )
                    )
                response = await self._presenter.request_response()
                owned_items.update(response.item_ids)
                if request.completion is not None:
                    # Publish generated source text before resolving the
                    # future:
                    # the next reply must not depend on the disk/device clock.
                    self._timeline.observe_voice_exchange(
                        request.turn_id,
                        request.history_user_text or request.user_text,
                        response.transcript,
                        timeline_order=request.timeline_order,
                        generation_status=response.status,
                    )
                if request.completion is not None and not request.completion.done():
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
        except asyncio.CancelledError:
            return
        except Exception:  # noqa: BLE001
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
            await self._events.put(
                ProviderEvent(
                    "chat.history.updated",
                    uuid4().hex,
                    {
                        "turn_id": turn_id,
                        "messages": [
                            message.model_dump(mode="json") for message in messages
                        ],
                    },
                    correlation_id=turn_id,
                )
            )
            if not self._closed:
                self._start(self._reconcile_timeline())
        except Exception as exc:  # noqa: BLE001
            await self._emit_error(
                "voice_history_commit_failed",
                str(exc)[:500],
                source="coordinator",
                correlation_id=turn_id,
            )

    async def _presentation_instruction(self, intent: PresentationIntent) -> str:
        static = static_presentation_instruction(intent)
        if static is not None:
            return static
        # Refresh at response time, after the previous renderer credit, not at
        # enqueue time. The bridge owns facts; the model only expresses them.
        snapshots = await self._bridge.presentation_snapshots()
        return build_update_instruction(snapshots, intent)

    async def _reconcile_timeline(self) -> None:
        try:
            await self._timeline.reconcile()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            await self._emit_error(
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
        await self._events.put(
            ProviderEvent(
                "agent.input.accepted",
                uuid4().hex,
                {
                    "turn_id": turn.input_id,
                    "input_id": receipt.input_id or receipt.task_id,
                    "task_ref": receipt.task_ref,
                    "run_id": snapshot.run_id,
                    "status": receipt.status,
                },
                correlation_id=turn.input_id,
            )
        )

    async def _pump_bridge_events(self) -> None:
        while True:
            event = await self._bridge_events.get()
            if isinstance(event, VoiceTaskEvent):
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
                    if r.phase != "incomplete"
                    and (r.text or r.media_refs)
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
                elif (
                    snapshot.status in _TERMINAL_TASK_STATUSES
                    and (previous is None or previous.status != snapshot.status)
                    and not (
                        snapshot.status == "failed"
                        and failed_inputs
                        and failed_inputs <= diagnosed_inputs
                    )
                    and (
                        snapshot.status != "responded"
                        or not any(
                            r.phase != "incomplete" and (r.text or r.media_refs)
                            for r in snapshot.replies
                        )
                    )
                ):
                    self._announce_changes.add(f"task:{snapshot.task_id}")
                if changed or f"task:{snapshot.task_id}" in self._announce_changes:
                    self._preempt_presentation("superseded")
                await self._events.put(
                    ProviderEvent(
                        "agent.task.updated",
                        uuid4().hex,
                        snapshot.public_dict() | {"run_id": snapshot.run_id},
                    )
                )
                self._state_changed.set()
            elif isinstance(event, VoiceRunEvent):
                await self._events.put(
                    ProviderEvent(
                        "agent.run.started"
                        if event.status == "started"
                        else "agent.run.completed",
                        uuid4().hex,
                        {
                            "run_id": event.run_id,
                            "status": event.status,
                            **({"error": event.error} if event.error else {}),
                        },
                    )
                )

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

    async def _cleanup_items(self, item_ids: set[str]) -> None:
        if not item_ids:
            return
        try:
            await self._presenter.delete_items(item_ids)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            await self._emit_error(
                "voice_context_cleanup_failed",
                str(exc)[:500],
                source="coordinator",
            )

    async def _emit_error(
        self,
        code: str,
        message: str,
        *,
        source: str,
        correlation_id: str | None = None,
    ) -> None:
        await self._events.put(
            ProviderEvent(
                "error",
                uuid4().hex,
                {
                    "code": code,
                    "message": message,
                    "recoverable": True,
                    "source": source,
                },
                correlation_id=correlation_id,
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
        self._bridge.unsubscribe(self._bridge_events)
        self._presentation_queue.close()
        tasks = tuple(self._tasks - self._history_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self._history_tasks:
            await asyncio.gather(*tuple(self._history_tasks), return_exceptions=True)
        with suppress(Exception):
            await self._provider.close()
        if self._presenter is not self._provider:
            with suppress(Exception):
                await self._presenter.close()
        await self._events.put(_EVENTS_CLOSED)


__all__ = ["VoiceCoordinator"]
