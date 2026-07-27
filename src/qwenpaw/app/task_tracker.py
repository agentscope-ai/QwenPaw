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
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Callable, Coroutine, Optional

logger = logging.getLogger(__name__)

_SENTINEL = None

# Replay buffer limits per run. Without them the buffer grows without
# bound for long runs with huge tool outputs, and every reconnect
# replays the whole history — causing sustained frontend CPU load.
# When exceeded, oldest events are evicted and reconnecting clients
# receive a ``replay_truncated`` marker first.
MAX_BUFFER_EVENTS = 2000
MAX_BUFFER_BYTES = 8 * 1024 * 1024

# Active subscribers are bounded independently from the replay buffer. A slow
# browser must not retain every live event indefinitely while the producer
# continues. On overflow, the pending tail is replaced with a truncation
# marker and further deltas are suppressed until a terminal event arrives.
# The canonical completed response then brings the client to the final state.
MAX_SUBSCRIBER_EVENTS = 256
MAX_SUBSCRIBER_BYTES = 2 * 1024 * 1024

TRUNCATED_MARKER_SSE = f"data: {json.dumps({'type': 'replay_truncated'})}\n\n"

# Emit an SSE comment frame when no event arrives for this long, so
# proxies between remote clients and the server do not drop the idle
# connection (each drop triggers a reconnect + full buffer replay).
HEARTBEAT_INTERVAL_SECONDS = 15.0
HEARTBEAT_SSE = ": keep-alive\n\n"


class _SubscriberQueue(asyncio.Queue):
    """Queue that tracks the UTF-8 bytes currently waiting for delivery."""

    def __init__(self) -> None:
        # Terminal, usage, and sentinel frames are protected control data.
        super().__init__(maxsize=MAX_SUBSCRIBER_EVENTS + 3)
        self.buffered_bytes = 0
        self.suppress_until_terminal = False
        self.terminal_enqueued = False
        self.turn_usage_enqueued = False

    def put_nowait(self, item: Any) -> None:
        super().put_nowait(item)
        if isinstance(item, str):
            self.buffered_bytes += len(item.encode("utf-8"))

    def get_nowait(self) -> Any:
        item = super().get_nowait()
        if isinstance(item, str):
            self.buffered_bytes -= len(item.encode("utf-8"))
        return item


def _clear_subscriber_queue(queue: _SubscriberQueue) -> None:
    """Discard all events currently waiting in a subscriber queue."""
    while True:
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            return


def _subscriber_put(queue: _SubscriberQueue, sse: str) -> None:
    """Enqueue an event while bounding slow-subscriber work."""
    event_bytes = len(sse.encode("utf-8"))
    event_kind = _subscriber_event_kind(sse)

    if queue.terminal_enqueued:
        if event_kind == "turn_usage" and not queue.turn_usage_enqueued:
            queue.put_nowait(sse)
            queue.turn_usage_enqueued = True
        return

    if queue.suppress_until_terminal:
        if event_kind != "terminal":
            return
        queue.suppress_until_terminal = False
        queue.put_nowait(sse)
        queue.terminal_enqueued = True
        return

    exceeds_limit = (
        queue.qsize() >= MAX_SUBSCRIBER_EVENTS
        or queue.buffered_bytes + event_bytes > MAX_SUBSCRIBER_BYTES
    )
    if exceeds_limit:
        _clear_subscriber_queue(queue)
        queue.put_nowait(TRUNCATED_MARKER_SSE)
        if event_kind != "terminal":
            queue.suppress_until_terminal = True
            return
    queue.put_nowait(sse)
    if event_kind == "terminal":
        queue.terminal_enqueued = True


def _subscriber_event_kind(sse: str) -> str:
    """Classify SSE frames that require subscriber queue protection."""
    stripped = sse.strip()
    if not stripped.startswith("data: "):
        return "normal"
    try:
        payload = json.loads(stripped[6:])
    except (json.JSONDecodeError, TypeError):
        return "normal"
    if not isinstance(payload, dict):
        return "normal"
    if (
        (
            payload.get("object") == "response"
            and payload.get("status") == "completed"
        )
        or payload.get("error")
        or payload.get("type") == "rate_limited"
    ):
        return "terminal"
    if payload.get("type") == "turn_usage":
        return "turn_usage"
    return "normal"


def _subscriber_finish(queue: _SubscriberQueue) -> None:
    """Append the terminator without dropping the newest queued event."""
    queue.put_nowait(_SENTINEL)


@dataclass
class _RunState:
    """Per-run state (task, queues, buffer), guarded by tracker lock."""

    task: asyncio.Future
    queues: list[_SubscriberQueue] = field(default_factory=list)
    buffer: deque[str] = field(default_factory=deque)
    buffer_bytes: int = 0
    truncated: bool = False
    start_time: Optional[datetime] = None
    finish_time: Optional[datetime] = None


