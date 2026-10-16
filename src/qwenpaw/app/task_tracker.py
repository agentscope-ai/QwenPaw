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

logger = logging.getLogger(__name__)

_SENTINEL = None

# Indirection so tests can simulate a failing task creation without
# patching the process-wide ``asyncio`` module.
_create_task = asyncio.create_task

# Emitted to reconnect subscribers right after the buffered events, so
# the client can render the replayed part instantly (no token-by-token
# re-animation) and switch to live streaming afterwards.
REPLAY_END_SSE = f"data: {json.dumps({'type': 'replay_end'})}\n\n"

# Upper bound on the ``on_finished`` completion callback. The callback
# persists a completion marker under ``ChatManager``'s shared lock (held by
# ~24 other methods), so lock contention or a stalled repo would otherwise
# leave the producer task suspended in its ``finally``: the run stays
# registered *and* its task is not done, so every status reader reports
# "running", which blocks workspace reload and makes inbound messages get
# dropped with HTTP 409. The callback is best-effort bookkeeping, so giving
# up on it is better than wedging the run.
#
# The wedge is therefore *bounded* by this value, not eliminated: the run is
# cleaned up in ``_producer``'s ``finally`` only after the callback returns
# or times out, which the ordering below is required to preserve (a
# subscriber must observe the run as running while the callback runs).
# A callback that suppresses cancellation can still outlive the bound, since
# ``wait_for`` waits for the cancelled coroutine to unwind; none of the
# shipped callbacks do that.
ON_FINISHED_TIMEOUT = 30.0


async def _notify_finished(
    on_finished: Callable[[str, datetime], Awaitable[Any]] | None,
    run_key: str,
    finish_time: datetime,
) -> None:
    """Invoke the completion callback, bounded; failures are swallowed.

    An exception or a timeout is logged and swallowed, so cleanup of the
    finished run is never skipped and a slow callback cannot hold the run
    open indefinitely. ``CancelledError`` is deliberately not caught: it is
    a ``BaseException`` and must keep propagating to the caller, whose
    ``finally`` still performs the cleanup.
    """
    if on_finished is None:
        return
    callback = asyncio.ensure_future(on_finished(run_key, finish_time))
    try:
        await asyncio.wait_for(
            asyncio.shield(callback),
            timeout=ON_FINISHED_TIMEOUT,
        )
    except asyncio.TimeoutError:
        # Distinguish "our bound fired" from a TimeoutError the callback
        # raised itself; only the former is a hang on our side.
        if callback.done():
            logger.exception(
                "run completion callback failed run_key=%s",
                run_key,
            )
        else:
            callback.cancel()
            logger.warning(
                "run completion callback timed out after %ss run_key=%s",
                ON_FINISHED_TIMEOUT,
                run_key,
            )
    except asyncio.CancelledError:
        callback.cancel()
        raise
    except Exception:  # pylint: disable=broad-except
        callback.cancel()
        logger.exception(
            "run completion callback failed run_key=%s",
            run_key,
        )


@dataclass
class _RunState:
    """Per-run state (task, queues, buffer), guarded by tracker lock."""

    task: asyncio.Future
    queues: list[asyncio.Queue] = field(default_factory=list)
    buffer: list[str] = field(default_factory=list)
    start_time: Optional[datetime] = None
    finish_time: Optional[datetime] = None
    owner: object | None = None


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

    async def attach(self, run_key: str) -> asyncio.Queue | None:
        """Attach to an existing run.

        Returns a new queue pre-filled with the event buffer plus a
        ``replay_end`` marker, or ``None`` if no run is active for
        *run_key*.
        """
        async with self._lock:
            state = self._runs.get(run_key)
            if state is None or state.task.done():
                return None
            q: asyncio.Queue = asyncio.Queue()
            for sse in state.buffer:
                q.put_nowait(sse)
            q.put_nowait(REPLAY_END_SSE)
            state.queues.append(q)
            return q

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
            task.cancel(reason)
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
        stream_fn: Callable[[Any], AsyncIterator[str]],
        owner: object | None = None,
        on_finished: Callable[[str, datetime], Awaitable[Any]] | None = None,
    ) -> tuple[asyncio.Queue, bool]:
        """Attach to an existing run or start a new one.

        Returns ``(queue, is_new_run)``.
        """
        async with self._lock:
            state = self._runs.get(run_key)
            if state is not None and not state.task.done():
                q: asyncio.Queue = asyncio.Queue()
                for sse in state.buffer:
                    q.put_nowait(sse)
                state.queues.append(q)
                return q, False

            my_queue: asyncio.Queue = asyncio.Queue()
            run = _RunState(
                task=asyncio.Future(),  # placeholder, replaced below
                queues=[my_queue],
                buffer=[],
                owner=owner,
            )

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
                            run.buffer.append(sse)
                            for q in run.queues:
                                q.put_nowait(sse)
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
                            run.buffer.append(err_sse)
                            for q in run.queues:
                                q.put_nowait(err_sse)
                finally:
                    finish_time = datetime.now(timezone.utc)
                    # Cleanup lives in a nested ``finally`` so it still runs
                    # when the producer is cancelled while the completion
                    # callback is in flight: ``CancelledError`` is a
                    # ``BaseException`` and so escapes the ``except
                    # Exception`` guard, which would otherwise leave a
                    # subscriber queue without its end-of-stream sentinel.
                    try:
                        await _notify_finished(
                            on_finished,
                            run_key,
                            finish_time,
                        )
                    finally:
                        tracker = tracker_ref()
                        if tracker is not None:
                            async with tracker.lock:
                                run.finish_time = finish_time
                                # pylint: disable=protected-access
                                tracker._global_last_finish_at = finish_time
                                for q in run.queues:
                                    q.put_nowait(_SENTINEL)
                                # pylint: disable=protected-access
                                tracker._runs.pop(
                                    run_key,
                                    None,
                                )

            # Register the run only once the producer task exists.
            # Registering a placeholder first would leak a permanent
            # "running" entry -- the status counters read
            # ``not state.task.done()``, and a bare Future is never done --
            # if task creation ever failed. This is defensive hardening:
            # the window is synchronous and a running loop cannot be
            # closed, so the failure is not reachable in practice.
            run.task = _create_task(_producer())
            self._runs[run_key] = run
            return my_queue, True

    async def stream_from_queue(
        self,
        queue: asyncio.Queue,
        run_key: str,
    ) -> AsyncGenerator[str, None]:
        """Yield SSE strings from *queue* until the sentinel ``None``.

        Always detaches *queue* from *run_key* when this stream ends or is
        closed (including client disconnect), so reconnects do not leak queues.
        """
        try:
            while True:
                try:
                    event = await queue.get()
                    if event is _SENTINEL:
                        break
                    yield event
                except asyncio.CancelledError:
                    break
        finally:
            await self.detach_subscriber(run_key, queue)
