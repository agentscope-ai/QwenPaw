# -*- coding: utf-8 -*-
"""Task tracker for background runs: streaming, reconnect, multi-subscriber.

``run_key`` is typically ``ChatSpec.id`` (chat_id). Per run: task, queues,
folded replay store. Reconnects get replay + new events. Terminal replay is
retained briefly so a history request cannot race with run cleanup.
"""

from __future__ import annotations

import asyncio
import json
import logging
import weakref
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import (
    Any,
    AsyncGenerator,
    AsyncIterator,
    Awaitable,
    Callable,
    Optional,
)
from .chats.models import session_storage_identity

from .replay_store import (
    RECONNECT_REQUIRED_SSE,
    REPLAY_UNAVAILABLE_SSE,
    ReplayStore,
)
from .replay_snapshot import ReplayPrefix, materialize_replay
from .replay_persistence import replay_receipt

logger = logging.getLogger(__name__)

_SENTINEL = None
_DEFAULT_SUBSCRIBER_QUEUE_MAX = 256
_DEFAULT_RECONNECT_GRACE_SECONDS = 15.0
_DEFAULT_COMPLETED_RUN_MAX = 16

# Indirection so tests can simulate a failing task creation without
# patching the process-wide ``asyncio`` module.
_create_task = asyncio.create_task

# Emitted to reconnect subscribers right after the replayed events, so
# the client can render the replayed part instantly (no token-by-token
# re-animation) and switch to live streaming afterwards.
REPLAY_END_SSE = f"data: {json.dumps({'type': 'replay_end'})}\n\n"


class _SubscriberQueue(asyncio.Queue):
    """Bound both event count and retained text, excluding replay prefixes."""

    def __init__(self, maxsize: int) -> None:
        super().__init__(maxsize=maxsize)
        self._text_size = 0
        self.run_task: asyncio.Future | None = None

    def put_nowait(self, item: str | None) -> None:
        size = len(item or "") * 4
        if self._text_size + size > 8 * 1024 * 1024:
            raise asyncio.QueueFull
        super().put_nowait(item)
        self._text_size += size

    def get_nowait(self) -> str | None:
        item = super().get_nowait()
        self._text_size -= len(item or "") * 4
        return item


class RunUnavailableError(ValueError):
    """The conversation was removed or is being deleted."""


@dataclass
class _RunState:
    """Per-run state (task, queues, replay), guarded by tracker lock."""

    task: asyncio.Future
    queues: list[asyncio.Queue] = field(default_factory=list)
    replay: ReplayStore = field(default_factory=ReplayStore)
    start_time: Optional[datetime] = None
    finish_time: Optional[datetime] = None
    owner: object | None = None
    channel_id: str | None = None


