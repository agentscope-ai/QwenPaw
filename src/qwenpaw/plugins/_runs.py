# -*- coding: utf-8 -*-
"""Host-owned bounded run index, shared by queries and immutable events."""

from collections import deque
from contextvars import ContextVar
from dataclasses import replace
import time
import uuid

from .runs import RunSnapshot

current_run: ContextVar[str | None] = ContextVar(
    "sdk_current_run",
    default=None,
)


class RunIndex:
    def __init__(self):
        self.snapshots: dict[str, RunSnapshot] = {}
        self.aliases: dict[str, str] = {}
        self.finished: deque[str] = deque()

    def start(self, workspace, request):
        parent = self.snapshots.get(current_run.get())
        identity = {
            "workspace_id": workspace.agent_id,
            "session_id": str(getattr(request, "session_id", "") or ""),
            "user_id": str(getattr(request, "user_id", "") or ""),
            "channel": str(getattr(request, "channel", "") or ""),
        }
        related = parent and all(
            getattr(parent, key) == identity[key]
            for key in ("workspace_id", "user_id", "channel")
        )
        # Request IDs may be client-supplied or reused. Run IDs always belong
        # to the host and cannot overwrite another user's record.
        snapshot = RunSnapshot(
            uuid.uuid4().hex,
            **identity,
            status="running",
            started_at=time.time(),
            parent_run_id=parent.run_id if related else None,
        )
        self.snapshots[snapshot.run_id] = snapshot
        self.aliases[snapshot.run_id] = str(
            getattr(request, "request_id", None) or snapshot.run_id,
        )
        return snapshot

    def finish(self, run_id, status, reason):
        snapshot = replace(
            self.snapshots[run_id],
            status=status,
            reason=reason,
            finished_at=time.time(),
        )
        self.snapshots[run_id] = snapshot
        self.finished.append(run_id)
        while len(self.finished) > 512:
            expired = self.finished.popleft()
            self.snapshots.pop(expired, None)
            self.aliases.pop(expired, None)
        return snapshot


def index(registry=None):
    if registry is None:
        from .registry import PluginRegistry

        registry = PluginRegistry()
    if not hasattr(registry, "_sdk_runs"):
        registry._sdk_runs = RunIndex()
    return registry._sdk_runs


def bind_approval(pending):
    if pending._sdk_run_id is not None or pending.status != "pending":
        return
    snapshot = index().snapshots.get(current_run.get())
    if snapshot and (
        snapshot.workspace_id == pending.agent_id
        and snapshot.session_id == pending.session_id
        and snapshot.user_id == pending.user_id
        and snapshot.channel == pending.channel
    ):
        pending._sdk_run_id = snapshot.run_id
