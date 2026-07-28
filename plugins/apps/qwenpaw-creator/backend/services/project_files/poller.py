# -*- coding: utf-8 -*-
"""Backend file poller and last-good Project snapshot cache."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime
import random
import threading
from typing import Literal

from .store import (
    ProjectIntegrityError,
    ProjectNotFound,
    ProjectSnapshot,
    ProjectStore,
    ProjectStoreError,
)


SyncStatus = Literal["healthy", "degraded", "invalid"]


@dataclass(frozen=True, slots=True)
class ProjectSnapshotCacheEntry:
    project_id: str
    snapshot: ProjectSnapshot | None
    inode: int | None
    mtime_ns: int
    size_bytes: int
    loaded_at: datetime
    sync_status: SyncStatus
    last_error: str | None = None

    @property
    def generation(self) -> int | None:
        return self.snapshot.generation if self.snapshot is not None else None

    @property
    def etag(self) -> str | None:
        return self.snapshot.etag if self.snapshot is not None else None


class ProjectPoller:
    """Poll opened Project files without ever caching invalid raw JSON."""

    def __init__(
        self,
        store: ProjectStore,
        *,
        active_interval_seconds: float = 0.75,
        full_reconcile_every: int = 40,
    ) -> None:
        if active_interval_seconds <= 0:
            raise ValueError("active poll interval must be positive")
        if full_reconcile_every < 1:
            raise ValueError("full_reconcile_every must be positive")
        self.store = store
        self.active_interval_seconds = active_interval_seconds
        self.full_reconcile_every = full_reconcile_every
        self._entries: dict[str, ProjectSnapshotCacheEntry] = {}
        self._opened: set[str] = set()
        self._poll_counts: dict[str, int] = {}
        self._lock = threading.RLock()
        self._stop_event: asyncio.Event | None = None

    def open(self, project_id: str) -> ProjectSnapshotCacheEntry:
        with self._lock:
            self._opened.add(project_id)
        return self.poll_once(project_id, force=True)

    def close(self, project_id: str) -> None:
        with self._lock:
            self._opened.discard(project_id)

    def cached(self, project_id: str) -> ProjectSnapshotCacheEntry | None:
        with self._lock:
            return self._entries.get(project_id)

    def note_commit(
        self,
        snapshot: ProjectSnapshot,
    ) -> ProjectSnapshotCacheEntry:
        """Refresh from disk after a commit without allowing cache rollback.

        Async callers can notify out of order. Reusing a caller's old snapshot
        with the current file stat would make subsequent polls treat stale data
        as fresh, so the forced poll is the only source of this cache entry.
        """

        project_id = snapshot.project.project_id
        entry = self.poll_once(project_id, force=True)
        current = entry.snapshot
        if current is None:
            return entry
        if current.generation < snapshot.generation:
            raise ProjectStoreError(
                "Project authority is older than the committed snapshot",
            )
        if (
            current.generation == snapshot.generation
            and current.etag != snapshot.etag
        ):
            raise ProjectStoreError(
                "Project authority ETag conflicts with the committed snapshot",
            )
        with self._lock:
            self._opened.add(project_id)
        return entry

    def poll_once(
        self,
        project_id: str,
        *,
        force: bool = False,
    ) -> ProjectSnapshotCacheEntry:
        target = self.store.project_path(project_id)
        with self._lock:
            previous = self._entries.get(project_id)
            count = self._poll_counts.get(project_id, 0) + 1
            self._poll_counts[project_id] = count
        reconcile = force or count % self.full_reconcile_every == 0
        try:
            file_stat = target.stat()
            fingerprint = (
                getattr(file_stat, "st_ino", None),
                file_stat.st_mtime_ns,
                file_stat.st_size,
            )
            if (
                previous is not None
                and not reconcile
                and fingerprint
                == (previous.inode, previous.mtime_ns, previous.size_bytes)
            ):
                return previous
            snapshot = self.store.read(project_id)
            entry = ProjectSnapshotCacheEntry(
                project_id=project_id,
                snapshot=snapshot,
                inode=fingerprint[0],
                mtime_ns=fingerprint[1],
                size_bytes=fingerprint[2],
                loaded_at=datetime.now(UTC),
                sync_status="healthy",
            )
        except (FileNotFoundError, ProjectNotFound) as exc:
            # ENOENT is an authoritative lifecycle transition, not a
            # transient read failure. Keeping the last-good snapshot here
            # would make a deleted Project remain visible indefinitely.
            with self._lock:
                self._entries.pop(project_id, None)
                self._opened.discard(project_id)
            if isinstance(exc, ProjectNotFound):
                raise
            raise ProjectNotFound(f"Project not found: {project_id}") from exc
        except ProjectIntegrityError as exc:
            entry = self._failed_entry(project_id, previous, "invalid", exc)
        except (OSError, ProjectStoreError) as exc:
            entry = self._failed_entry(project_id, previous, "degraded", exc)
        with self._lock:
            self._entries[project_id] = entry
        return entry

    @staticmethod
    def _failed_entry(
        project_id: str,
        previous: ProjectSnapshotCacheEntry | None,
        status: SyncStatus,
        error: BaseException,
    ) -> ProjectSnapshotCacheEntry:
        if previous is not None:
            return replace(
                previous,
                loaded_at=datetime.now(UTC),
                sync_status=status,
                last_error=f"{type(error).__name__}: {error}",
            )
        return ProjectSnapshotCacheEntry(
            project_id=project_id,
            snapshot=None,
            inode=None,
            mtime_ns=0,
            size_bytes=0,
            loaded_at=datetime.now(UTC),
            sync_status=status,
            last_error=f"{type(error).__name__}: {error}",
        )

    async def run(self) -> None:
        """Poll opened Projects until :meth:`stop` is called."""

        self._stop_event = asyncio.Event()
        while not self._stop_event.is_set():
            with self._lock:
                opened = tuple(sorted(self._opened))
            if opened:
                await asyncio.gather(
                    *(
                        asyncio.to_thread(self.poll_once, project_id)
                        for project_id in opened
                    ),
                    return_exceptions=True,
                )
            delay = self.active_interval_seconds * random.uniform(0.9, 1.1)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
            except TimeoutError:
                pass

    def stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()


__all__ = ["ProjectPoller", "ProjectSnapshotCacheEntry", "SyncStatus"]
