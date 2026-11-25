# -*- coding: utf-8 -*-
"""Identity-bound checkpoint operations using the host restore engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .errors import SDKError

if TYPE_CHECKING:
    from .tools import ToolContext


class CheckpointError(SDKError):
    """The host rejected or could not complete a checkpoint operation."""


@dataclass(frozen=True)
class CheckpointEntry:
    id: str
    kind: str
    name: str
    timestamp_ms: int
    description: str
    is_current: bool


@dataclass(frozen=True)
class SnapshotResult:
    id: str
    timestamp_ms: int


@dataclass(frozen=True)
class RestoreResult:
    id: str
    dry_run: bool
    restored_paths: tuple[str, ...]
    deleted_paths: tuple[str, ...]
    file_paths: tuple[str, ...]
    include_memory: bool
    include_files: bool


class CheckpointService:
    """Use call.checkpoints; no arbitrary workspace/user/session selector.

    Applying a restore requires an app request or declared control command,
    and always asks the bound user through host approval. Ordinary tools can
    preview only. Locks, quiescence, safety snapshots and rollback stay hosted.
    """

    def __init__(self, context: ToolContext):
        self._context = context

    async def timeline(
        self,
        *,
        limit: int = 20,
    ) -> tuple[CheckpointEntry, ...]:
        from ._checkpoints import timeline

        return await timeline(self._context, limit)

    async def snapshot(self, *, name: str = "") -> SnapshotResult:
        from ._checkpoints import snapshot

        return await snapshot(self._context, name)

    async def restore(
        self,
        target: str,
        *,
        dry_run: bool = True,
        include_memory: bool = False,
        include_files: bool = False,
        files: tuple[str, ...] | None = None,
    ) -> RestoreResult:
        """Preview by default; applying waits up to 120 seconds for approval.

        File application requires an explicit nonempty selection from the
        preview. Denial, timeout or cancellation while awaiting confirmation
        never apply. Cancellation while waiting for in-flight work also aborts
        without mutation. Once the host starts writing, the transaction finishes
        atomically even if its caller disconnects; changed impact requires fresh
        confirmation.
        """
        from ._checkpoints import restore

        return await restore(
            self._context,
            target,
            dry_run=dry_run,
            include_memory=include_memory,
            include_files=include_files,
            files=files,
        )
