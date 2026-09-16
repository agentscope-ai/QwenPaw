"""Current-Chat task admission and typed state for realtime voice."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, replace
from typing import Any
from uuid import uuid4

from ...constant import (
    CHAT_CONVERSATION_CONTEXT_KEY,
    CHAT_INPUT_TARGET_KEY,
    QWENPAW_CLIENT_MESSAGE_ID_KEY,
)
from ...runtime.reply_cycle import InputStateEvent, ReplyContentEvent
from ..chats.replies import ChatReply
from ...schemas import TextContent
from ..chats.run_coordinator import ChatInputRequest, ChatRunCoordinator
from ..chats.title_generator import generate_and_update_title
from ..task_tracker import RunOutcome
from .contracts import (
    HandoffVoiceAction,
    VoiceAction,
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
    action: HandoffVoiceAction
    text: str
    idempotency_key: str
    admission_mode: VoiceAdmissionMode
    completion: asyncio.Future[VoiceTaskReceipt]
    conversation_context: str


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
        self._task_refs: dict[str, str] = {}
        self._input_task_ids: dict[str, str] = {}
        self._idempotency: dict[str, str] = {}
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
        self._observer_tasks: set[asyncio.Task] = set()
        if hasattr(workspace.task_tracker, "subscribe_starts"):
            workspace.task_tracker.subscribe_starts(
                chat.id, _BRIDGE_OBSERVER, self._on_run_started
            )

    def _on_run_started(self, events: asyncio.Queue, run_id: str) -> None:
        self._observer_run_id = run_id
        self._observer_task = asyncio.create_task(
            self._observe(events, run_id)
        )
        self._observer_tasks.add(self._observer_task)
        self._observer_task.add_done_callback(self._observer_tasks.discard)
        self._publish(VoiceRunEvent(run_id, "started"))

    def _snapshot(self, record: _TaskRecord) -> VoiceTaskSnapshot:
        results = getattr(
            self._workspace.task_tracker, "background_results", {}
        ).get(self._chat.id)
        ids = tuple(
            i
            for i, task in self._input_task_ids.items()
            if task == record.task_id
        )
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
            ids = {
                i
                for i, task in self._input_task_ids.items()
                if task == record.task_id
            }
            owned = tuple(r for r in replies if ids.intersection(r.input_ids))
            if owned != record.replies:
                record.replies = owned
                record.version += 1
                self._publish(VoiceTaskEvent(self._snapshot(record)))

    def observe_input(
        self, identity: str, text: str, action: VoiceAction
    ) -> None:
        """Publish original words before admission or speech I/O."""
        if self._closed:
            raise RuntimeError("The Chat admission bridge is closed.")
        task_ref = getattr(action, "task_ref", "")
        target = self._task_refs.get(task_ref, "") if task_ref else ""
        self._input_context.register(
            identity,
            text,
            target=target,
            context_only=not isinstance(action, HandoffVoiceAction),
        )

    async def enqueue_action(
        self,
        action: HandoffVoiceAction,
        text: str,
        *,
        idempotency_key: str,
        admission_mode: VoiceAdmissionMode = "queue",
        conversation_context: str = "",
    ) -> VoiceAdmissionHandle:
        """Take custody before a Voice session publishes a committed turn."""
        idempotency_key = idempotency_key.strip()
        if not idempotency_key:
            raise ValueError("The speech turn identity is empty.")
        if admission_mode not in {"queue", "steer"}:
            raise ValueError("unknown voice admission mode")
        if not isinstance(action, HandoffVoiceAction):
            raise TypeError("Only handoff actions can enter Chat admission.")
        self.observe_input(idempotency_key, text, action)

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
            pending = _PendingAdmission(
                action=action,
                text=text,
                idempotency_key=idempotency_key,
                admission_mode=admission_mode,
                completion=completion,
                conversation_context=conversation_context,
            )
            self._admission_results[idempotency_key] = completion
            self._pending_admission_keys.add(idempotency_key)
            self._admission_queue.put_nowait(pending)
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
                receipt = await self._execute_admission(pending)
            except asyncio.CancelledError:
                self._input_context.set_admission(
                    pending.idempotency_key, "cancelled"
                )
                if not pending.completion.done():
                    pending.completion.set_result(
                        VoiceTaskReceipt(
                            task_id="",
                            task_ref="",
                            accepted=False,
                            status="cancelled",
                            message="The application is shutting down.",
                        ),
                    )
                raise
            except Exception as exc:  # noqa: BLE001
                receipt = VoiceTaskReceipt(
                    task_id="",
                    task_ref="",
                    accepted=False,
                    status="failed",
                    message=str(exc)[:500],
                )

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
                self._pending_admission_keys.discard(
                    pending.idempotency_key,
                )

    async def _execute_admission(
        self,
        pending: _PendingAdmission,
    ) -> VoiceTaskReceipt:
        return await self.submit(
            pending.text,
            idempotency_key=pending.idempotency_key,
            admission_mode=pending.admission_mode,
            conversation_context=pending.conversation_context,
            task_ref=pending.action.task_ref,
        )

    async def submit(
        self,
        request: str,
        *,
        idempotency_key: str,
        admission_mode: VoiceAdmissionMode = "queue",
        conversation_context: str = "",
        task_ref: str = "",
    ) -> VoiceTaskReceipt:
        """Admit one speech turn without waiting for the Agent or its tools."""
        request = request.strip()
        idempotency_key = idempotency_key.strip()
        if not request or len(request) > 8000 or not idempotency_key:
            return VoiceTaskReceipt(
                task_id="",
                task_ref="",
                accepted=False,
                status="failed",
                message="The task request is empty or too long.",
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
            task_id = uuid4().hex
            record = self._create_record_locked(
                task_id,
                request,
                "accepted",
            )
            self._records[task_id] = record
            self._input_task_ids[task_id] = task_id
            self._idempotency[idempotency_key] = task_id
            referenced_id = self._task_refs.get(task_ref, "")
            self._input_context.register(
                idempotency_key, request, target=referenced_id
            )
            self._input_context.bind(task_id, idempotency_key)

        try:
            submission = await ChatRunCoordinator.submit(
                self._workspace,
                self._chat,
                ChatInputRequest(
                    content_parts=(TextContent(text=request),),
                    client_message_id=task_id,
                    message_metadata={
                        QWENPAW_CLIENT_MESSAGE_ID_KEY: task_id,
                        "realtime_voice_task_id": task_id,
                        "realtime_voice_turn_id": idempotency_key,
                    },
                    origin="speech",
                    request_context={
                        CHAT_CONVERSATION_CONTEXT_KEY: conversation_context,
                        **(
                            {
                                CHAT_INPUT_TARGET_KEY: json.dumps(
                                    {
                                        "input_id": referenced_id,
                                        "task_ref": task_ref,
                                        "relationship": "reference",
                                    },
                                    ensure_ascii=False,
                                ),
                            }
                            if referenced_id
                            else {}
                        ),
                    },
                    mode=admission_mode,
                ),
            )
        except OverflowError as exc:
            await self._transition(task_id, "failed")
            return VoiceTaskReceipt(
                task_id=task_id,
                task_ref=record.task_ref,
                accepted=False,
                status="failed",
                message=str(exc),
            )
        except Exception as exc:  # noqa: BLE001
            await self._transition(task_id, "failed")
            return VoiceTaskReceipt(
                task_id=task_id,
                task_ref=record.task_ref,
                accepted=False,
                status="failed",
                message=str(exc)[:500],
            )

        await self._refresh_input_state(
            InputStateEvent(submission.run_id, (task_id,), "queued")
        )
        status = self._snapshot(record).status
        await self._attach_observer(
            submission.events,
            submission.run_id,
        )
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
            task_id=task_id,
            task_ref=record.task_ref,
            accepted=True,
            status=status,
        )

    def _create_record_locked(
        self,
        task_id: str,
        request: str,
        status: VoiceTaskStatus,
        *,
        run_id: str = "",
    ) -> _TaskRecord:
        ordinal = self._next_task_ref
        self._next_task_ref += 1
        task_ref = task_ref_label(ordinal)
        record = _TaskRecord(
            task_id=task_id,
            task_ref=task_ref,
            requests={task_id: request},
            status=status,
            run_id=run_id,
        )
        self._task_refs[task_ref] = task_id
        return record

    async def status(self, task_id: str) -> VoiceTaskSnapshot:
        async with self._lock:
            record = self._records.get(task_id.strip())
            if record is not None:
                return record.snapshot()
        return VoiceTaskSnapshot(
            task_id=task_id.strip(),
            task_ref="",
            request="",
            status="not_found",
            version=0,
        )

    async def active_snapshots(self) -> tuple[VoiceTaskSnapshot, ...]:
        """Return only live task state; terminal history stays in Chat."""
        async with self._lock:
            return tuple(
                record.snapshot()
                for record in self._records.values()
                if record.status not in _TERMINAL
            )

    async def routing_snapshots(self) -> tuple[VoiceTaskSnapshot, ...]:
        """Expose admitted inputs; the router owns its context window."""
        async with self._lock:
            return tuple(
                self._snapshot(record) for record in self._records.values()
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
        self._observer_run_id = run_id
        self._observer_task = asyncio.create_task(
            self._observe(events, run_id)
        )
        return run_id

    async def _attach_observer(
        self,
        events: asyncio.Queue,
        run_id: str,
    ) -> None:
        tracker = self._workspace.task_tracker
        claimed = await tracker.claim_live_subscriber(
            self._chat.id,
            _BRIDGE_OBSERVER,
            events,
        )
        if not claimed:
            await tracker.detach_subscriber(self._chat.id, events)
            return
        if (
            self._observer_task is not None
            and not self._observer_task.done()
            and self._observer_run_id == run_id
        ):
            await tracker.detach_subscriber(self._chat.id, events)
            return
        self._observer_run_id = run_id
        self._observer_task = asyncio.create_task(
            self._observe(events, run_id)
        )

    async def _observe(
        self,
        events: asyncio.Queue,
        run_id: str,
    ) -> None:
        outcome: RunOutcome | None = None
        stream = self._workspace.task_tracker.stream_events_from_queue(
            events,
            self._chat.id,
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
            # Observer teardown is not evidence that the Agent stopped or
            # succeeded.
            # The Chat-owned producer alone publishes its terminal outcome.
        if outcome is not None:
            async with self._lock:
                await self._refresh_replies_locked()
            self._publish(
                VoiceRunEvent(
                    run_id=run_id,
                    status=outcome.status,
                    error=outcome.error,
                )
            )

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

    async def _ensure_observed_task(
        self,
        task_id: str,
        run_id: str,
    ) -> None:
        async with self._lock:
            if task_id in self._records:
                return
            record = self._create_record_locked(
                task_id,
                "",
                "queued",
                run_id=run_id,
            )
            self._records[task_id] = record
            self._input_task_ids[task_id] = task_id
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
            changed = record.status != status or (
                run_id and record.run_id != run_id
            )
            if not changed:
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
                    self._input_context.set_admission(
                        pending.idempotency_key, "cancelled"
                    )
                    pending.completion.set_result(
                        VoiceTaskReceipt(
                            task_id="",
                            task_ref="",
                            accepted=False,
                            status="cancelled",
                            message="The application is shutting down.",
                        ),
                    )
            self._pending_admission_keys.clear()
            self._admission_results.clear()
        task = self._observer_task
        self._observer_task = None
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self._subscribers.clear()


__all__ = ["VoiceAdmissionHandle", "VoiceTaskBridge"]