def _buffer_append(state: _RunState, sse: str) -> None:
    """Append *sse* to the replay buffer, evicting oldest on overflow.

    Caller must hold the tracker lock. Sizes are accounted in encoded
    UTF-8 bytes (``len(str)`` counts code points and undercounts
    multi-byte content such as CJK text). Sets ``truncated`` once any
    event has been evicted so reconnects can signal the client.
    """
    state.buffer.append(sse)
    state.buffer_bytes += len(sse.encode("utf-8"))
    while state.buffer and (
        len(state.buffer) > MAX_BUFFER_EVENTS
        or state.buffer_bytes > MAX_BUFFER_BYTES
    ):
        evicted = state.buffer.popleft()
        state.buffer_bytes -= len(evicted.encode("utf-8"))
        state.truncated = True


class TaskTracker:
    """Per-workspace tracker: run_key -> RunState.

    All mutations to _runs under _lock. Producer broadcasts under lock.
    Subscribers use bounded per-connection queues; disconnect removes them via
    :meth:`detach_subscriber`.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._runs: dict[str, _RunState] = {}
        self._global_last_run_at: Optional[datetime] = None
        self._global_last_finish_at: Optional[datetime] = None

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

    @staticmethod
    def _subscribe_with_replay(state: _RunState) -> _SubscriberQueue:
        """Create a subscriber queue pre-filled with the replay buffer.

        Prepends the truncated marker when eviction has occurred so the
        client knows early events are missing. Caller must hold the
        tracker lock.
        """
        q = _SubscriberQueue()
        if state.truncated:
            _subscriber_put(q, TRUNCATED_MARKER_SSE)
        for sse in state.buffer:
            _subscriber_put(q, sse)
        state.queues.append(q)
        return q

    async def attach(self, run_key: str) -> _SubscriberQueue | None:
        """Attach to an existing run.

        Returns a new queue pre-filled with the event buffer, or ``None``
        if no run is active for *run_key*.
        """
        async with self._lock:
            state = self._runs.get(run_key)
            if state is None or state.task.done():
                return None
            return self._subscribe_with_replay(state)

    async def detach_subscriber(
        self,
        run_key: str,
        queue: _SubscriberQueue,
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

    async def request_stop(self, run_key: str) -> bool:
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
            task.cancel()
            logger.debug("[STOP] task.cancel() called for run_key=%s", run_key)
        try:
            await task
        except asyncio.CancelledError:
            pass
        return True

    async def attach_or_start(
        self,
        run_key: str,
        payload: Any,
        stream_fn: Callable[..., Coroutine],
    ) -> tuple[_SubscriberQueue, bool]:
        """Attach to an existing run or start a new one.

        Returns ``(queue, is_new_run)``.
        """
        async with self._lock:
            state = self._runs.get(run_key)
            if state is not None and not state.task.done():
                return self._subscribe_with_replay(state), False

            my_queue = _SubscriberQueue()
            run = _RunState(
                task=asyncio.Future(),  # placeholder, replaced below
                queues=[my_queue],
            )
            self._runs[run_key] = run

            tracker_ref = weakref.ref(self)

            async def _producer() -> None:
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
                            _buffer_append(run, sse)
                            for q in run.queues:
                                _subscriber_put(q, sse)
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
                            _buffer_append(run, err_sse)
                            for q in run.queues:
                                _subscriber_put(q, err_sse)
                finally:
                    finish_time = datetime.now(timezone.utc)
                    tracker = tracker_ref()
                    if tracker is not None:
                        async with tracker.lock:
                            run.finish_time = finish_time
                            # pylint: disable=protected-access
                            tracker._global_last_finish_at = finish_time
                            for q in run.queues:
                                _subscriber_finish(q)
                            # pylint: disable=protected-access
                            tracker._runs.pop(
                                run_key,
                                None,
                            )

            run.task = asyncio.create_task(_producer())
            return my_queue, True

    async def stream_from_queue(
        self,
        queue: _SubscriberQueue,
        run_key: str,
    ) -> AsyncGenerator[str, None]:
        """Yield SSE strings from *queue* until the sentinel ``None``.

        Emits a comment heartbeat frame when the queue stays empty for
        ``HEARTBEAT_INTERVAL_SECONDS`` so idle connections survive
        proxies on remote access paths.

        Always detaches *queue* from *run_key* when this stream ends or is
        closed (including client disconnect), so reconnects do not leak queues.
        """
        try:
            while True:
                try:
                    try:
                        # Fast path: avoid the per-call Task/timer overhead
                        # of wait_for while the stream is busy; only arm
                        # the heartbeat timeout when the queue is empty.
                        event = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        try:
                            event = await asyncio.wait_for(
                                queue.get(),
                                timeout=HEARTBEAT_INTERVAL_SECONDS,
                            )
                        except asyncio.TimeoutError:
                            yield HEARTBEAT_SSE
                            continue
                    if event is _SENTINEL:
                        break
                    yield event
                except asyncio.CancelledError:
                    break
        finally:
            await self.detach_subscriber(run_key, queue)
