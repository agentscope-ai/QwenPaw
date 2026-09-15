# -*- coding: utf-8 -*-
"""Task tracker for background runs: streaming, reconnect, multi-subscriber.

``run_key`` is typically ``ChatSpec.id`` (chat_id). Per run: task, queues,
event buffer. Reconnects get buffer replay + new events. Cleanup when task
completes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import weakref
from collections import OrderedDict, deque
from collections.abc import (
    AsyncGenerator,
    AsyncIterator,
    Awaitable,
    Callable,
    Coroutine,
)
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Literal, Optional
from uuid import uuid4

from ..hooks.session.signals import SessionSaveResult
from ..runtime.input_context import ChatInputContext
from ..runtime.reply_cycle import (
    InputStateEvent,
    InternalResultInput,
    ReplyCycleContext,
    ReplyContentEvent,
)

logger = logging.getLogger(__name__)

_SENTINEL = None
_MAX_STEER_INPUTS = 32
_MAX_STEER_IDEMPOTENCY_KEYS = 256

# Emitted to reconnect subscribers right after the buffered events, so
# the client can render the replayed part instantly (no token-by-token
# re-animation) and switch to live streaming afterwards.
REPLAY_END_SSE = f"data: {json.dumps({'type': 'replay_end'})}\n\n"


@dataclass(frozen=True)
class RunOutcome:
    """Execution result, independent of the renderer's response completion."""

    run_id: str
    status: Literal["completed", "failed", "cancelled"]
    error: str = ""
    persistence: str = "unknown"


@dataclass(frozen=True)
class RunStarted:
    run_id: str
    replay: bool = False


def _stream_error(sse: str) -> str:
    """Read run errors; failed tool messages are not run failures."""
    for line in sse.splitlines():
        if not line.startswith("data: "):
            continue
        try:
            payload = json.loads(line[6:])
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        if payload.get("object") not in {None, "response"}:
            continue
        error = payload.get("error")
        if error or payload.get("status") == "failed":
            if isinstance(error, dict):
                return str(error.get("message") or error.get("code") or error)
            return str(error or "Run failed")
    return ""


@dataclass(frozen=True)
class RunInput:
    """One ordered user input accepted by an active Chat run."""

    content_parts: tuple[Any, ...]
    idempotency_key: str
    message_metadata: dict[str, Any] | None = None
    request_context: dict[str, Any] | None = None
    model_slot_override: Any = None
    mode: Literal["queue", "steer"] = "steer"
    timeline_order: int = 0

    def __post_init__(self) -> None:
        content_parts = tuple(self.content_parts)
        idempotency_key = self.idempotency_key.strip()
        if (
            not content_parts
            or not idempotency_key
            or self.mode not in {"queue", "steer"}
            or self.timeline_order < 0
        ):
            raise ValueError(
                "run input content, identity and mode are required"
            )
        object.__setattr__(self, "content_parts", content_parts)
        object.__setattr__(self, "idempotency_key", idempotency_key)
        if self.message_metadata is not None:
            object.__setattr__(
                self,
                "message_metadata",
                dict(self.message_metadata),
            )
        if self.request_context is not None:
            object.__setattr__(
                self,
                "request_context",
                dict(self.request_context),
            )


