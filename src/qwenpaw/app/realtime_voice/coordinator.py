"""Application control and speech presentation for one Voice session."""

from __future__ import annotations

import asyncio
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
    ClarifyVoiceAction,
    ConverseVoiceAction,
    HandoffVoiceAction,
    VoiceAdmissionMode,
    VoiceRunEvent,
    VoiceTaskEvent,
    VoiceTaskReceipt,
    VoiceTaskSnapshot,
)
from .task_bridge import VoiceAdmissionHandle, VoiceTaskBridge
from .presentation import OutputCredit, PresentationIntent, PresentationQueue
from .prompts import (
    build_language_instruction,
    build_session_config,
    build_update_instruction,
    static_presentation_instruction,
)
from .turn_commit import (
    CommittedSpokenTurn,
    PendingSpokenTurn,
    SpokenTurnCommitter,
)

_EVENTS_CLOSED = object()
_APPLICATION_RESPONSE_EVENTS = {
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
        committer: SpokenTurnCommitter,
        timeline: ChatTimelineJournal,
        *,
        language: str = "zh",
        admission_mode: VoiceAdmissionMode = "queue",
        presentation_capacity: int = 32,
        playback_timeout_seconds: float = 90,
        max_history_turns: int = 20,
        context_max_chars: int = 1800,
    ) -> None:
        self._provider = provider
        self._language_instruction = build_language_instruction(language)
        self._session_config = build_session_config(language)
        self._bridge = bridge
        self._committer = committer
        committer.on_commit = lambda turn: bridge.observe_input(
            turn.turn_id,
            turn.text,
            turn.action,
        )
        self._timeline = timeline
        self._admission_mode = admission_mode
        self._events: asyncio.Queue[ProviderEvent | object] = asyncio.Queue()
        self._presentation_queue = PresentationQueue(presentation_capacity)
        self._playback_timeout = playback_timeout_seconds
        self._max_history_turns = max_history_turns
        self._context_max_chars = context_max_chars
        self._output_credit: OutputCredit | None = None
        self._seen_responses: set[str] = set()
        self._presentation_failed = False
        self._history_tasks: set[asyncio.Task[Any]] = set()
        self._bridge_events = bridge.subscribe()
        self._tasks: set[asyncio.Task[Any]] = set()
        self._conversation_lock = asyncio.Lock()
        self._state_changed = asyncio.Event()
        self._task_snapshots: dict[str, VoiceTaskSnapshot] = {}
        self._announce_changes: set[str] = set()
        self._committer_task: asyncio.Task[Any] | None = None
        self._closed = False

    async def start(self) -> None:
        await self._provider.connect(self._session_config)
        for snapshot in await self._bridge.routing_snapshots():
            self._task_snapshots[snapshot.task_id] = snapshot
        self._start(self._pump_provider())
        self._committer_task = self._start(self._pump_committer())
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

    def playback_feedback(self, output_id: str, status: str) -> None:
        """The relay has already checked the connection generation."""
        if self._output_credit is not None:
            self._output_credit.acknowledge(output_id, status)

    async def commit_pending(self) -> None:
        """Explicitly route retained speech without permitting WAIT."""
        await self._committer.commit_pending("manual")

    async def set_admission_mode(self, mode: VoiceAdmissionMode) -> None:
        if mode not in {"queue", "steer"}:
            raise ValueError("unknown voice admission mode")
        self._admission_mode = mode

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
                    await self._committer.input_failed("")
                    await self._emit_error(
                        "missing_turn_identity",
                        "The speech provider did not supply a stable input "
                        "item identifier. The request was not submitted.",
                        source="coordinator",
                    )
                    continue
                if event.kind == "speech.started":
                    await self._committer.speech_started(event.correlation_id)
                elif event.kind == "speech.stopped":
                    await self._committer.speech_stopped(event.correlation_id)
                elif event.kind == "input_transcript.partial":
                    await self._committer.speech_started(event.correlation_id)
                elif event.kind == "input_transcript.failed":
                    await self._committer.input_failed(event.correlation_id)
                    await self._emit_error(
                        "voice_transcription_failed",
                        "一段语音识别失败，未自动提交。请检查已识别的内容后手动提交，" "或重新开始语音会话说明完整请求。",
                        source="coordinator",
                    )
                    continue
                if event.kind == "input_transcript.final":
                    await self._handle_source_segment(event)
                    continue
                if event.kind == "input_turn.boundary":
                    await self._committer.commit_pending("native")
                    continue
                if (
                    event.kind in _APPLICATION_RESPONSE_EVENTS
                    and event.response_origin != "application"
                ):
                    continue
                if event.kind in _APPLICATION_RESPONSE_EVENTS:
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
                    if (
                        credit is None
                        or credit.sealed
                        or response_id != credit.provider_id
                    ):
                        continue
                    # Stale events must never acquire a new app output.
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
                        continue
                await self._events.put(event)
        finally:
            await self._events.put(_EVENTS_CLOSED)

    async def _handle_source_segment(self, event: ProviderEvent) -> None:
        text = str(event.data.get("text") or "").strip()
        source_id = str(event.correlation_id or "").strip()
        await self._committer.add_segment(source_id, text)

    async def _pump_committer(self) -> None:
        async for event in self._committer.events():
            if isinstance(event, PendingSpokenTurn):
                await self._events.put(
                    ProviderEvent(
                        "input_turn.pending",
                        uuid4().hex,
                        {
                            "text": event.text,
                            "source_count": len(event.source_ids),
                            "state": event.state,
                            "manual_commit_available": True,
                            **({"error": event.error} if event.error else {}),
                        },
                    )
                )
                continue
            if isinstance(event, CommittedSpokenTurn):
                admission: VoiceAdmissionHandle | None = None
                if isinstance(
                    event.action,
                    HandoffVoiceAction,
                ):
                    try:
                        admission = await self._bridge.enqueue_action(
                            event.action,
                            event.text,
                            idempotency_key=event.turn_id,
                            admission_mode=self._admission_mode,
                            conversation_context=event.conversation_context,
                        )
                    except Exception as exc:  # noqa: BLE001
                        await self._reject_task_action(event, exc)
                        continue
                await self._events.put(
                    ProviderEvent(
                        "input_turn.committed",
                        uuid4().hex,
                        {
                            "turn_id": event.turn_id,
                            "source_count": len(event.source_ids),
                            "origin": event.origin,
                            "action": event.action.public_dict(),
                        },
                        correlation_id=event.turn_id,
                    )
                )
                if admission is not None:
                    self._start(self._complete_admission(event, admission))
                else:
                    await self._apply_presentation_action(event)

    async def _complete_admission(
        self,
        turn: CommittedSpokenTurn,
        admission: VoiceAdmissionHandle,
    ) -> None:
        receipt = await admission.wait()
        await self._publish_admission(turn, receipt)
        await self._queue_admission(turn, receipt)

    async def _reject_task_action(
        self,
        turn: CommittedSpokenTurn,
        error: Exception,
    ) -> None:
        message = str(error)[:500] or "The task could not be accepted."
        await self._events.put(
            ProviderEvent(
                "input_turn.rejected",
                uuid4().hex,
                {
                    "turn_id": turn.turn_id,
                    "action": turn.action.public_dict(),
                    "message": message,
                },
                correlation_id=turn.turn_id,
            ),
        )
        await self._queue_admission(
            turn,
            VoiceTaskReceipt(
                task_id="",
                task_ref="",
                accepted=False,
                status="failed",
                message=message,
            ),
        )

    async def _apply_presentation_action(
        self,
        turn: CommittedSpokenTurn,
    ) -> None:
        action = turn.action
        if isinstance(action, ClarifyVoiceAction):
            await self._queue_turn_presentation(
                turn,
                PresentationIntent(
                    "clarify", missing_information=action.missing_information
                ),
            )
            return
        if isinstance(action, ConverseVoiceAction):
            await self._queue_turn_presentation(
                turn,
                PresentationIntent("converse"),
            )
            return
        raise TypeError(f"unsupported voice action: {type(action).__name__}")

    async def _queue_admission(
        self,
        turn: CommittedSpokenTurn,
        receipt: VoiceTaskReceipt,
    ) -> None:
        await self._queue_presentation(
            PresentationIntent(
                "admission" if receipt.accepted else "rejected",
                turn_id=turn.turn_id,
                admission_turn_ids=(turn.turn_id,) if receipt.accepted else (),
                user_text="请告知用户本轮请求接收结果。" if not receipt.accepted else "",
                task_ref=receipt.task_ref,
            ),
            persist_exchange=not receipt.accepted,
            # Accepted text already belongs to the ordinary Chat task. Keep it
            # out of speech rendering so receipt wording cannot imply results.
            history_user_text="" if receipt.accepted else turn.text,
        )

    async def _queue_turn_presentation(
        self,
        turn: CommittedSpokenTurn,
        intent: PresentationIntent,
    ) -> None:
        await self._queue_presentation(
            replace(intent, turn_id=turn.turn_id, user_text=turn.text),
            persist_exchange=True,
            history_user_text=turn.text,
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
            credit = OutputCredit()
            self._output_credit = credit
            try:
                await self._events.put(
                    ProviderEvent(
                        "output.begin",
                        uuid4().hex,
                        {"output_id": credit.output_id},
                    )
                )
                await self._present(queued)
                # Do not couple generated text/history to the device clock.
                await credit.wait(self._playback_timeout)
            except asyncio.CancelledError:
                if (
                    queued.completion is not None
                    and not queued.completion.done()
                ):
                    queued.completion.cancel()
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
                    await self._provider.interrupt_output()
                await self._emit_error(
                    "voice_presentation_failed",
                    str(exc)[:500] or "Speech playback confirmation timed out",
                    source="presentation",
                    correlation_id=queued.turn_id or None,
                )
                return
            finally:
                self._output_credit = None

    async def _present(
        self, request: PresentationIntent
    ) -> ProviderResponseResult:
        owned_items: set[str] = set()
        async with self._conversation_lock:
            try:
                instruction = (
                    await self._presentation_instruction(request)
                    + "\n"
                    + self._language_instruction
                )
                history = ""
                owned_items.add(
                    await self._provider.create_message(
                        "system",
                        instruction,
                    )
                )
                if request.kind == "converse":
                    history = await self._timeline.read_context(
                        turn_id=request.turn_id,
                        order=request.timeline_order,
                        max_turns=self._max_history_turns,
                        max_chars=self._context_max_chars,
                    )
                if history:
                    owned_items.add(
                        await self._provider.create_message("user", history)
                    )
                owned_items.add(
                    await self._provider.create_message(
                        "user",
                        # Automatic feedback has no new user question. Its
                        # purpose comes from the fresh instruction above,
                        # not a stale status question frozen at enqueue time.
                        "请按本轮反馈目的，用自然口语向用户反馈以上信息。"
                        if request.system_feedback
                        else request.user_text,
                    )
                )
                response = await self._provider.request_response()
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
                if (
                    request.completion is not None
                    and not request.completion.done()
                ):
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
                            message.model_dump(mode="json")
                            for message in messages
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

    async def _presentation_instruction(
        self, intent: PresentationIntent
    ) -> str:
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
        turn: CommittedSpokenTurn,
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
                    "turn_id": turn.turn_id,
                    "input_id": receipt.task_id,
                    "task_ref": receipt.task_ref,
                    "run_id": snapshot.run_id,
                    "status": receipt.status,
                },
                correlation_id=turn.turn_id,
            )
        )

    async def _pump_bridge_events(self) -> None:
        while True:
            event = await self._bridge_events.get()
            if isinstance(event, VoiceTaskEvent):
                snapshot = event.snapshot
                previous = self._task_snapshots.get(snapshot.task_id)
                if (
                    previous is not None
                    and previous.version >= snapshot.version
                ):
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
                    i
                    for i, state in snapshot.input_states
                    if state == "failed"
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
                    and (
                        previous is None or previous.status != snapshot.status
                    )
                    and not (
                        snapshot.status == "failed"
                        and failed_inputs
                        and failed_inputs <= diagnosed_inputs
                    )
                    and (
                        snapshot.status != "responded"
                        or not any(
                            r.phase != "incomplete"
                            and (r.text or r.media_refs)
                            for r in snapshot.replies
                        )
                    )
                ):
                    self._announce_changes.add(f"task:{snapshot.task_id}")
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
            await self._provider.delete_items(item_ids)
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
        await self._committer.close()
        if self._committer_task is not None:
            await asyncio.gather(self._committer_task, return_exceptions=True)
        self._presentation_queue.close()
        tasks = tuple(self._tasks - self._history_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self._history_tasks:
            await asyncio.gather(
                *tuple(self._history_tasks), return_exceptions=True
            )
        with suppress(Exception):
            await self._provider.close()
        await self._events.put(_EVENTS_CLOSED)


__all__ = ["VoiceCoordinator"]
