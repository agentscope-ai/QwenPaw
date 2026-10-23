"""Current-Chat task admission and typed state for realtime voice."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import Any
from uuid import uuid4

from ...constant import QWENPAW_CLIENT_MESSAGE_ID_KEY
from ...runtime.reply_cycle import InputStateEvent, ReplyContentEvent
from ...schemas import TextContent
from ..chats.replies import ChatReply
from ..chats.run_coordinator import ChatInputRequest, ChatRunCoordinator
from ..chats.timeline import ChatTimelineJournal
from ..chats.title_generator import generate_and_update_title
from ..task_tracker import RunOutcome
from .contracts import (
    VoiceAdmissionMode,
    VoiceBridgeEvent,
    VoiceRunEvent,
    VoiceTaskEvent,
    VoiceTaskReceipt,
    VoiceTaskSnapshot,
    VoiceTaskStatus,
)
from .labels import VOICE_CHAT_PLACEHOLDER_NAME, task_ref_label

_BRIDGE_OBSERVER = "realtime_voice_task_bridge"
_TERMINAL = {"responded", "failed", "cancelled"}
_MAX_PENDING_ADMISSIONS = 32


@dataclass
class _TaskRecord:
    task_id: str
    task_ref: str
    requests: dict[str, str]
    status: VoiceTaskStatus
    version: int = 1
    run_id: str = ""
    replies: tuple[ChatReply, ...] = ()

    def snapshot(self) -> VoiceTaskSnapshot:
        return VoiceTaskSnapshot(
            task_id=self.task_id,
            task_ref=self.task_ref,
            request=next(iter(self.requests.values()), ""),
            status=self.status,
            version=self.version,
            run_id=self.run_id,
            replies=self.replies,
            input_requests=tuple(self.requests.items()),
        )


@dataclass(frozen=True)
class _PendingAdmission:
    text: str
    idempotency_key: str
    admission_mode: VoiceAdmissionMode
    completion: asyncio.Future[VoiceTaskReceipt]


@dataclass(frozen=True)
class VoiceAdmissionHandle:
    """A Chat-owned admission whose caller may stop waiting safely."""

    completion: asyncio.Future[VoiceTaskReceipt]

    async def wait(self) -> VoiceTaskReceipt:
        return await asyncio.shield(self.completion)


class VoiceTaskBridge:
    """Submit speech turns to one visible Chat and observe canonical state."""

    def __init__(self, workspace: Any, chat: Any) -> None:
        self._workspace = workspace
        self._chat = chat
        self._input_context = workspace.task_tracker.input_context(chat.id)
        self._lock = asyncio.Lock()
        self._records: dict[str, _TaskRecord] = {}
        self._input_task_ids: dict[str, str] = {}
        self._idempotency: dict[str, str] = {}
        self._current_run_task_id = ""
        self._next_task_ref = 1
        self._subscribers: set[asyncio.Queue[VoiceBridgeEvent]] = set()
        self._observer_task: asyncio.Task[None] | None = None
        self._observer_run_id = ""
        self._admission_queue: asyncio.Queue[
            _PendingAdmission
        ] = asyncio.Queue()
        self._admission_results: dict[
            str,
            asyncio.Future[VoiceTaskReceipt],
        ] = {}
        self._pending_admission_keys: set[str] = set()
        self._admission_task: asyncio.Task[None] | None = None
        self._closed = False
        self._observer_tasks: set[asyncio.Task[None]] = set()
        if hasattr(workspace.task_tracker, "subscribe_starts"):
            workspace.task_tracker.subscribe_starts(
                chat.id, _BRIDGE_OBSERVER, self._on_run_started
            )

    def _on_run_started(self, events: asyncio.Queue, run_id: str) -> None:
        self._start_observer(events, run_id)
        self._publish(VoiceRunEvent(run_id, "started"))

    def _start_observer(self, events: asyncio.Queue, run_id: str) -> None:
        self._observer_run_id = run_id
        task = asyncio.create_task(self._observe(events, run_id))
        self._observer_task = task
        self._observer_tasks.add(task)
        task.add_done_callback(self._observer_tasks.discard)

    def _input_ids(self, task_id: str) -> tuple[str, ...]:
        return tuple(
            i for i, task in self._input_task_ids.items() if task == task_id
        )

    def _snapshot(self, record: _TaskRecord) -> VoiceTaskSnapshot:
        results = getattr(
            self._workspace.task_tracker, "background_results", {}
        ).get(self._chat.id)
        ids = self._input_ids(record.task_id)
        facts = results.facts(set(ids)) if results is not None else ()
        states = tuple(
            (i, state.status)
            for i in ids
            if (state := self._input_context.state(i)) is not None
        )
        statuses = {status for _, status in states}
        status = next(
            (s for s in ("processing", "waiting", "queued") if s in statuses),
            None,
        )
        if status is None and states:
            status = (
                "accepted"
                if len(states) < len(ids)
                else "failed"
                if "failed" in statuses
                else "cancelled"
                if "cancelled" in statuses
                else "responded"
            )
        run_id = next(
            (
                state.run_id
                for i in reversed(ids)
                if (state := self._input_context.state(i)) is not None
                and (state.status == status or status == "responded")
            ),
            record.run_id,
        )
        return replace(
            record.snapshot(),
            status=status or record.status,
            run_id=run_id,
            background_work=facts,
            input_states=states,
        )

    async def _refresh_replies_locked(self) -> None:
        view = getattr(self._workspace.task_tracker, "reply_views", {}).get(
            self._chat.id
        )
        session = getattr(self._workspace, "session", None)
        if view is None or session is None:
            return
        replies = await view.read(session, self._chat)
        for record in self._records.values():
            ids = set(self._input_ids(record.task_id))
            owned = tuple(r for r in replies if ids.intersection(r.input_ids))
            if owned != record.replies:
                record.replies = owned
                record.version += 1
                self._publish(VoiceTaskEvent(self._snapshot(record)))

    def observe_input(
        self, identity: str, text: str, *, transcript_source_id: str = ""
    ) -> None:
        """Publish original words before admission or speech I/O."""
        if self._closed:
            raise RuntimeError("The Chat admission bridge is closed.")
        self._input_context.register(
            identity,
            text,
            context_only=False,
            transcript_source_id=transcript_source_id,
        )

    def observe_transcript(
        self, source_id: str, text: str, *, final: bool
    ) -> None:
        self._input_context.observe_transcript(source_id, text, final=final)

    async def persist_transcript(self, source_id: str) -> None:
        """Save final evidence for bound inputs without resubmitting them."""
        journal = ChatTimelineJournal(self._workspace, self._chat)
        for input_id, transcript in self._input_context.transcripts(
            source_id
        ).items():
            if transcript["final"]:
                await journal.append_speech_transcript(input_id, transcript)

    async def enqueue_input(
        self,
        text: str,
        *,
        idempotency_key: str,
        admission_mode: VoiceAdmissionMode = "queue",
        transcript_source_id: str = "",
    ) -> VoiceAdmissionHandle:
        """Take custody before a Voice session publishes a committed turn."""
        idempotency_key = idempotency_key.strip()
        if not idempotency_key:
            raise ValueError("The speech turn identity is empty.")
        if admission_mode not in {"queue", "steer"}:
            raise ValueError("unknown voice admission mode")
        self.observe_input(
            idempotency_key, text, transcript_source_id=transcript_source_id
        )

        async with self._lock:
            existing = self._admission_results.get(idempotency_key)
            if existing is not None:
                return VoiceAdmissionHandle(existing)
            if self._closed:
                raise RuntimeError("The Chat admission bridge is closed.")
            if len(self._pending_admission_keys) >= _MAX_PENDING_ADMISSIONS:
                self._input_context.set_admission(idempotency_key, "rejected")
                raise OverflowError(
                    "The current Chat has too many pending admissions.",
                )

            self._input_context.set_admission(idempotency_key, "preparing")
            completion = asyncio.get_running_loop().create_future()
            self._admission_results[idempotency_key] = completion
            self._pending_admission_keys.add(idempotency_key)
            self._admission_queue.put_nowait(
                _PendingAdmission(
                    text, idempotency_key, admission_mode, completion
                )
            )
            if self._admission_task is None or self._admission_task.done():
                self._admission_task = asyncio.create_task(
                    self._drain_admissions(),
                )
            return VoiceAdmissionHandle(completion)

    async def _drain_admissions(self) -> None:
        current = asyncio.current_task()
        while True:
            async with self._lock:
                try:
                    pending = self._admission_queue.get_nowait()
                except asyncio.QueueEmpty:
                    if self._admission_task is current:
                        self._admission_task = None
                    return

            try:
                receipt = await self.submit(
                    pending.text,
                    idempotency_key=pending.idempotency_key,
                    admission_mode=pending.admission_mode,
                )
            except asyncio.CancelledError:
                self._cancel_pending(pending)
                raise
            except Exception as exc:  # noqa: BLE001
                receipt = VoiceTaskReceipt.rejected("failed", str(exc)[:500])

            if not pending.completion.done():
                pending.completion.set_result(receipt)
            if (
                not receipt.accepted
                and self._input_context.admission_status(
                    pending.idempotency_key
                )
                == "preparing"
            ):
                self._input_context.set_admission(
                    pending.idempotency_key, "failed"
                )
            async with self._lock:
                self._pending_admission_keys.discard(pending.idempotency_key)

    def _cancel_pending(self, pending: _PendingAdmission) -> None:
        self._input_context.set_admission(pending.idempotency_key, "cancelled")
        if not pending.completion.done():
            pending.completion.set_result(
                VoiceTaskReceipt.rejected(
                    "cancelled", "The application is shutting down."
                )
            )

    async def submit(
        self,
        request: str,
        *,
        idempotency_key: str,
        admission_mode: VoiceAdmissionMode = "queue",
    ) -> VoiceTaskReceipt:
        """Admit one speech turn without waiting for the Agent or its tools."""
        request = request.strip()
        idempotency_key = idempotency_key.strip()
        if not request or len(request) > 8000 or not idempotency_key:
            return VoiceTaskReceipt.rejected(
                "failed", "The task request is empty or too long."
            )

        async with self._lock:
            existing_id = self._idempotency.get(idempotency_key)
            if existing_id:
                existing = self._records[existing_id].snapshot()
                return VoiceTaskReceipt(
                    task_id=existing.task_id,
                    task_ref=existing.task_ref,
                    accepted=self._input_context.admission_status(
                        idempotency_key
                    )
                    == "admitted",
                    status=existing.status,
                    message="This speech turn was already submitted.",
                )
            input_id = uuid4().hex
            record = self._add_record_locked(input_id, request, "accepted")
            self._idempotency[idempotency_key] = input_id
            self._input_context.register(idempotency_key, request)
            self._input_context.bind(input_id, idempotency_key)

        try:
            transcript = self._input_context.transcripts().get(input_id)
            if transcript is not None:
                await ChatTimelineJournal(
                    self._workspace, self._chat
                ).append_speech_transcript(input_id, transcript)
            submission = await ChatRunCoordinator.submit(
                self._workspace,
                self._chat,
                ChatInputRequest(
                    content_parts=(TextContent(text=request),),
                    client_message_id=input_id,
                    message_metadata={
                        QWENPAW_CLIENT_MESSAGE_ID_KEY: input_id,
                        "realtime_voice_task_id": input_id,
                        "realtime_voice_turn_id": idempotency_key,
                    },
                    origin="speech",
                    request_context={},
                    mode=admission_mode,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            await self._transition(input_id, "failed")
            return VoiceTaskReceipt(
                task_id=input_id,
                task_ref=record.task_ref,
                accepted=False,
                status="failed",
                message=str(exc)[:500],
                input_id=input_id,
            )

        async with self._lock:
            # A steer into the current run joins that run's task record.
            target = self._records.get(self._current_run_task_id)
            if (
                target is not None
                and self._snapshot(target).run_id == submission.run_id
            ):
                self._records.pop(input_id)
                target.requests[input_id] = request
                target.version += 1
                target.run_id = submission.run_id
                self._input_task_ids[input_id] = target.task_id
                self._idempotency[idempotency_key] = target.task_id
                record = target
                self._publish(VoiceTaskEvent(self._snapshot(target)))
            else:
                record.run_id = submission.run_id
                self._current_run_task_id = input_id

        await self._refresh_input_state(
            InputStateEvent(submission.run_id, (input_id,), "queued")
        )
        status = self._snapshot(record).status
        await self._attach_observer(submission.events, submission.run_id)
        if self._chat.name == VOICE_CHAT_PLACEHOLDER_NAME:
            asyncio.create_task(
                generate_and_update_title(
                    workspace=self._workspace,
                    chat_id=self._chat.id,
                    user_message=request,
                    placeholder_name=VOICE_CHAT_PLACEHOLDER_NAME,
                )
            )
        return VoiceTaskReceipt(
            task_id=record.task_id,
            task_ref=record.task_ref,
            accepted=True,
            status=status,
            input_id=input_id,
        )

    def _add_record_locked(
        self,
        task_id: str,
        request: str,
        status: VoiceTaskStatus,
        *,
        run_id: str = "",
    ) -> _TaskRecord:
        record = _TaskRecord(
            task_id=task_id,
            task_ref=task_ref_label(self._next_task_ref),
            requests={task_id: request},
            status=status,
            run_id=run_id,
        )
        self._next_task_ref += 1
        self._records[task_id] = record
        self._input_task_ids[task_id] = task_id
        return record

    async def status(self, task_id: str) -> VoiceTaskSnapshot:
        task_id = task_id.strip()
        async with self._lock:
            record = self._records.get(task_id)
            if record is not None:
                return record.snapshot()
        return VoiceTaskSnapshot(
            task_id=task_id,
            task_ref="",
            request="",
            status="not_found",
            version=0,
        )

    async def presentation_snapshots(self) -> tuple[VoiceTaskSnapshot, ...]:
        """Read all records so speech totals are not a context window."""
        async with self._lock:
            await self._refresh_replies_locked()
            return tuple(
                self._snapshot(record) for record in self._records.values()
            )

    def subscribe(self) -> asyncio.Queue[VoiceBridgeEvent]:
        queue: asyncio.Queue[VoiceBridgeEvent] = asyncio.Queue()
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[VoiceBridgeEvent]) -> None:
        self._subscribers.discard(queue)

    async def observe_active_run(self) -> str | None:
        """Attach typed observation to a run started by keyboard input."""
        subscription = (
            await self._workspace.task_tracker.attach_live_once_with_identity(
                self._chat.id,
                _BRIDGE_OBSERVER,
            )
        )
        if subscription is None:
            return None
        events, run_id = subscription
        self._start_observer(events, run_id)
        return run_id

    async def _attach_observer(
        self, events: asyncio.Queue, run_id: str
    ) -> None:
        tracker = self._workspace.task_tracker
        claimed = await tracker.claim_live_subscriber(
            self._chat.id, _BRIDGE_OBSERVER, events
        )
        if not claimed or (
            self._observer_task is not None
            and not self._observer_task.done()
            and self._observer_run_id == run_id
        ):
            await tracker.detach_subscriber(self._chat.id, events)
            return
        self._start_observer(events, run_id)

    async def _observe(self, events: asyncio.Queue, run_id: str) -> None:
        outcome: RunOutcome | None = None
        stream = self._workspace.task_tracker.stream_events_from_queue(
            events, self._chat.id
        )
        try:
            async for raw_event in stream:
                if isinstance(raw_event, ReplyContentEvent):
                    for input_id in raw_event.input_ids:
                        await self._ensure_observed_task(
                            self._input_task_ids.get(input_id, input_id),
                            raw_event.run_id,
                        )
                    async with self._lock:
                        await self._refresh_replies_locked()
                    continue
                if isinstance(raw_event, RunOutcome):
                    if raw_event.run_id == run_id:
                        outcome = raw_event
                    continue
                if (
                    isinstance(raw_event, InputStateEvent)
                    and raw_event.run_id == run_id
                ):
                    await self._refresh_input_state(raw_event)
        finally:
            await stream.aclose()
        # Observer teardown is not evidence that the Agent stopped; only the
        # Chat-owned producer publishes a terminal outcome.
        if outcome is not None:
            async with self._lock:
                await self._refresh_replies_locked()
            self._publish(VoiceRunEvent(run_id, outcome.status, outcome.error))

    async def _refresh_input_state(self, event: InputStateEvent) -> None:
        """Render the producer's latest state; observers never rewrite it."""
        for input_id in event.input_ids:
            current = self._input_context.state(input_id)
            if current is None or current.run_id != event.run_id:
                continue
            task_id = self._input_task_ids.get(input_id, input_id)
            await self._ensure_observed_task(task_id, event.run_id)
            async with self._lock:
                current = self._input_context.state(input_id)
                if current is None or current.run_id != event.run_id:
                    continue
                snapshot = self._snapshot(self._records[task_id])
            await self._transition(
                task_id,
                snapshot.status,
                run_id=snapshot.run_id,
                allow_reopen=True,
            )

    async def _ensure_observed_task(self, task_id: str, run_id: str) -> None:
        async with self._lock:
            if task_id in self._records:
                return
            record = self._add_record_locked(
                task_id, "", "queued", run_id=run_id
            )
            event = VoiceTaskEvent(self._snapshot(record))
        self._publish(event)

    def _publish(self, event: VoiceBridgeEvent) -> None:
        for subscriber in tuple(self._subscribers):
            subscriber.put_nowait(event)

    async def _transition(
        self,
        task_id: str,
        status: VoiceTaskStatus,
        *,
        run_id: str = "",
        allow_reopen: bool = False,
    ) -> None:
        async with self._lock:
            record = self._records.get(task_id)
            if record is None or (
                record.status in _TERMINAL and not allow_reopen
            ):
                return
            if record.status == status and (
                not run_id or record.run_id == run_id
            ):
                return
            record.status = status
            if run_id:
                record.run_id = run_id
            record.version += 1
            event = VoiceTaskEvent(self._snapshot(record))
        self._publish(event)

    async def close(self) -> None:
        if hasattr(self._workspace.task_tracker, "unsubscribe_starts"):
            self._workspace.task_tracker.unsubscribe_starts(
                self._chat.id, _BRIDGE_OBSERVER
            )
        for observer in tuple(self._observer_tasks):
            observer.cancel()
        await asyncio.gather(*self._observer_tasks, return_exceptions=True)
        async with self._lock:
            self._closed = True
            admission_task = self._admission_task
            self._admission_task = None
        if admission_task is not None and not admission_task.done():
            admission_task.cancel()
            await asyncio.gather(admission_task, return_exceptions=True)

        async with self._lock:
            while True:
                try:
                    pending = self._admission_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if not pending.completion.done():
                    self._cancel_pending(pending)
            self._pending_admission_keys.clear()
            self._admission_results.clear()
        task = self._observer_task
        self._observer_task = None
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self._subscribers.clear()


__all__ = ["VoiceAdmissionHandle", "VoiceTaskBridge"]