class RunInputMailbox:
    """Bounded ordered mailbox consumed by the owning Agent loop."""

    def __init__(self, capacity: int = _MAX_STEER_INPUTS) -> None:
        self.input_context: ChatInputContext | None = None
        self._capacity = capacity
        self._pending: deque[RunInput | InternalResultInput] = deque()
        self._seen: set[str] = set()
        self._seen_order: deque[str] = deque()
        self._accepting = True

    def submit(self, item: RunInput | InternalResultInput) -> str:
        if not self._accepting:
            return "closed"
        if item.idempotency_key in self._seen:
            return "duplicate"
        if len(self._pending) >= self._capacity:
            return "full"
        self._seen.add(item.idempotency_key)
        self._seen_order.append(item.idempotency_key)
        while len(self._seen_order) > _MAX_STEER_IDEMPOTENCY_KEYS:
            self._seen.discard(self._seen_order.popleft())
        self._pending.append(item)
        return "accepted"

    def drain_steer(self) -> list[RunInput]:
        """Consume leading corrections before the next model request."""
        items: list[RunInput] = []
        while self._pending and self._pending[0].mode == "steer":
            items.append(self._pending.popleft())
        return items

    def drain_after_reply(self) -> list[RunInput]:
        """Consume one queued request or one consecutive steer batch."""
        if not self._pending:
            return []
        first = self._pending.popleft()
        items = [first]
        if first.mode == "steer":
            while self._pending and self._pending[0].mode == "steer":
                items.append(self._pending.popleft())
        return items

    @property
    def accepting(self) -> bool:
        """Whether the owning run can still consume newly submitted input."""
        return self._accepting

    def close(self) -> None:
        self._accepting = False


@dataclass
class _RunState:
    """Per-run state (task, queues, buffer), guarded by tracker lock."""

    task: asyncio.Future
    run_id: str = ""
    queues: list[asyncio.Queue] = field(default_factory=list)
    buffer: list[
        str | InputStateEvent | RunStarted | ReplyContentEvent
    ] = field(default_factory=list)
    start_time: Optional[datetime] = None
    finish_time: Optional[datetime] = None
    owner: object | None = None
    mailbox: RunInputMailbox = field(default_factory=RunInputMailbox)
    reply_cycle: ReplyCycleContext | None = None
    named_subscribers: dict[str, asyncio.Queue] = field(default_factory=dict)
    persistence: SessionSaveResult = field(default_factory=SessionSaveResult)
    on_finished: Callable[[str, datetime], Awaitable[Any]] | None = None


