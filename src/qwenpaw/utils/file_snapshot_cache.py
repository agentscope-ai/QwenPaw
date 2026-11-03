# -*- coding: utf-8 -*-
"""Bounded process-local cache for immutable file byte snapshots."""

from __future__ import annotations

import os
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FileSignature:
    """Metadata used to cheaply detect ordinary file changes."""

    mtime_ns: int
    ctime_ns: int
    size: int
    device: int
    inode: int

    @classmethod
    def from_stat(cls, value: os.stat_result) -> "FileSignature":
        return cls(
            mtime_ns=value.st_mtime_ns,
            ctime_ns=value.st_ctime_ns,
            size=value.st_size,
            device=getattr(value, "st_dev", 0) or 0,
            inode=getattr(value, "st_ino", 0) or 0,
        )


@dataclass(frozen=True)
class FileSnapshot:
    """One immutable view of a file."""

    path: Path
    signature: FileSignature
    data: bytes
    stable: bool = True

    @property
    def byte_size(self) -> int:
        return len(self.data)


@dataclass(frozen=True)
class FileSnapshotCacheStats:
    hits: int
    misses: int
    reloads: int
    evictions: int
    load_errors: int
    unstable_read_retries: int
    singleflight_waits: int
    entries: int
    bytes: int


@dataclass
class _Flight:
    lock: threading.Lock
    users: int = 0


class FileSnapshotCache:
    """Thread-safe LRU cache which validates entries with ``stat``."""

    def __init__(
        self,
        *,
        max_entries: int = 512,
        max_bytes: int = 64 * 1024 * 1024,
    ) -> None:
        if max_entries <= 0 or max_bytes <= 0:
            raise ValueError("cache limits must be positive")
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self._entries: OrderedDict[str, FileSnapshot] = OrderedDict()
        self._flights: dict[str, _Flight] = {}
        self._lock = threading.RLock()
        self._total_bytes = 0
        self._hits = 0
        self._misses = 0
        self._reloads = 0
        self._evictions = 0
        self._load_errors = 0
        self._unstable_read_retries = 0
        self._singleflight_waits = 0
        self._publication_epoch = 0

    @staticmethod
    def normalize(path: Path | str) -> tuple[str, Path]:
        resolved = Path(path).expanduser().resolve(strict=False)
        return os.path.normcase(os.fspath(resolved)), resolved

    @staticmethod
    def _signature(path: Path) -> FileSignature:
        return FileSignature.from_stat(path.stat())

    def _cached(
        self,
        key: str,
        signature: FileSignature,
    ) -> FileSnapshot | None:
        with self._lock:
            snapshot = self._entries.get(key)
            if snapshot is None or snapshot.signature != signature:
                return None
            self._entries.move_to_end(key)
            self._hits += 1
            return snapshot

    def _remove_locked(self, key: str) -> FileSnapshot | None:
        snapshot = self._entries.pop(key, None)
        if snapshot is not None:
            self._total_bytes -= snapshot.byte_size
        return snapshot

    def _acquire_flight(self, key: str) -> _Flight:
        with self._lock:
            flight = self._flights.get(key)
            if flight is None:
                flight = _Flight(threading.Lock())
                self._flights[key] = flight
            elif flight.users:
                self._singleflight_waits += 1
            flight.users += 1
        flight.lock.acquire()
        return flight

    def _release_flight(self, key: str, flight: _Flight) -> None:
        flight.lock.release()
        with self._lock:
            flight.users -= 1
            if flight.users == 0 and self._flights.get(key) is flight:
                self._flights.pop(key, None)

    def _load_stable(self, path: Path) -> tuple[FileSnapshot, bool]:
        last: FileSnapshot | None = None
        for attempt in range(2):
            before = self._signature(path)
            data = path.read_bytes()
            after = self._signature(path)
            stable = before == after and len(data) == after.size
            last = FileSnapshot(
                path=path,
                signature=after,
                data=data,
                stable=stable,
            )
            if stable:
                return last, True
            if attempt == 0:
                with self._lock:
                    self._unstable_read_retries += 1
        # A continuously-changing file is safe to return to this caller, but
        # must not become a reusable cache entry.
        assert last is not None
        return last, False

    def _publish(
        self,
        key: str,
        snapshot: FileSnapshot,
        publication_epoch: int,
    ) -> None:
        with self._lock:
            if publication_epoch != self._publication_epoch:
                return
            self._remove_locked(key)
            if snapshot.byte_size > self.max_bytes:
                return
            self._entries[key] = snapshot
            self._total_bytes += snapshot.byte_size
            while (
                len(self._entries) > self.max_entries
                or self._total_bytes > self.max_bytes
            ):
                old_key = next(iter(self._entries))
                self._remove_locked(old_key)
                self._evictions += 1

    def get_bytes(self, path: Path | str) -> FileSnapshot:
        """Return a current snapshot, coalescing concurrent cold reads."""
        key, resolved = self.normalize(path)
        try:
            signature = self._signature(resolved)
        except OSError:
            with self._lock:
                self._remove_locked(key)
                self._load_errors += 1
            raise

        cached = self._cached(key, signature)
        if cached is not None:
            return cached

        with self._lock:
            previous = self._entries.get(key)
            self._remove_locked(key)
            self._misses += 1
            publication_epoch = self._publication_epoch
        flight = self._acquire_flight(key)
        try:
            # Another caller may have populated the entry while we waited.
            signature = self._signature(resolved)
            cached = self._cached(key, signature)
            if cached is not None:
                return cached
            snapshot, stable = self._load_stable(resolved)
            # Only publish a stable snapshot. Re-checking its signature also
            # prevents a change immediately after the second stat.
            if stable and self._signature(resolved) == snapshot.signature:
                self._publish(key, snapshot, publication_epoch)
            with self._lock:
                if previous is not None:
                    self._reloads += 1
            return snapshot
        except OSError:
            with self._lock:
                self._remove_locked(key)
                self._load_errors += 1
            raise
        finally:
            self._release_flight(key, flight)

    def invalidate(self, path: Path | str) -> bool:
        key, _ = self.normalize(path)
        with self._lock:
            self._publication_epoch += 1
            return self._remove_locked(key) is not None

    def clear(self) -> None:
        with self._lock:
            self._publication_epoch += 1
            self._entries.clear()
            self._total_bytes = 0

    def stats(self) -> FileSnapshotCacheStats:
        with self._lock:
            return FileSnapshotCacheStats(
                hits=self._hits,
                misses=self._misses,
                reloads=self._reloads,
                evictions=self._evictions,
                load_errors=self._load_errors,
                unstable_read_retries=self._unstable_read_retries,
                singleflight_waits=self._singleflight_waits,
                entries=len(self._entries),
                bytes=self._total_bytes,
            )


_PROCESS_CACHE = FileSnapshotCache()


def get_file_snapshot_cache() -> FileSnapshotCache:
    """Return the process-wide snapshot cache."""
    return _PROCESS_CACHE


__all__ = [
    "FileSignature",
    "FileSnapshot",
    "FileSnapshotCache",
    "FileSnapshotCacheStats",
    "get_file_snapshot_cache",
]
