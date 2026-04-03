# -*- coding: utf-8 -*-
"""Task tracker for background runs: streaming, reconnect, multi-subscriber.

run_key is ChatSpec.id (chat_id). Per run: task, queues, event buffer.
Reconnects get buffer replay + new events. Cleanup when task completes.
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import weakref
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Callable, Coroutine

logger = logging.getLogger(__name__)

_SENTINEL = None


@dataclass
class _RunState:
    """Per-run state (task, queues, buffer), guarded by tracker lock."""

    task: asyncio.Future
    queues: list[asyncio.Queue] = field(default_factory=list)
    buffer: list[str] = field(default_factory=list)
    runtime_messages: list[Any] = field(default_factory=list)
    managed_by_runner: bool = False


class TaskTracker:
    """Per-workspace tracker: run_key -> RunState.

    All mutations to _runs under _lock. Producer broadcasts under lock.
    Subscribers use unbounded per-connection queues; disconnect removes them
    via :meth:`detach_subscriber`.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._runs: dict[str, _RunState] = {}

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

    async def attach(self, run_key: str) -> asyncio.Queue | None:
        """Attach to an existing run.

        Returns a new queue pre-filled with the event buffer, or ``None``
        if no run is active for *run_key*.
        """
        async with self._lock:
            state = self._runs.get(run_key)
            if state is None or state.task.done():
                return None
            q: asyncio.Queue = asyncio.Queue()
            for sse in state.buffer:
                q.put_nowait(sse)
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

    async def request_stop(self, run_key: str) -> bool:
        """Cancel the run. Returns ``True`` if it was running."""
        async with self._lock:
            state = self._runs.get(run_key)
            if state is None or state.task.done():
                return False
            state.task.cancel()
            return True

    async def ensure_runtime_run(self, run_key: str) -> bool:
        """Register a runner-owned active run when no tracker run exists."""
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("ensure_runtime_run must run inside a task")

        async with self._lock:
            state = self._runs.get(run_key)
            if state is not None and not state.task.done():
                return False
            self._runs[run_key] = _RunState(
                task=task,
                managed_by_runner=True,
            )
            return True

    async def update_runtime_messages(
        self,
        run_key: str,
        messages: list[Any],
    ) -> bool:
        """Store a structured runtime snapshot for an active run."""
        async with self._lock:
            state = self._runs.get(run_key)
            if state is None or state.task.done():
                return False
            state.runtime_messages = copy.deepcopy(messages)
            return True

    async def get_runtime_messages(
        self,
        run_key: str,
    ) -> list[Any] | None:
        """Return a copy of the structured runtime snapshot, if any."""
        async with self._lock:
            state = self._runs.get(run_key)
            if state is None or state.task.done():
                return None
            if not state.runtime_messages:
                return None
            return copy.deepcopy(state.runtime_messages)

    async def finish_runtime_run(self, run_key: str) -> None:
        """Remove a runner-owned active run when the handler exits."""
        task = asyncio.current_task()
        async with self._lock:
            state = self._runs.get(run_key)
            if state is None or not state.managed_by_runner:
                return
            if (
                task is not None
                and state.task is not task
                and not state.task.done()
            ):
                return
            self._runs.pop(run_key, None)

    async def attach_or_start(
        self,
        run_key: str,
        payload: Any,
        stream_fn: Callable[..., Coroutine],
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
                managed_by_runner=False,
            )
            self._runs[run_key] = run

            tracker_ref = weakref.ref(self)

            async def _producer() -> None:
                try:
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
                    tracker = tracker_ref()
                    if tracker is not None:
                        async with tracker.lock:
                            for q in run.queues:
                                q.put_nowait(_SENTINEL)
                            # pylint: disable=protected-access
                            tracker._runs.pop(
                                run_key,
                                None,
                            )

            run.task = asyncio.create_task(_producer())
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
