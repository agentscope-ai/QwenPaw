# -*- coding: utf-8 -*-
"""In-process event bridge for background subagent tasks."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Optional


TERMINAL_STATUSES = {"completed", "failed", "cancelled", "timed_out", "stale"}


@dataclass
class SubagentTaskRecord:
    """Parent-child metadata for a background subagent task."""

    task_id: str
    parent_agent_id: str
    parent_session_id: str
    child_agent_id: str
    child_session_id: str
    task: str = ""
    user_id: str = ""
    channel: str = ""
    fork: bool = False
    status: str = "submitted"
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    last_heartbeat_at: Optional[float] = None
    result: Any = None
    error: Optional[str] = None


@dataclass
class SubagentTaskEvent:
    """Event delivered to the parent session."""

    event_id: int
    event_type: str
    task_id: str
    parent_agent_id: str
    parent_session_id: str
    child_agent_id: str
    child_session_id: str
    status: str
    created_at: float
    task: str = ""
    result: Any = None
    error: Optional[str] = None
    elapsed_time: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "task_id": self.task_id,
            "parent_agent_id": self.parent_agent_id,
            "parent_session_id": self.parent_session_id,
            "child_agent_id": self.child_agent_id,
            "child_session_id": self.child_session_id,
            "status": self.status,
            "created_at": self.created_at,
            "task": self.task,
            "result": self.result,
            "error": self.error,
            "elapsed_time": self.elapsed_time,
        }


class SubagentEventRegistry:
    """Small in-memory registry shared by tools and AgentApp task runner.

    AgentApp starts background tasks before the tool response reaches the
    caller, so a very fast task may finish before spawn_subagent can register
    its parent-child relation. Pending terminal results are cached by task_id
    and flushed when the relation is registered.
    """

    def __init__(
        self,
        max_events_per_session: int = 200,
        max_pending_terminal: int = 200,
        max_records: int = 1000,
    ) -> None:
        self._lock = RLock()
        self._records: dict[str, SubagentTaskRecord] = {}
        self._events_by_parent: dict[str, list[SubagentTaskEvent]] = {}
        self._pending_terminal: dict[str, dict[str, Any]] = {}
        self._event_id = 0
        self._max_events_per_session = max(10, max_events_per_session)
        self._max_pending_terminal = max(10, max_pending_terminal)
        self._max_records = max(10, max_records)

    def register_task(self, record: SubagentTaskRecord) -> None:
        pending: Optional[dict[str, Any]]
        with self._lock:
            self._records[record.task_id] = record
            self._prune_records_locked()
            pending = self._pending_terminal.pop(record.task_id, None)
        self.publish_event(record.task_id, "subagent.started", "running")
        if pending:
            self.publish_terminal(
                record.task_id,
                status=pending["status"],
                result=pending.get("result"),
                error=pending.get("error"),
                elapsed_time=pending.get("elapsed_time"),
            )

    def publish_terminal(
        self,
        task_id: str,
        *,
        status: str,
        result: Any = None,
        error: Optional[str] = None,
        elapsed_time: Optional[float] = None,
    ) -> None:
        event_type = f"subagent.{status}"
        with self._lock:
            record = self._records.get(task_id)
            if record is None:
                self._pending_terminal[task_id] = {
                    "status": status,
                    "result": result,
                    "error": error,
                    "elapsed_time": elapsed_time,
                    "created_at": time.time(),
                }
                if len(self._pending_terminal) > self._max_pending_terminal:
                    oldest = min(
                        self._pending_terminal,
                        key=lambda tid: self._pending_terminal[tid].get(
                            "created_at",
                            0,
                        ),
                    )
                    self._pending_terminal.pop(oldest, None)
                return
            record.status = status
            record.finished_at = time.time()
            record.result = result
            record.error = error
            self._prune_records_locked()
        self.publish_event(
            task_id,
            event_type,
            status,
            result=result,
            error=error,
            elapsed_time=elapsed_time,
        )

    def publish_event(
        self,
        task_id: str,
        event_type: str,
        status: str,
        *,
        result: Any = None,
        error: Optional[str] = None,
        elapsed_time: Optional[float] = None,
    ) -> Optional[SubagentTaskEvent]:
        with self._lock:
            record = self._records.get(task_id)
            if record is None:
                return None
            if status == "running" and record.started_at is None:
                record.started_at = time.time()
            record.status = status
            if status == "running":
                record.last_heartbeat_at = time.time()

            self._event_id += 1
            event = SubagentTaskEvent(
                event_id=self._event_id,
                event_type=event_type,
                task_id=task_id,
                parent_agent_id=record.parent_agent_id,
                parent_session_id=record.parent_session_id,
                child_agent_id=record.child_agent_id,
                child_session_id=record.child_session_id,
                status=status,
                created_at=time.time(),
                task=record.task,
                result=result,
                error=error,
                elapsed_time=elapsed_time,
            )
            events = self._events_by_parent.setdefault(
                record.parent_session_id,
                [],
            )
            events.append(event)
            if len(events) > self._max_events_per_session:
                del events[: len(events) - self._max_events_per_session]
            return event

    def _prune_records_locked(self) -> None:
        """Keep terminal task metadata bounded without dropping live tasks."""
        overflow = len(self._records) - self._max_records
        if overflow <= 0:
            return
        terminal_records = [
            record
            for record in self._records.values()
            if record.status in TERMINAL_STATUSES
        ]
        terminal_records.sort(
            key=lambda record: record.finished_at or record.created_at,
        )
        for record in terminal_records[:overflow]:
            self._records.pop(record.task_id, None)

    def drain_events(
        self,
        parent_session_id: str,
        *,
        task_ids: Optional[set[str]] = None,
        terminal_only: bool = False,
    ) -> list[SubagentTaskEvent]:
        with self._lock:
            events = self._events_by_parent.get(parent_session_id, [])
            if not events:
                return []
            matched: list[SubagentTaskEvent] = []
            remaining: list[SubagentTaskEvent] = []
            for event in events:
                if task_ids and event.task_id not in task_ids:
                    remaining.append(event)
                    continue
                if terminal_only and event.status not in TERMINAL_STATUSES:
                    remaining.append(event)
                    continue
                matched.append(event)
            self._events_by_parent[parent_session_id] = remaining
            return matched

    def get_records_for_parent(
        self,
        parent_session_id: str,
    ) -> list[SubagentTaskRecord]:
        with self._lock:
            return [
                record
                for record in self._records.values()
                if record.parent_session_id == parent_session_id
            ]

    def linked_running_task_ids(self, parent_session_id: str) -> list[str]:
        with self._lock:
            return [
                record.task_id
                for record in self._records.values()
                if record.parent_session_id == parent_session_id
                and record.status in {"submitted", "running"}
            ]

    def linked_running_count(self, parent_session_id: str) -> int:
        return len(self.linked_running_task_ids(parent_session_id))

    def mark_stale_tasks(self, stale_after: float) -> list[SubagentTaskEvent]:
        """Mark quiet running tasks as stale and publish terminal events."""
        now = time.time()
        stale_task_ids: list[str] = []
        with self._lock:
            for task_id, record in self._records.items():
                if record.status not in {"submitted", "running"}:
                    continue
                last_seen = (
                    record.last_heartbeat_at
                    or record.started_at
                    or record.created_at
                )
                if now - last_seen >= stale_after:
                    stale_task_ids.append(task_id)

        events: list[SubagentTaskEvent] = []
        for task_id in stale_task_ids:
            self.publish_terminal(
                task_id,
                status="stale",
                error=(
                    "Background subagent produced no heartbeat for "
                    f"{int(stale_after)}s"
                ),
            )
            with self._lock:
                parent = self._records.get(task_id)
                if parent:
                    session_events = self._events_by_parent.get(
                        parent.parent_session_id,
                        [],
                    )
                    if session_events:
                        events.append(session_events[-1])
        return events


_REGISTRY = SubagentEventRegistry()


def get_subagent_event_registry() -> SubagentEventRegistry:
    return _REGISTRY
