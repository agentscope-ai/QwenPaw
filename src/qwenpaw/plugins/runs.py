# -*- coding: utf-8 -*-
"""Read-only summaries of runs visible to the current request identity."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TYPE_CHECKING

from .errors import SDKError, StaleContextError

if TYPE_CHECKING:
    from .tools import ToolContext


@dataclass(frozen=True)
class RunSnapshot:
    run_id: str
    workspace_id: str
    session_id: str
    user_id: str
    channel: str
    status: Literal["running", "completed", "failed", "cancelled"]
    started_at: float
    finished_at: float | None = None
    reason: str = ""
    # None means no confirmed relationship, not proof that this is a root run.
    parent_run_id: str | None = None


class RunService:
    """Use call.runs; history is in-memory and retains 512 finished runs.

    Queries require a known user/channel and stay in the calling workspace
    and, when present, session. They never grant cancellation or mutation.
    """

    def __init__(self, context: ToolContext):
        self._context = context

    def _visible(self, snapshot: RunSnapshot) -> bool:
        from .apps import AppContext

        if isinstance(self._context, AppContext):
            namespace = self._context._services.session_id(None)
            if not (
                snapshot.session_id == namespace
                or snapshot.session_id.startswith(namespace + ":")
            ):
                return False
        identity = self._context.identity
        return bool(
            identity.user_id
            and identity.channel
            and snapshot.workspace_id == identity.workspace_id
            and snapshot.user_id == identity.user_id
            and snapshot.channel == identity.channel
            and (
                not identity.session_id
                or snapshot.session_id == identity.session_id
            ),
        )

    def _index(self):
        from ._runs import index

        context = self._context
        if context._plugin is None:
            raise SDKError("Run queries require a host-owned context")
        context._plugin._guard()
        if (
            context.resources.closed
            or context.resources._closing
            or context.cancelled
        ):
            raise StaleContextError("The run caller's scope has ended")
        return index(context._plugin._loader.registry)

    async def current(self) -> RunSnapshot | None:
        """Return this execution's run, or None outside a known run."""
        from ._runs import current_run

        return await self.get(current_run.get() or "")

    async def get(self, run_id: str) -> RunSnapshot | None:
        """Resolve a unique ID, or an unambiguous visible SDK 1.0 event alias."""
        runs = self._index()
        snapshot = runs.snapshots.get(run_id)
        if snapshot is not None:
            return snapshot if self._visible(snapshot) else None
        matches = [
            item
            for key, item in runs.snapshots.items()
            if runs.aliases[key] == run_id and self._visible(item)
        ]
        return matches[0] if len(matches) == 1 else None

    async def list(self, *, limit: int = 50) -> tuple[RunSnapshot, ...]:
        """List visible current/recent runs, newest first; limit is 1–100."""
        if not 1 <= limit <= 100:
            raise SDKError("Run list limit must be between 1 and 100")
        snapshots = self._index().snapshots
        return tuple(
            item
            for item in reversed(tuple(snapshots.values()))
            if self._visible(item)
        )[:limit]