class TaskTracker:
    """Per-agent tracker: run_key -> RunState.

    All mutations to _runs under _lock. Producer broadcasts under lock.
    Subscribers use bounded per-connection queues; a slow subscriber receives
    an explicit reconnect marker and is detached without delaying the run.
    A workspace reload reuses the same tracker so active runs remain
    reconnectable.
    """

    def __init__(
        self,
        *,
        subscriber_queue_max: int = _DEFAULT_SUBSCRIBER_QUEUE_MAX,
        reconnect_grace_seconds: float = _DEFAULT_RECONNECT_GRACE_SECONDS,
        completed_run_max: int = _DEFAULT_COMPLETED_RUN_MAX,
    ) -> None:
        if subscriber_queue_max < 2:
            raise ValueError("subscriber queue limit must be at least 2")
        if reconnect_grace_seconds < 0 or completed_run_max < 1:
            raise ValueError("completed replay limits are invalid")
        self._lock = asyncio.Lock()
        self._runs: dict[str, _RunState] = {}
        self._blocked_runs: set[str] = set()
        self._session_tasks: dict[tuple[str, str, str], dict] = {}
        self._blocked_sessions: set[tuple[str, str, str]] = set()
        self._subscriber_queue_max = subscriber_queue_max
        self._reconnect_grace_seconds = reconnect_grace_seconds
        self._completed_run_max = completed_run_max
        self._global_last_run_at: Optional[datetime] = None
        self._global_last_finish_at: Optional[datetime] = None

    def _reconnect_queue(self, *, unavailable: bool = False) -> asyncio.Queue:
        """Return a terminal queue instructing the client to resync."""
        queue: asyncio.Queue = _SubscriberQueue(
            maxsize=self._subscriber_queue_max,
        )
        queue.put_nowait(
            REPLAY_UNAVAILABLE_SSE if unavailable else RECONNECT_REQUIRED_SSE,
        )
        queue.put_nowait(_SENTINEL)
        return queue

    def _attach_queue(
        self,
        state: _RunState,
        *,
        include_replay_end: bool,
    ) -> asyncio.Queue:
        """Create a bounded subscriber from the replay snapshot."""
        replay = list(state.replay.replay())
        marker_count = 1 if include_replay_end else 0
        if state.replay.requires_resync or (
            len(replay) + marker_count > self._subscriber_queue_max
            or sum(map(len, replay)) * 4 > 8 * 1024 * 1024 - 1024
        ):
            return self._reconnect_queue(
                unavailable=state.replay.recovery_unavailable,
            )
        queue: asyncio.Queue = _SubscriberQueue(
            maxsize=self._subscriber_queue_max,
        )
        for sse in replay:
            queue.put_nowait(sse)
        if include_replay_end:
            queue.put_nowait(REPLAY_END_SSE)
        state.queues.append(queue)
        return queue

    def _completed_queue(self, state: _RunState) -> asyncio.Queue:
        """Return terminal replay for the history-to-live handoff window."""
        replay = list(state.replay.replay())
        if state.replay.requires_resync or (
            len(replay) + 2 > self._subscriber_queue_max
            or sum(map(len, replay)) * 4 > 8 * 1024 * 1024 - 1024
        ):
            return self._reconnect_queue(
                unavailable=state.replay.recovery_unavailable,
            )
        queue: asyncio.Queue = _SubscriberQueue(
            maxsize=self._subscriber_queue_max,
        )
        for sse in replay:
            queue.put_nowait(sse)
        queue.put_nowait(REPLAY_END_SSE)
        queue.put_nowait(_SENTINEL)
        return queue

    @staticmethod
    def _reset_slow_subscriber(queue: asyncio.Queue) -> None:
        """Replace queued events with a reconnect marker and EOF."""
        while not queue.empty():
            queue.get_nowait()
        queue.put_nowait(RECONNECT_REQUIRED_SSE)
        queue.put_nowait(_SENTINEL)

    def _broadcast(self, state: _RunState, event: str | None) -> None:
        """Offer one event without allowing subscribers to block the run."""
        retained: list[asyncio.Queue] = []
        for queue in state.queues:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                self._reset_slow_subscriber(queue)
                continue
            retained.append(queue)
        state.queues = retained

    @staticmethod
    def _is_running(state: _RunState) -> bool:
        return state.finish_time is None and not state.task.done()

    def _prune_completed_locked(self) -> None:
        completed: list[tuple[datetime, str]] = []
        for run_key, state in self._runs.items():
            if state.finish_time is not None:
                completed.append((state.finish_time, run_key))
        completed.sort()
        for _finish_time, run_key in completed[: -self._completed_run_max]:
            self._runs.pop(run_key, None)

    async def _expire_completed(
        self,
        run_key: str,
        state: _RunState,
    ) -> None:
        """Remove a completed run unless a newer run replaced it."""
        async with self._lock:
            if self._runs.get(run_key) is state:
                self._runs.pop(run_key, None)

    def _retain_completed_locked(
        self,
        run_key: str,
        state: _RunState,
    ) -> None:
        """Retain bounded terminal replay for the reconnect grace period."""
        self._prune_completed_locked()
        if self._reconnect_grace_seconds == 0:
            self._runs.pop(run_key, None)
            return

        tracker_ref = weakref.ref(self)

        def expire() -> None:
            tracker = tracker_ref()
            if tracker is not None:
                # pylint: disable-next=protected-access
                _create_task(tracker._expire_completed(run_key, state))

        asyncio.get_running_loop().call_later(
            self._reconnect_grace_seconds,
            expire,
        )

    @asynccontextmanager
    async def session_execution(self, identity, can_start, *, owner=None):
        """Track all workspace writers, including callers outside channels."""
        identity = session_storage_identity(*identity)
        task = asyncio.current_task()
        async with self._lock:
            if identity in self._blocked_sessions or not await can_start():
                raise RunUnavailableError("conversation deletion is pending")
            self._session_tasks.setdefault(identity, {})[task] = owner
        try:
            yield
        finally:
            async with self._lock:
                tasks = self._session_tasks.get(identity)
                if tasks is not None:
                    tasks.pop(task, None)
                    if not tasks:
                        self._session_tasks.pop(identity, None)

    @asynccontextmanager
    async def stop_session_writers(self, identities):
        """Keep writers excluded until persisted cleanup has finished."""
        identities = {session_storage_identity(*key) for key in identities}
        async with self._lock:
            if identities & self._blocked_sessions:
                raise RunUnavailableError("conversation deletion is pending")
            self._blocked_sessions.update(identities)
            tasks = set().union(
                *(self._session_tasks.get(key, {}) for key in identities),
            )
        try:
            for task in tasks:
                if not task.done() and not task.cancelling():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            yield
        finally:
            async with self._lock:
                self._blocked_sessions.difference_update(identities)

    @property
    def lock(self) -> asyncio.Lock:
        return self._lock

    async def get_status(self, run_key: str) -> str:
        """Return ``'idle'`` or ``'running'``."""
        async with self._lock:
            state = self._runs.get(run_key)
        if state is None or not self._is_running(state):
            return "idle"
        return "running"

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
                1 for state in self._runs.values() if self._is_running(state)
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
                if self._is_running(state):
                    return True
            return False

    async def has_active_tasks_excluding(
        self,
        excluded_task: asyncio.Future | None,
    ) -> bool:
        """Check for active tasks other than ``excluded_task``."""
        async with self._lock:
            return any(
                self._is_running(state) and state.task is not excluded_task
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
                if self._is_running(state)
            ]

    async def snapshot_active_tasks(
        self,
        owner: object | None = None,
        channel_id: str | None = None,
    ) -> dict[str, asyncio.Future]:
        """Return the currently active tasks without tracking later runs."""
        async with self._lock:
            tasks = {
                run_key: state.task
                for run_key, state in self._runs.items()
                if self._is_running(state)
                and (owner is None or state.owner is owner)
                and (channel_id is None or state.channel_id == channel_id)
            }
            for identity, writers in self._session_tasks.items():
                if channel_id is not None and identity[2] != channel_id:
                    continue
                for task, task_owner in writers.items():
                    if (
                        not task.done()
                        and task not in tasks.values()
                        and (owner is None or task_owner is owner)
                    ):
                        tasks.setdefault(f"session:{id(task)}", task)
            return tasks

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

    async def attach(self, run_key: str) -> asyncio.Queue | None:
        """Attach to an existing run.

        Returns a new queue pre-filled with the folded replay plus a
        ``replay_end`` marker. A recently completed run also returns its
        terminal replay during the reconnect grace period. Returns ``None``
        after that replay expires.
        """
        async with self._lock:
            state = self._runs.get(run_key)
            if state is None:
                return None
            if not self._is_running(state):
                return self._completed_queue(state)
            return self._attach_queue(state, include_replay_end=True)

    async def attach_materialized(
        self,
        run_key: str,
        *,
        expected_task: asyncio.Future | None = None,
    ) -> tuple[list[str] | ReplayPrefix, asyncio.Queue] | None:
        """Atomically subscribe, then materialize the fixed replay prefix.

        Future events enter a bounded queue while the captured prefix is
        folded off the event loop. The caller must publish the returned
        prefix and ``REPLAY_END_SSE`` before consuming that queue.
        """
        async with self._lock:
            state = self._runs.get(run_key)
            if state is None or (
                expected_task is not None and state.task is not expected_task
            ):
                return None
            if state.replay.requires_resync:
                return [], self._reconnect_queue(
                    unavailable=state.replay.recovery_unavailable,
                )
            durable = state.replay.capture()
            materialized = state.replay.is_materialized
            replay = [] if durable else list(state.replay.replay())
            queue: asyncio.Queue = _SubscriberQueue(
                maxsize=self._subscriber_queue_max,
            )
            queue.run_task = state.task
            if self._is_running(state):
                state.queues.append(queue)
            else:
                queue.put_nowait(_SENTINEL)

        try:
            snapshot: list[str] | ReplayPrefix
            if durable is not None:
                snapshot = durable
            elif materialized:
                snapshot = replay
            else:
                snapshot = await asyncio.to_thread(materialize_replay, replay)
        except BaseException:
            await self.detach_subscriber(run_key, queue)
            raise
        return snapshot, queue

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

    async def request_stop(
        self,
        run_key: str,
        *,
        reason: str = "user",
    ) -> bool:
        """Cancel the run. Returns ``True`` if it was running."""
        logger.debug("[STOP] request_stop called for run_key=%s", run_key)
        async with self._lock:
            state = self._runs.get(run_key)
            logger.debug(
                "[STOP] run_key=%s state=%s done=%s",
                run_key,
                "found" if state else "not_found",
                state.task.done() if state else "N/A",
            )
            if state is None or not self._is_running(state):
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
            task.cancel(reason)
            logger.debug("[STOP] task.cancel() called for run_key=%s", run_key)
        try:
            await task
        except asyncio.CancelledError:
            pass
        return True

    @asynccontextmanager
    async def prevent_new_runs(self, run_keys: list[str]):
        """Exclude run registration while deleting conversations."""
        keys = set(run_keys)
        async with self._lock:
            if keys & self._blocked_runs:
                raise RunUnavailableError("Conversation deletion in progress")
            self._blocked_runs.update(keys)
        try:
            yield
        finally:
            async with self._lock:
                self._blocked_runs.difference_update(keys)

    async def attach_or_start(
        self,
        run_key: str,
        payload: Any,
        stream_fn: Callable[[Any], AsyncIterator[str]],
        owner: object | None = None,
        on_finished: Callable[[str, datetime], Awaitable[Any]] | None = None,
        channel_id: str | None = None,
        can_start: Callable[[], Awaitable[bool]] | None = None,
    ) -> tuple[asyncio.Queue, bool]:
        """Attach to an existing run or start a new one.

        Returns ``(queue, is_new_run)``.
        """
        async with self._lock:
            if run_key in self._blocked_runs or (
                can_start is not None and not await can_start()
            ):
                raise RunUnavailableError(
                    "Conversation was deleted or deletion needs retry",
                )
            state = self._runs.get(run_key)
            if state is not None and self._is_running(state):
                return (
                    self._attach_queue(
                        state,
                        include_replay_end=False,
                    ),
                    False,
                )

            my_queue: asyncio.Queue = _SubscriberQueue(
                maxsize=self._subscriber_queue_max,
            )
            run = _RunState(
                task=asyncio.Future(),  # placeholder, replaced below
                queues=[my_queue],
                owner=owner,
                channel_id=channel_id,
            )

            tracker_ref = weakref.ref(self)

            async def _producer() -> None:
                replay_receipt.set(None)
                start_time = datetime.now(timezone.utc)

                try:
                    tracker = tracker_ref()
                    if tracker is not None:
                        async with tracker.lock:
                            run.start_time = start_time
                            # pylint: disable=protected-access
                            tracker._global_last_run_at = start_time

                    async for sse in stream_fn(payload):
                        tracker = tracker_ref()
                        if tracker is None:
                            return
                        async with tracker.lock:
                            run.replay.append(sse, replay_receipt.get())
                            # pylint: disable-next=protected-access
                            tracker._broadcast(run, sse)
                except asyncio.CancelledError:
                    logger.debug("run cancelled run_key=%s", run_key)
                except Exception:
                    logger.exception("run error run_key=%s", run_key)
                    err_sse = (
                        "data: "
                        f"{json.dumps({'error': 'internal server error'})}\n\n"
                    )
                    tracker = tracker_ref()
                    if tracker is not None:
                        async with tracker.lock:
                            run.replay.append(err_sse)
                            # pylint: disable-next=protected-access
                            tracker._broadcast(run, err_sse)
                finally:
                    finish_time = datetime.now(timezone.utc)
                    if on_finished is not None:
                        try:
                            await on_finished(run_key, finish_time)
                        except Exception:  # pylint: disable=broad-except
                            logger.exception(
                                "run completion callback failed run_key=%s",
                                run_key,
                            )
                    tracker = tracker_ref()
                    if tracker is not None:
                        async with tracker.lock:
                            run.finish_time = finish_time
                            # pylint: disable=protected-access
                            tracker._global_last_finish_at = finish_time
                            tracker._broadcast(run, _SENTINEL)
                            tracker._retain_completed_locked(run_key, run)

            # Register the run only once the producer task exists.
            # Registering a placeholder first would leak a permanent
            # "running" entry -- the status counters inspect the task and
            # finish time, and a bare Future is never done --
            # if task creation ever failed. This is defensive hardening:
            # the window is synchronous and a running loop cannot be
            # closed, so the failure is not reachable in practice.
            run.task = _create_task(_producer())
            my_queue.run_task = run.task
            self._runs[run_key] = run
            return my_queue, True

    async def stream_from_queue(
        self,
        queue: asyncio.Queue,
        run_key: str,
        *,
        cancel_run: bool = False,
        recover_overflow: bool = False,
    ) -> AsyncGenerator[str, None]:
        """Yield SSE strings from *queue* until the sentinel ``None``.

        Always detaches *queue* from *run_key* when this stream ends or is
        closed (including client disconnect), so reconnects do not leak queues.
        Channel queue executions opt into cancelling and joining their exact
        producer; ordinary subscribers leave the run alive on disconnect.
        """

        async def owned_task():
            async with self._lock:
                state = self._runs.get(run_key)
                return (
                    state.task
                    if state is not None and queue in state.queues
                    else None
                )

        producer = None
        try:
            if cancel_run:
                producer = await owned_task()
            while True:
                try:
                    event = await queue.get()
                    if event is _SENTINEL:
                        break
                    if recover_overflow and event == RECONNECT_REQUIRED_SSE:
                        attached = await self.attach_materialized(
                            run_key,
                            expected_task=queue.run_task,
                        )
                        if attached is not None:
                            prefix, replacement = attached
                            if prefix:
                                await self.detach_subscriber(run_key, queue)
                                queue = replacement
                                if isinstance(prefix, ReplayPrefix):
                                    async for item in prefix:
                                        yield item
                                else:
                                    for item in prefix:
                                        yield item
                                yield REPLAY_END_SSE
                                continue
                            await self.detach_subscriber(run_key, replacement)
                    yield event
                except asyncio.CancelledError:
                    if cancel_run:
                        raise
                    break
        finally:
            if cancel_run and asyncio.current_task().cancelling():
                from ..utils.io_utils import run_async_to_completion

                async def stop_and_detach():
                    # Capture may itself have been cancelled waiting on the
                    # lock. The exact subscriber queue excludes later runs
                    # that reuse this key.
                    task = producer or await owned_task()
                    if task is not None:
                        if not task.done() and not task.cancelling():
                            task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
                    await self.detach_subscriber(run_key, queue)

                await run_async_to_completion(stop_and_detach())
            else:
                await self.detach_subscriber(run_key, queue)