class TaskTracker:
    """Per-agent tracker: run_key -> RunState.

    All mutations to _runs under _lock. Producer broadcasts under lock.
    Subscribers use unbounded per-connection queues; disconnect removes them
    via :meth:`detach_subscriber`. A workspace reload reuses the same tracker
    so active runs remain reconnectable.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._runs: dict[str, _RunState] = {}
        self._outcomes: OrderedDict[str, deque[RunOutcome]] = OrderedDict()
        self._global_last_run_at: Optional[datetime] = None
        self._global_last_finish_at: Optional[datetime] = None
        self.background_results: dict[str, Any] = {}
        self.reply_views: dict[str, Any] = {}
        self.conversation_views: dict[str, Any] = {}
        self._input_contexts: dict[str, ChatInputContext] = {}
        self._start_listeners: dict[str, dict[str, Callable]] = {}

    def input_context(self, run_key: str) -> ChatInputContext:
        """Return the Chat's input source, also shared across successive runs."""
        return self._input_contexts.setdefault(run_key, ChatInputContext())

    def subscribe_starts(
        self, run_key: str, identity: str, callback: Callable
    ) -> None:
        """Attach an observer before a short run can finish."""
        self._start_listeners.setdefault(run_key, {})[identity] = callback

    def unsubscribe_starts(self, run_key: str, identity: str) -> None:
        listeners = self._start_listeners.get(run_key, {})
        listeners.pop(identity, None)
        if not listeners:
            self._start_listeners.pop(run_key, None)

    @property
    def lock(self) -> asyncio.Lock:
        return self._lock

    async def get_status(self, run_key: str) -> str:
        """Return ``'idle'`` or ``'running'``."""
        async with self._lock:
            state = self._runs.get(run_key)
        if state is None or state.task.done():
            return "idle"
        return "running"

    @asynccontextmanager
    async def idle_guard(self, run_key: str) -> AsyncIterator[None]:
        """Wait for one run key to be idle and prevent a concurrent start."""
        while True:
            active_task: asyncio.Future | None = None
            await self._lock.acquire()
            state = self._runs.get(run_key)
            if state is None or state.task.done():
                try:
                    yield
                finally:
                    self._lock.release()
                return
            active_task = state.task
            self._lock.release()
            await asyncio.wait({active_task})

    async def get_global_status(self) -> dict:
        """Get global agent status summary.

        Returns:
            dict with keys:
                - status: 'idle' | 'running'
                - running_task_count: int
                - last_run_at: Optional[datetime]
                - last_finish_at: Optional[datetime]
        """
        async with self._lock:
            running_count = sum(
                1 for state in self._runs.values() if not state.task.done()
            )
            status = "running" if running_count > 0 else "idle"

            return {
                "status": status,
                "running_task_count": running_count,
                "last_run_at": self._global_last_run_at,
                "last_finish_at": self._global_last_finish_at,
            }

    async def has_active_tasks(self) -> bool:
        """Check if any tasks are currently running.

        Returns:
            bool: True if any tasks are active, False otherwise
        """
        async with self._lock:
            for state in self._runs.values():
                if not state.task.done():
                    return True
            return False

    async def has_active_tasks_excluding(
        self,
        excluded_task: asyncio.Future | None,
    ) -> bool:
        """Check for active tasks other than ``excluded_task``."""
        async with self._lock:
            return any(
                not state.task.done() and state.task is not excluded_task
                for state in self._runs.values()
            )

    async def list_active_tasks(self) -> list[str]:
        """List all currently running task keys.

        Returns:
            list[str]: List of active run_keys
        """
        async with self._lock:
            return [
                run_key
                for run_key, state in self._runs.items()
                if not state.task.done()
            ]

    async def snapshot_active_tasks(
        self,
        owner: object | None = None,
    ) -> dict[str, asyncio.Future]:
        """Return the currently active tasks without tracking later runs."""
        async with self._lock:
            return {
                run_key: state.task
                for run_key, state in self._runs.items()
                if not state.task.done()
                and (owner is None or state.owner is owner)
            }

    async def wait_tasks_done(
        self,
        tasks: list[asyncio.Future],
        timeout: float = 300.0,
    ) -> bool:
        """Wait for a fixed task snapshot without cancelling on timeout."""
        if not tasks:
            return True

        async def _wait_snapshot() -> None:
            await asyncio.gather(
                *(asyncio.shield(task) for task in tasks),
                return_exceptions=True,
            )

        try:
            await asyncio.wait_for(_wait_snapshot(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def wait_all_done(self, timeout: float = 300.0) -> bool:
        """Wait for all active tasks to complete.

        Args:
            timeout: Maximum time to wait in seconds (default: 300s = 5min)

        Returns:
            bool: True if all tasks completed, False if timeout occurred
        """

        async def _wait_loop() -> None:
            while await self.has_active_tasks():
                await asyncio.sleep(0.5)

        try:
            await asyncio.wait_for(_wait_loop(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def attach(
        self, run_key: str, *, include_finished: bool = False
    ) -> asyncio.Queue | None:
        """Attach to an existing run.

        Returns a new queue pre-filled with the event buffer plus a
        ``replay_end`` marker, or ``None`` if no run is active for
        *run_key*.
        """
        async with self._lock:
            state = self._runs.get(run_key)
            if state is None or state.task.done():
                if include_finished:
                    queue: asyncio.Queue = asyncio.Queue()
                    for outcome in self._outcomes.get(run_key, ()):
                        queue.put_nowait(outcome)
                    queue.put_nowait(_SENTINEL)
                    return queue
                return None
            q: asyncio.Queue = asyncio.Queue()
            if include_finished:
                for outcome in self._outcomes.get(run_key, ()):
                    q.put_nowait(outcome)
            q.put_nowait(RunStarted(state.run_id, replay=True))
            for sse in state.buffer:
                if not isinstance(sse, RunStarted):
                    q.put_nowait(sse)
            q.put_nowait(REPLAY_END_SSE)
            state.queues.append(q)
            return q

    async def attach_live(self, run_key: str) -> asyncio.Queue | None:
        """Subscribe to future events only, for an accepted same-run input."""
        async with self._lock:
            state = self._runs.get(run_key)
            if state is None or state.task.done():
                return None
            queue: asyncio.Queue = asyncio.Queue()
            state.queues.append(queue)
            return queue

    async def attach_live_once(
        self,
        run_key: str,
        subscriber_id: str,
    ) -> asyncio.Queue | None:
        """Attach one named live subscriber at most once per active run."""
        subscription = await self.attach_live_once_with_identity(
            run_key,
            subscriber_id,
        )
        return subscription[0] if subscription is not None else None

    async def attach_live_once_with_identity(
        self,
        run_key: str,
        subscriber_id: str,
    ) -> tuple[asyncio.Queue, str] | None:
        """Attach one named subscriber and return its immutable run ID."""
        async with self._lock:
            state = self._runs.get(run_key)
            if state is None or state.task.done():
                return None
            if subscriber_id in state.named_subscribers:
                return None
            queue: asyncio.Queue = asyncio.Queue()
            # Typed observers need current execution facts even when attached
            # after the first reply boundary, but do not replay tool output.
            for event in state.buffer:
                if isinstance(event, InputStateEvent):
                    queue.put_nowait(event)
            state.queues.append(queue)
            state.named_subscribers[subscriber_id] = queue
            return queue, state.run_id

    async def claim_live_subscriber(
        self,
        run_key: str,
        subscriber_id: str,
        queue: asyncio.Queue,
    ) -> bool:
        """Claim an existing queue as the named subscriber for its run."""
        async with self._lock:
            state = self._runs.get(run_key)
            if state is None or state.task.done() or queue not in state.queues:
                return True
            existing = state.named_subscribers.get(subscriber_id)
            if existing is not None:
                return existing is queue
            state.named_subscribers[subscriber_id] = queue
            return True

    async def detach_subscriber(
        self,
        run_key: str,
        queue: asyncio.Queue,
    ) -> None:
        """Remove *queue* from *run_key*'s subscriber list.

        Idempotent if the run ended or *queue* was already removed.
        """
        async with self._lock:
            state = self._runs.get(run_key)
            if state is None:
                return
            try:
                state.queues.remove(queue)
            except ValueError:
                pass
            for subscriber_id, subscriber in list(
                state.named_subscribers.items(),
            ):
                if subscriber is queue:
                    state.named_subscribers.pop(subscriber_id, None)

    async def request_stop(self, run_key: str) -> bool:
        """Cancel the run. Returns ``True`` if it was running."""
        logger.debug("[STOP] request_stop called for run_key=%s", run_key)
        async with self._lock:
            state = self._runs.get(run_key)
            results = self.background_results.get(run_key)
            if results is not None:
                input_ids = (
                    state.reply_cycle.pending_input_ids()
                    if state is not None and state.reply_cycle is not None
                    else tuple(
                        {
                            i
                            for w in results.works.values()
                            if w.delivery not in {"delivered", "cancelled"}
                            for i in w.input_ids
                        }
                    )
                )
                results.cancel_inputs(input_ids)
            logger.debug(
                "[STOP] run_key=%s state=%s done=%s",
                run_key,
                "found" if state else "not_found",
                state.task.done() if state else "N/A",
            )
            if state is None or state.task.done():
                logger.debug(
                    "[STOP] Cannot stop run_key=%s (not running)",
                    run_key,
                )
                return False
            logger.debug(
                "[STOP] Calling task.cancel() for run_key=%s",
                run_key,
            )
            task = state.task
            if not task.cancelling():
                task.cancel()
            logger.debug("[STOP] task.cancel() called for run_key=%s", run_key)
        try:
            await task
        except asyncio.CancelledError:
            pass
        return True

    async def submit_or_start(
        self,
        run_key: str,
        payload: Any,
        stream_fn: Callable[..., Coroutine],
        run_input: RunInput,
        owner: object | None = None,
        *,
        accepted_sse: str | None = None,
        reserve_timeline_order: Callable[[], Awaitable[int]] | None = None,
    ) -> tuple[asyncio.Queue | None, str, str]:
        """Atomically steer an active run or start a new one.

        The returned status is ``started``, ``accepted``, ``duplicate`` or
        ``full``. Accepted and duplicate active-run submissions receive a new
        complete replay subscriber; a new run receives its initial events.
        """
        while True:
            finishing_task: asyncio.Future | None = None
            async with self._lock:
                state = self._runs.get(run_key)
                if state is not None and not state.task.done():
                    if not state.mailbox.accepting:
                        finishing_task = state.task
                    else:
                        status = state.mailbox.submit(run_input)
                        if (
                            status == "accepted"
                            and state.reply_cycle is not None
                        ):
                            state.reply_cycle.accept_input(
                                run_input.idempotency_key
                            )
                        if status == "accepted" and accepted_sse:
                            state.buffer.append(accepted_sse)
                            for subscriber in state.queues:
                                subscriber.put_nowait(accepted_sse)
                        if status == "full":
                            return None, status, state.run_id
                        queue: asyncio.Queue = asyncio.Queue()
                        queue.put_nowait(RunStarted(state.run_id, replay=True))
                        for event in state.buffer:
                            if not isinstance(event, RunStarted):
                                queue.put_nowait(event)
                        queue.put_nowait(REPLAY_END_SSE)
                        state.queues.append(queue)
                        return queue, status, state.run_id
                else:
                    queue, _ = self._start_locked(
                        run_key,
                        payload,
                        stream_fn,
                        owner,
                        [accepted_sse] if accepted_sse else None,
                        initial_input_id=run_input.idempotency_key,
                        reserve_timeline_order=reserve_timeline_order,
                    )
                    state = self._runs[run_key]
                    return queue, "started", state.run_id

            if finishing_task is not None:
                try:
                    await asyncio.shield(finishing_task)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    # Producer failures are already converted to SSE. Retry
                    # after cleanup so this input starts the next run.
                    pass

    async def submit_result(self, run_key: str, work: Any) -> str:
        """Admit an assistant result under the Chat single-writer lock."""
        owner = work.owner
        while True:
            await owner.refresh_runtime()
            finishing_task = None
            async with self._lock:
                if work.delivery in {
                    "cancelled",
                    "queued",
                    "observed",
                    "replied",
                    "delivered",
                }:
                    return work.delivery
                state = self._runs.get(run_key)
                if (
                    state is not None
                    and not state.task.done()
                    and not state.mailbox.accepting
                ):
                    finishing_task = state.task
                else:
                    item = owner.make_input(work)
                    if state is not None and not state.task.done():
                        status = state.mailbox.submit(item)
                        if status != "accepted":
                            work.delivery, work.error = (
                                "failed",
                                f"Result mailbox {status}",
                            )
                            return status
                    else:
                        if (
                            owner.source_saves.get(work.source_run_id)
                            != "saved"
                        ):
                            work.delivery = "failed"
                            work.error = (
                                "The originating tool receipt was not saved"
                            )
                            return "failed"
                        payload = dict(owner.payload)
                        payload.pop("content_parts", None)
                        payload.pop("message_metadata", None)
                        meta = dict(payload.get("meta") or {})
                        context = dict(meta.get("request_context") or {})
                        context["_internal_result"] = item
                        meta["request_context"] = context
                        payload["meta"] = meta
                        queue, _ = self._start_locked(
                            run_key,
                            payload,
                            owner.stream_fn,
                            owner.workspace,
                            None,
                            initial_input_id=item.input_ids[0],
                            reserve_timeline_order=owner.reserve_order,
                        )
                        state = self._runs[run_key]
                        state.queues.remove(queue)
                    work.delivery, work.consumer_run = "queued", state.run_id
                    return "accepted"
            if finishing_task is not None:
                try:
                    await asyncio.shield(finishing_task)
                except asyncio.CancelledError:
                    if asyncio.current_task().cancelling():
                        raise
                except Exception:
                    pass

    async def attach_or_start(
        self,
        run_key: str,
        payload: Any,
        stream_fn: Callable[[Any], AsyncIterator[str]],
        owner: object | None = None,
        on_finished: Callable[[str, datetime], Awaitable[Any]] | None = None,
        *,
        initial_events: list[str] | None = None,
    ) -> tuple[asyncio.Queue, bool]:
        """Attach to an existing run or start a new one.

        Returns ``(queue, is_new_run)``.
        """
        while True:
            finishing_task: asyncio.Future | None = None
            async with self._lock:
                state = self._runs.get(run_key)
                if state is not None and not state.task.done():
                    if state.mailbox.accepting:
                        q: asyncio.Queue = asyncio.Queue()
                        q.put_nowait(RunStarted(state.run_id, replay=True))
                        for sse in state.buffer:
                            if not isinstance(sse, RunStarted):
                                q.put_nowait(sse)
                        q.put_nowait(REPLAY_END_SSE)
                        state.queues.append(q)
                        return q, False
                    # The Agent has committed its final result and closed the
                    # mailbox, but the producer still needs to flush the last
                    # SSE events. Wait outside the tracker lock, then create a
                    # new turn in this same Chat instead of attaching the new
                    # input to a run that can no longer consume it.
                    finishing_task = state.task
                else:
                    return self._start_locked(
                        run_key,
                        payload,
                        stream_fn,
                        owner,
                        initial_events,
                        on_finished=on_finished,
                    )

            if finishing_task is not None:
                try:
                    await asyncio.shield(finishing_task)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    # Producer errors are already converted to SSE and the
                    # finished run is removed in its ``finally`` block.
                    pass

    def _start_locked(
        self,
        run_key: str,
        payload: Any,
        stream_fn: Callable[..., Coroutine],
        owner: object | None,
        initial_events: list[str] | None,
        *,
        initial_input_id: str | None = None,
        reserve_timeline_order: Callable[[], Awaitable[int]] | None = None,
        on_finished: Callable[[str, datetime], Awaitable[Any]] | None = None,
    ) -> tuple[asyncio.Queue, bool]:
        """Create a run while the caller holds :attr:`lock`."""
        my_queue: asyncio.Queue = asyncio.Queue()
        run_id = uuid4().hex
        initial_buffer = [RunStarted(run_id), *(initial_events or [])]
        for event in initial_buffer:
            my_queue.put_nowait(event)
        run = _RunState(
            task=asyncio.Future(),  # placeholder, replaced below
            run_id=run_id,
            queues=[my_queue],
            buffer=initial_buffer,
            owner=owner,
            on_finished=on_finished,
        )
        run.mailbox.input_context = self.input_context(run_key)
        self._runs[run_key] = run
        results = self.background_results.get(run_key)
        result_input = (
            payload.get("meta", {})
            .get("request_context", {})
            .get("_internal_result")
            if isinstance(payload, dict)
            else None
        )
        resumed_from = dict(results.input_runs) if results is not None else {}

        def publish_input_state(event: InputStateEvent) -> None:
            # Synchronous on the producer's event loop; no yielding.
            if results is None:
                run.buffer.append(event)
                for subscriber in run.queues:
                    subscriber.put_nowait(event)
                return
            for input_id in event.input_ids:
                previous = resumed_from.get(input_id, "")
                owned_event = replace(
                    event,
                    input_ids=(input_id,),
                    resumed_from=event.resumed_from
                    or (previous if previous != run_id else ""),
                )
                if results is not None:
                    results.input_runs[input_id] = run_id
                    if event.status == "cancelled":
                        results.cancel_inputs((input_id,))
                run.buffer.append(owned_event)
                for subscriber in run.queues:
                    subscriber.put_nowait(owned_event)

        if initial_input_id:
            from .chats.replies import ChatReplyView

            reply_view = self.reply_views.setdefault(run_key, ChatReplyView())

            def publish_reply_content(
                event: ReplyContentEvent, message: Any
            ) -> None:
                reply_view.observe(message, event.run_id)
                conversation = self.conversation_views.get(run_key)
                if conversation is not None:
                    conversation.observe_message(message)
                run.buffer.append(event)
                for subscriber in run.queues:
                    subscriber.put_nowait(event)

            run.reply_cycle = ReplyCycleContext(
                run_id,
                initial_input_id,
                reserve_timeline_order,
                on_input_state=publish_input_state,
                on_reply_content=publish_reply_content,
                has_pending_work=results.pending
                if results is not None
                else None,
                is_input_cancelled=results.cancelled_inputs.__contains__
                if results is not None
                else None,
            )
            if isinstance(result_input, InternalResultInput):
                run.reply_cycle.activate(result_input.input_ids)
            else:
                # Admission precedes the producer's first event-loop tick.
                # Publish its identity now so later queued inputs cannot be
                # observed (or numbered) ahead of the initial request.
                publish_input_state(
                    InputStateEvent(run_id, (initial_input_id,), "queued")
                )

        if isinstance(payload, dict):
            meta = payload.setdefault("meta", {})
            request_context = meta.setdefault("request_context", {})
            if isinstance(request_context, dict):
                request_context["_run_input_mailbox"] = run.mailbox
                request_context["_session_save_result"] = run.persistence
                if run.reply_cycle is not None:
                    request_context["_reply_cycle_context"] = run.reply_cycle

        tracker_ref = weakref.ref(self)

        async def _producer() -> None:
            start_time = datetime.now(timezone.utc)
            outcome = RunOutcome(run_id, "completed")

            try:
                tracker = tracker_ref()
                if tracker is not None:
                    async with tracker.lock:
                        run.start_time = start_time
                        # pylint: disable=protected-access
                        tracker._global_last_run_at = start_time

                if run.reply_cycle is not None:
                    run.reply_cycle.start_inputs(
                        run.reply_cycle.snapshot.responds_to_input_ids
                    )
                async for sse in stream_fn(payload):
                    error = _stream_error(sse)
                    if error:
                        outcome = RunOutcome(run_id, "failed", error)
                    tracker = tracker_ref()
                    if tracker is None:
                        return
                    async with tracker.lock:
                        run.buffer.append(sse)
                        for q in run.queues:
                            q.put_nowait(sse)
            except asyncio.CancelledError:
                outcome = RunOutcome(run_id, "cancelled")
                logger.debug("run cancelled run_key=%s", run_key)
            except Exception as exc:
                outcome = RunOutcome(
                    run_id, "failed", str(exc) or type(exc).__name__
                )
                logger.exception("run error run_key=%s", run_key)
                error = json.dumps({"error": "internal server error"})
                err_sse = f"data: {error}\n\n"
                tracker = tracker_ref()
                if tracker is not None:
                    async with tracker.lock:
                        run.buffer.append(err_sse)
                        for q in run.queues:
                            q.put_nowait(err_sse)
            finally:
                tracker = tracker_ref()
                if tracker is not None:
                    await tracker._finish_run(run_key, run, outcome)

        run.task = asyncio.create_task(_producer())

        def cancelled_before_start(task: asyncio.Task) -> None:
            tracker = tracker_ref()
            if (
                task.cancelled()
                and run.start_time is None
                and tracker is not None
            ):
                asyncio.create_task(
                    tracker._finish_run(
                        run_key,
                        run,
                        RunOutcome(run_id, "cancelled"),
                    )
                )

        run.task.add_done_callback(cancelled_before_start)
        for identity, callback in self._start_listeners.get(
            run_key, {}
        ).items():
            queue: asyncio.Queue = asyncio.Queue()
            for event in run.buffer:
                queue.put_nowait(event)
            run.queues.append(queue)
            run.named_subscribers[identity] = queue
            try:
                callback(queue, run_id)
            except Exception:
                run.queues.remove(queue)
                run.named_subscribers.pop(identity, None)
                logger.exception("Run observer failed to attach: %s", run_id)
        return my_queue, True

    async def _finish_run(
        self,
        run_key: str,
        run: _RunState,
        outcome: RunOutcome,
    ) -> None:
        # Retire live references even for ordinary Chats with no Voice reader.
        # A save flag alone is insufficient: verify the actual stored content.
        view = self.reply_views.get(run_key)
        if view is not None and run.persistence.status == "saved":
            view.saved(run.run_id)
        if (
            view is not None
            and run.persistence.status == "saved"
            and run.owner is not None
        ):
            try:
                chat = await run.owner.chat_manager.get_chat(run_key)
                if chat is not None:
                    replies = await view.read(run.owner.session, chat)
                    conversation = self.conversation_views.get(run_key)
                    if conversation is not None:
                        from .chats.conversation_view import reply_item

                        conversation.observe(
                            reply_item(reply) for reply in replies
                        )
            except Exception:
                logger.warning(
                    "Reply readback failed for %s; retaining live source",
                    run_key,
                    exc_info=True,
                )
        finish_time: datetime | None = None
        async with self.lock:
            if run.finish_time is not None:
                return
            run.mailbox.close()
            results = self.background_results.get(run_key)
            if results is not None:
                results.finish_run(
                    run.run_id, run.persistence.status, outcome.error
                )
                if run.reply_cycle is not None:
                    run.reply_cycle.settle_background_inputs(
                        results.settled_inputs(run.run_id)
                    )
            if run.reply_cycle is not None:
                run.reply_cycle.finish_run(outcome.status)
            run.finish_time = datetime.now(timezone.utc)
            finish_time = run.finish_time
            self._global_last_finish_at = run.finish_time
            outcome = RunOutcome(
                outcome.run_id,
                outcome.status,
                outcome.error,
                run.persistence.status,
            )
            outcomes = self._outcomes.setdefault(run_key, deque(maxlen=64))
            outcomes.append(outcome)
            self._outcomes.move_to_end(run_key)
            while len(self._outcomes) > 256:
                self._outcomes.popitem(last=False)
            for queue in run.queues:
                queue.put_nowait(outcome)
                queue.put_nowait(_SENTINEL)
            if self._runs.get(run_key) is run:
                self._runs.pop(run_key)

        if run.on_finished is not None and finish_time is not None:
            try:
                await run.on_finished(run_key, finish_time)
            except Exception:  # pylint: disable=broad-except
                logger.exception(
                    "run completion callback failed run_key=%s",
                    run_key,
                )

    async def stream_from_queue(
        self,
        queue: asyncio.Queue,
        run_key: str,
        *,
        lifecycle: bool = False,
    ) -> AsyncGenerator[str, None]:
        """Render SSE data, excluding internal execution outcomes."""
        stream = self.stream_events_from_queue(queue, run_key)
        try:
            async for event in stream:
                if isinstance(event, str):
                    yield event
                elif lifecycle and isinstance(event, RunStarted):
                    yield (
                        "data: "
                        + json.dumps(
                            {
                                "type": "run_started",
                                "run_id": event.run_id,
                                "replay": event.replay,
                            }
                        )
                        + "\n\n"
                    )
                elif lifecycle and isinstance(event, RunOutcome):
                    yield (
                        "data: "
                        + json.dumps(
                            {
                                "type": "run_sealed",
                                "run_id": event.run_id,
                                "persistence": event.persistence,
                            }
                        )
                        + "\n\n"
                    )
        finally:
            await stream.aclose()

    async def stream_events_from_queue(
        self,
        queue: asyncio.Queue,
        run_key: str,
    ) -> AsyncGenerator[
        str | RunOutcome | RunStarted | InputStateEvent | ReplyContentEvent,
        None,
    ]:
        """Yield SSE data and its authoritative outcome until the sentinel.

        Always detaches *queue* from *run_key* when this stream ends or is
        closed (including client disconnect), so reconnects do not leak queues.
        """
        try:
            while True:
                event = await queue.get()
                if event is _SENTINEL:
                    break
                yield event
        finally:
            await self.detach_subscriber(run_key, queue)
