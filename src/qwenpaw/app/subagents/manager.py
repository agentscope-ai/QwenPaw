# -*- coding: utf-8 -*-
"""Workspace-scoped background subagent task manager.

The design follows AgentScope 2.0's background-tool lifecycle: keep the
asyncio task handle locally, publish lifecycle events into a parent-session
inbox, then enqueue an idle-session wakeup.  QwenPaw supplies its own inbox and
wakeup bridge because it does not run the ``agentscope.app`` service stack.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import uuid4

from ...runtime.heartbeat import HEARTBEAT_INTERVAL_SECONDS

logger = logging.getLogger(__name__)

DEFAULT_HEARTBEAT_TIMEOUT_SECONDS = HEARTBEAT_INTERVAL_SECONDS * 4
DEFAULT_WATCHDOG_INTERVAL_SECONDS = HEARTBEAT_INTERVAL_SECONDS
DEFAULT_CANCEL_GRACE_SECONDS = 10.0
DEFAULT_PARENT_WAKEUP_WAIT_TIMEOUT_SECONDS = 300.0
DEFAULT_PARENT_WAKEUP_RETRY_INTERVAL_SECONDS = 5.0


class SubagentStatus(str, Enum):
    """Stable lifecycle states exposed to tools, logs, and tests."""

    SUBMITTED = "submitted"
    RUNNING = "running"
    CANCELLING = "cancelling"
    STALE = "stale"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = frozenset(
    {
        SubagentStatus.COMPLETED,
        SubagentStatus.FAILED,
        SubagentStatus.CANCELLED,
    },
)


@dataclass
class SubagentTaskRecord:
    """Runtime metadata plus the local task handle."""

    task_id: str
    parent_agent_id: str
    parent_session_id: str
    root_session_id: str
    child_agent_id: str
    child_session_id: str
    prompt: str
    user_id: str
    channel: str
    channel_meta: dict[str, Any] = field(default_factory=dict)
    status: SubagentStatus = SubagentStatus.SUBMITTED
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    last_heartbeat_at: float = 0.0
    cancel_requested_at: float | None = None
    stale_notified: bool = False
    result: str | None = None
    error: str | None = None
    cancel_reason: str | None = None
    notify_on_cancel: bool = True
    worktree_branch: str = ""
    asyncio_task: asyncio.Task | None = field(
        default=None,
        repr=False,
        compare=False,
    )


@dataclass
class SubagentLifecycleEvent:
    """A child lifecycle event waiting to be injected into its parent."""

    event_id: str
    task_id: str
    parent_session_id: str
    child_session_id: str
    status: SubagentStatus
    prompt: str
    created_at: float = field(default_factory=time.time)
    result: str | None = None
    error: str | None = None
    elapsed_seconds: float | None = None
    worktree_branch: str = ""
    claim_id: str | None = None


class SubagentTaskManager:
    """AS2-style lifecycle adapter for leaf subagents in one Workspace.

    This is intentionally not a generic background-task framework.  It only
    adds parent/child identity and child Runtime execution around the same
    inbox, HintBlock, wakeup, and cancellation semantics used by AS2.
    """

    def __init__(
        self,
        workspace: Any,
        *,
        max_running_per_parent: int = 8,
        heartbeat_timeout_seconds: float = DEFAULT_HEARTBEAT_TIMEOUT_SECONDS,
        watchdog_interval_seconds: float = DEFAULT_WATCHDOG_INTERVAL_SECONDS,
        cancel_grace_seconds: float = DEFAULT_CANCEL_GRACE_SECONDS,
        parent_wakeup_wait_timeout_seconds: float = (
            DEFAULT_PARENT_WAKEUP_WAIT_TIMEOUT_SECONDS
        ),
        parent_wakeup_retry_interval_seconds: float = (
            DEFAULT_PARENT_WAKEUP_RETRY_INTERVAL_SECONDS
        ),
    ) -> None:
        self.workspace = workspace
        self.max_running_per_parent = max_running_per_parent
        self.heartbeat_timeout_seconds = max(
            float(heartbeat_timeout_seconds),
            0.01,
        )
        self.watchdog_interval_seconds = max(
            float(watchdog_interval_seconds),
            0.01,
        )
        self.cancel_grace_seconds = max(float(cancel_grace_seconds), 0.0)
        self.parent_wakeup_wait_timeout_seconds = max(
            float(parent_wakeup_wait_timeout_seconds),
            0.0,
        )
        self.parent_wakeup_retry_interval_seconds = max(
            float(parent_wakeup_retry_interval_seconds),
            0.01,
        )
        self._records: dict[str, SubagentTaskRecord] = {}
        self._events: list[SubagentLifecycleEvent] = []
        self._lock = asyncio.Lock()
        self._watchdog_task: asyncio.Task | None = None
        self._notification_tasks: set[asyncio.Task] = set()
        self._wakeup_retry_parents: set[str] = set()
        self._stopping = False

    async def start(self) -> None:
        """Start one workspace-wide heartbeat watchdog."""
        if self._watchdog_task is not None and not self._watchdog_task.done():
            return
        self._stopping = False
        self._watchdog_task = asyncio.create_task(
            self._watchdog_loop(),
            name="qwenpaw-subagent-watchdog",
        )

    async def stop(self) -> None:
        """Cancel live children without waking parents during shutdown."""
        self._stopping = True
        watchdog = self._watchdog_task
        self._watchdog_task = None
        if watchdog is not None and not watchdog.done():
            watchdog.cancel()
            await asyncio.gather(watchdog, return_exceptions=True)

        async with self._lock:
            tasks = []
            for record in self._records.values():
                task = record.asyncio_task
                if task is not None and not task.done():
                    record.cancel_reason = "workspace shutdown"
                    record.notify_on_cancel = False
                    tasks.append(task)
                    task.cancel()
            notifications = list(self._notification_tasks)
            for task in notifications:
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if notifications:
            await asyncio.gather(*notifications, return_exceptions=True)

    async def spawn(
        self,
        *,
        prompt: str,
        parent_agent_id: str,
        parent_session_id: str,
        root_session_id: str,
        child_agent_id: str,
        child_session_id: str,
        user_id: str,
        channel: str,
        channel_meta: dict[str, Any] | None,
        parent_is_subagent: bool,
        request_context: dict[str, Any] | None = None,
        worktree_branch: str = "",
    ) -> SubagentTaskRecord:
        """Create, register, and start one child Runtime task."""
        if parent_is_subagent:
            raise ValueError(
                "nested subagents are not supported; only a top-level "
                "agent may call spawn_subagent",
            )

        async with self._lock:
            running = sum(
                1
                for item in self._records.values()
                if item.parent_session_id == parent_session_id
                and item.status not in TERMINAL_STATUSES
            )
            if running >= self.max_running_per_parent:
                raise RuntimeError(
                    "background subagent limit reached for this parent "
                    f"({running}/{self.max_running_per_parent})",
                )

            task_id = f"subtask-{uuid4().hex[:12]}"
            record = SubagentTaskRecord(
                task_id=task_id,
                parent_agent_id=parent_agent_id,
                parent_session_id=parent_session_id,
                root_session_id=root_session_id or parent_session_id,
                child_agent_id=child_agent_id,
                child_session_id=child_session_id,
                prompt=prompt,
                user_id=user_id,
                channel=channel or "console",
                channel_meta=self._routing_meta(channel_meta or {}),
                last_heartbeat_at=time.monotonic(),
                worktree_branch=worktree_branch,
            )
            self._records[task_id] = record

            child_context = dict(request_context or {})
            child_context.update(
                {
                    "is_subagent": True,
                    "subagent_task_id": task_id,
                    "subagent_parent_session_id": parent_session_id,
                },
            )
            record.asyncio_task = asyncio.create_task(
                self._run_child(record, child_context),
                name=f"qwenpaw-subagent:{task_id}",
            )

            def _done_callback(done: asyncio.Task) -> None:
                self._on_task_done(record, done)

            record.asyncio_task.add_done_callback(_done_callback)
            return record

    def _on_task_done(
        self,
        record: SubagentTaskRecord,
        task: asyncio.Task,
    ) -> None:
        """Close the pre-start cancellation gap in asyncio task execution."""
        if record.status in TERMINAL_STATUSES:
            return
        try:
            asyncio.create_task(self._ensure_done_state(record, task))
        except RuntimeError:
            # Event loop is already closed during interpreter shutdown.
            return

    async def _ensure_done_state(
        self,
        record: SubagentTaskRecord,
        task: asyncio.Task,
    ) -> None:
        if record.status in TERMINAL_STATUSES:
            return
        if task.cancelled():
            await self._finish(
                record,
                SubagentStatus.CANCELLED,
                error=record.cancel_reason or "subagent task was cancelled",
                notify_parent=record.notify_on_cancel,
            )
            return
        exc = task.exception()
        if exc is not None:
            await self._finish(
                record,
                SubagentStatus.FAILED,
                error=str(exc) or type(exc).__name__,
            )
            return
        await self._finish(
            record,
            SubagentStatus.FAILED,
            error="subagent task exited without a terminal lifecycle state",
        )

    async def _run_child(
        self,
        record: SubagentTaskRecord,
        request_context: dict[str, Any],
    ) -> None:
        try:
            async with self._lock:
                record.status = SubagentStatus.RUNNING
                record.started_at = time.time()
                record.last_heartbeat_at = time.monotonic()

            request = self._build_child_request(record, request_context)
            final_text = ""
            async for item in self.workspace.stream_query(request):
                # AgentExecutor already emits heartbeat envelopes while
                # the AS2 event stream is idle. Reuse that established
                # mechanism instead of creating another timer task.
                await self.touch(record.task_id)
                text = self._completed_assistant_text(item)
                if text:
                    final_text = text

            await self._finish(
                record,
                SubagentStatus.COMPLETED,
                result=final_text
                or "(Subagent completed with no text output)",
            )
        except asyncio.CancelledError:
            reason = record.cancel_reason or "subagent task was cancelled"
            await self._finish(
                record,
                SubagentStatus.CANCELLED,
                error=reason,
                notify_parent=record.notify_on_cancel,
            )
            raise
        except BaseException as exc:  # noqa: BLE001
            logger.exception("Background subagent %s failed", record.task_id)
            await self._finish(
                record,
                SubagentStatus.FAILED,
                error=str(exc) or type(exc).__name__,
            )

    async def _finish(
        self,
        record: SubagentTaskRecord,
        status: SubagentStatus,
        *,
        result: str | None = None,
        error: str | None = None,
        notify_parent: bool = True,
    ) -> None:
        async with self._lock:
            if record.status in TERMINAL_STATUSES:
                return
            should_notify = notify_parent and record.notify_on_cancel
            record.status = status
            record.finished_at = time.time()
            record.result = result
            record.error = error
            if should_notify:
                self._append_lifecycle_event_locked(record)
            else:
                self._records.pop(record.task_id, None)
        if should_notify:
            await self._enqueue_parent_wakeup(record)

    async def touch(
        self,
        task_id: str,
    ) -> None:
        """Record one liveness pulse from the child Runtime stream."""
        async with self._lock:
            record = self._records.get(task_id)
            if record is None or record.status not in {
                SubagentStatus.SUBMITTED,
                SubagentStatus.RUNNING,
            }:
                return
            record.last_heartbeat_at = time.monotonic()

    async def cancel_task(
        self,
        task_id: str,
        *,
        reason: str = "cancelled by parent",
        notify_parent: bool = True,
    ) -> bool:
        """Cancel one task by id.  Idempotent for terminal/unknown tasks."""
        async with self._lock:
            record = self._records.get(task_id)
            if record is None or record.status in TERMINAL_STATUSES:
                return False
            record.cancel_reason = reason
            record.notify_on_cancel = notify_parent
            task = record.asyncio_task
            if task is None or task.done():
                return False
            if record.status == SubagentStatus.CANCELLING:
                return False
            if record.status == SubagentStatus.STALE:
                task.cancel()
                return True
            record.status = SubagentStatus.CANCELLING
            record.cancel_requested_at = time.monotonic()
            task.cancel()
            return True

    async def cancel_by_parent(
        self,
        parent_session_id: str,
        *,
        reason: str = "parent session cancelled",
    ) -> int:
        """Silently cancel all children and discard pending callbacks."""
        async with self._lock:
            discarded_task_ids = {
                event.task_id
                for event in self._events
                if event.parent_session_id == parent_session_id
            }
            self._events = [
                event
                for event in self._events
                if event.parent_session_id != parent_session_id
            ]
            for task_id in discarded_task_ids:
                record = self._records.get(task_id)
                if record is not None and record.status in TERMINAL_STATUSES:
                    self._records.pop(task_id, None)

            tasks = [
                record
                for record in self._records.values()
                if record.parent_session_id == parent_session_id
                and record.status not in TERMINAL_STATUSES
            ]
            cancelled = 0
            for record in tasks:
                task = record.asyncio_task
                if task is None or task.done():
                    continue
                record.cancel_reason = reason
                record.notify_on_cancel = False
                if record.status == SubagentStatus.CANCELLING:
                    continue
                if record.status != SubagentStatus.STALE:
                    record.status = SubagentStatus.CANCELLING
                    record.cancel_requested_at = time.monotonic()
                task.cancel()
                cancelled += 1
            return cancelled

    async def _watchdog_loop(self) -> None:
        """Cancel children whose Runtime heartbeat stream has stopped."""
        previous_tick = time.monotonic()
        while True:
            try:
                await asyncio.sleep(self.watchdog_interval_seconds)
                now = time.monotonic()
                tick_delay = now - previous_tick
                previous_tick = now

                # If this watchdog was delayed too, the whole event loop was
                # paused. Give every child a fresh lease instead of killing
                # healthy work after suspend, debugger pause, or starvation.
                if tick_delay > self.watchdog_interval_seconds * 2:
                    await self._reset_leases_after_loop_pause(now)
                    continue

                stale_records = await self._watchdog_tick(now)
                for record in stale_records:
                    self._schedule_parent_wakeup(record)
            except Exception:  # pragma: no cover - defensive service boundary
                logger.exception(
                    "Subagent watchdog tick failed; will retry next interval",
                )

    async def _reset_leases_after_loop_pause(self, now: float) -> None:
        async with self._lock:
            for record in self._records.values():
                if record.status in {
                    SubagentStatus.SUBMITTED,
                    SubagentStatus.RUNNING,
                }:
                    record.last_heartbeat_at = now
                elif record.status == SubagentStatus.CANCELLING:
                    record.cancel_requested_at = now

    async def _watchdog_tick(
        self,
        now: float,
    ) -> list[SubagentTaskRecord]:
        """Apply heartbeat leases and return newly stale records."""
        newly_stale: list[SubagentTaskRecord] = []
        async with self._lock:
            for record in self._records.values():
                task = record.asyncio_task
                if task is None or task.done():
                    continue

                if record.status in {
                    SubagentStatus.SUBMITTED,
                    SubagentStatus.RUNNING,
                }:
                    heartbeat_age = now - record.last_heartbeat_at
                    if heartbeat_age < self.heartbeat_timeout_seconds:
                        continue
                    record.status = SubagentStatus.CANCELLING
                    record.cancel_reason = (
                        f"subagent heartbeat lost for {heartbeat_age:.1f}s"
                    )
                    record.notify_on_cancel = True
                    record.cancel_requested_at = now
                    task.cancel()
                    continue

                if record.status != SubagentStatus.CANCELLING:
                    continue
                requested_at = record.cancel_requested_at
                if requested_at is None:
                    record.cancel_requested_at = now
                    continue
                if now - requested_at < self.cancel_grace_seconds:
                    continue
                if record.stale_notified:
                    continue

                record.status = SubagentStatus.STALE
                record.stale_notified = True
                record.error = (
                    f"{record.cancel_reason or 'subagent cancellation'}; "
                    "cancellation did not complete within "
                    f"{self.cancel_grace_seconds:g}s"
                )
                if record.notify_on_cancel:
                    self._append_lifecycle_event_locked(record)
                    newly_stale.append(record)
        return newly_stale

    def _schedule_parent_wakeup(self, record: SubagentTaskRecord) -> None:
        """Schedule a non-blocking wakeup without stalling the watchdog."""
        if self._stopping:
            return
        task = asyncio.create_task(
            self._enqueue_parent_wakeup(record),
            name=f"qwenpaw-subagent-wakeup:{record.task_id}",
        )
        self._notification_tasks.add(task)
        task.add_done_callback(self._notification_tasks.discard)

    def _schedule_parent_wakeup_retry(
        self,
        record: SubagentTaskRecord,
    ) -> None:
        """Retry an automatic parent wakeup without a tight idle poll loop."""
        if self._stopping:
            return
        parent_session_id = record.parent_session_id
        if parent_session_id in self._wakeup_retry_parents:
            return
        self._wakeup_retry_parents.add(parent_session_id)
        task = asyncio.create_task(
            self._retry_parent_wakeup_when_idle(record),
            name=f"qwenpaw-subagent-wakeup-retry:{parent_session_id}",
        )
        self._notification_tasks.add(task)

        def _done(done: asyncio.Task) -> None:
            self._notification_tasks.discard(done)
            self._wakeup_retry_parents.discard(parent_session_id)

        task.add_done_callback(_done)

    async def _retry_parent_wakeup_when_idle(
        self,
        record: SubagentTaskRecord,
    ) -> None:
        """Retry wakeup delivery at low frequency until the parent is idle."""
        while not self._stopping:
            await asyncio.sleep(self.parent_wakeup_retry_interval_seconds)
            if not await self.has_pending_events(record.parent_session_id):
                return
            if await self._parent_session_is_running(record):
                continue
            manager = getattr(self.workspace, "channel_manager", None)
            if manager is None or not record.channel:
                logger.warning(
                    "Cannot wake parent for subagent %s: channel unavailable",
                    record.task_id,
                )
                return
            if await self.has_pending_events(record.parent_session_id):
                self._enqueue_parent_request(record, manager)
            return

    async def get(self, task_id: str) -> SubagentTaskRecord | None:
        async with self._lock:
            return self._records.get(task_id)

    async def has_pending_events(self, parent_session_id: str) -> bool:
        async with self._lock:
            return any(
                event.parent_session_id == parent_session_id
                for event in self._events
            )

    async def claim_events(
        self,
        parent_session_id: str,
        claim_id: str,
    ) -> list[SubagentLifecycleEvent]:
        """Lease all currently available events to one parent run."""
        async with self._lock:
            events = [
                event
                for event in self._events
                if event.parent_session_id == parent_session_id
                and event.claim_id is None
            ]
            for event in events:
                event.claim_id = claim_id
            return events

    async def ack_events(self, claim_id: str) -> int:
        """Commit a delivery after the parent session state was saved."""
        async with self._lock:
            acknowledged = [
                event for event in self._events if event.claim_id == claim_id
            ]
            if not acknowledged:
                return 0
            acknowledged_ids = {event.event_id for event in acknowledged}
            self._events = [
                event
                for event in self._events
                if event.event_id not in acknowledged_ids
            ]
            for event in acknowledged:
                record = self._records.get(event.task_id)
                if (
                    event.status in TERMINAL_STATUSES
                    and record is not None
                    and record.status in TERMINAL_STATUSES
                ):
                    self._records.pop(event.task_id, None)
            return len(acknowledged)

    async def release_events(self, claim_id: str) -> int:
        """Release an uncommitted delivery for a later user/wakeup run."""
        count = 0
        async with self._lock:
            for event in self._events:
                if event.claim_id != claim_id:
                    continue
                event.claim_id = None
                count += 1
        return count

    async def drain_events(
        self,
        parent_session_id: str,
    ) -> list[SubagentLifecycleEvent]:
        """Compatibility helper for non-runtime consumers and tests."""
        claim_id = f"drain-{uuid4().hex}"
        events = await self.claim_events(parent_session_id, claim_id)
        await self.ack_events(claim_id)
        return events

    def _append_lifecycle_event_locked(
        self,
        record: SubagentTaskRecord,
    ) -> None:
        elapsed = None
        if record.started_at is not None and record.finished_at is not None:
            elapsed = max(0.0, record.finished_at - record.started_at)
        self._events.append(
            SubagentLifecycleEvent(
                event_id=f"subevent-{uuid4().hex[:12]}",
                task_id=record.task_id,
                parent_session_id=record.parent_session_id,
                child_session_id=record.child_session_id,
                status=record.status,
                prompt=record.prompt,
                result=record.result,
                error=record.error,
                elapsed_seconds=elapsed,
                worktree_branch=record.worktree_branch,
            ),
        )

    async def _enqueue_parent_wakeup(
        self,
        record: SubagentTaskRecord,
    ) -> None:
        """Wake the parent only after its current run becomes idle.

        Channel queues serialize ordinary chat traffic, but Console HTTP can
        drive TaskTracker directly.  Waiting here prevents two Runtime
        instances from loading and saving the same parent session at once.
        """
        manager = getattr(self.workspace, "channel_manager", None)
        if manager is None or not record.channel:
            logger.warning(
                "Cannot wake parent for subagent %s: channel unavailable",
                record.task_id,
            )
            return
        try:
            chat_manager = getattr(self.workspace, "chat_manager", None)
            tracker = getattr(self.workspace, "task_tracker", None)
            chat_id = None
            if chat_manager is not None:
                chat_id = await chat_manager.get_chat_id_by_session(
                    record.parent_session_id,
                    record.channel,
                )
            deadline = (
                time.monotonic() + self.parent_wakeup_wait_timeout_seconds
            )
            while chat_id and tracker is not None:
                if time.monotonic() > deadline:
                    logger.warning(
                        "Timed out waiting for parent session %s to become "
                        "idle; retrying wakeup when the parent becomes idle",
                        record.parent_session_id,
                    )
                    self._schedule_parent_wakeup_retry(record)
                    return
                if await tracker.get_status(chat_id) != "running":
                    break
                # The active parent may consume the HintBlock on its next
                # reasoning step.  If so, no follow-up wake is necessary.
                if not await self.has_pending_events(
                    record.parent_session_id,
                ):
                    return
                await asyncio.sleep(0.1)

            if not await self.has_pending_events(record.parent_session_id):
                return
            self._enqueue_parent_request(record, manager)
        except Exception:
            logger.exception(
                "Failed to enqueue parent wakeup for %s",
                record.task_id,
            )

    @staticmethod
    def _enqueue_parent_request(
        record: SubagentTaskRecord,
        manager: Any,
    ) -> None:
        from ...schemas import AgentRequest

        request = AgentRequest(
            input=[],
            session_id=record.parent_session_id,
            user_id=record.user_id or record.parent_session_id,
            channel=record.channel,
            root_session_id=record.root_session_id,
            root_agent_id=record.parent_agent_id,
            request_context={
                "subagent_wakeup": True,
                "subagent_event_task_id": record.task_id,
            },
        )
        request.channel_meta = dict(record.channel_meta)
        manager.enqueue(record.channel, request)

    async def _parent_session_is_running(
        self,
        record: SubagentTaskRecord,
    ) -> bool:
        chat_manager = getattr(self.workspace, "chat_manager", None)
        tracker = getattr(self.workspace, "task_tracker", None)
        if chat_manager is None or tracker is None:
            return False
        chat_id = await chat_manager.get_chat_id_by_session(
            record.parent_session_id,
            record.channel,
        )
        if not chat_id:
            return False
        return await tracker.get_status(chat_id) == "running"

    @staticmethod
    def _build_child_request(
        record: SubagentTaskRecord,
        request_context: dict[str, Any],
    ) -> Any:
        from ...schemas import (
            AgentRequest,
            ContentType,
            Message,
            MessageType,
            Role,
            TextContent,
        )

        message = Message(
            type=MessageType.MESSAGE,
            role=Role.USER,
            content=[TextContent(type=ContentType.TEXT, text=record.prompt)],
        )
        return AgentRequest(
            input=[message],
            session_id=record.child_session_id,
            user_id=record.user_id or record.parent_agent_id,
            channel=record.channel,
            agent_id=record.child_agent_id,
            root_session_id=record.root_session_id,
            root_agent_id=record.parent_agent_id,
            request_context=request_context,
        )

    @staticmethod
    def _completed_assistant_text(item: Any) -> str:
        role = getattr(item, "role", None)
        status = getattr(item, "status", None)
        if hasattr(role, "value"):
            role = role.value
        if hasattr(status, "value"):
            status = status.value
        if role != "assistant" or status != "completed":
            return ""
        parts = []
        for block in getattr(item, "content", None) or []:
            text = getattr(block, "text", None)
            if isinstance(text, str) and text:
                parts.append(text)
        return "\n".join(parts).strip()

    @staticmethod
    def _routing_meta(value: dict[str, Any]) -> dict[str, Any]:
        """Keep reusable routing values, dropping callbacks and secrets."""
        safe: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = str(key).lower()
            if any(
                sensitive in normalized_key
                for sensitive in (
                    "token",
                    "secret",
                    "password",
                    "webhook",
                    "api_key",
                    "reply_future",
                    "reply_loop",
                    "incoming_message",
                )
            ):
                continue
            if not isinstance(
                item,
                (str, int, float, bool, type(None), list, dict),
            ):
                continue
            safe[str(key)] = item
        return safe


__all__ = [
    "SubagentLifecycleEvent",
    "SubagentStatus",
    "SubagentTaskManager",
    "SubagentTaskRecord",
    "TERMINAL_STATUSES",
]
