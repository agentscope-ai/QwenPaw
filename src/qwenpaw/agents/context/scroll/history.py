# -*- coding: utf-8 -*-
"""Synchronous history contract used by the existing scroll runtime.

The async storage contract lives in storage.contracts.history. This contract
keeps the old runtime's call semantics explicit until its async commit
boundaries are integrated; it must not be used to block on remote storage.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any

from ..types import LogEntry

UNCHANGED = object()


class HistoryStore(ABC):
    """Existing scroll operations, without SQLite connections or paths."""

    degraded: bool
    write_failures: int
    write_errors: tuple[type[Exception], ...] = (OSError,)

    @abstractmethod
    def append(
        self,
        *,
        session_id: str,
        entry: LogEntry,
        agent_id: str | None = None,
        dedup_key: str | None = None,
    ) -> int:
        """Persist an event; retries with the same key return its seq."""

    @abstractmethod
    def append_many(
        self,
        *,
        session_id: str,
        entries: Sequence[tuple[LogEntry, str | None]],
        agent_id: str | None = None,
    ) -> int:
        """Persist a batch atomically and return the inserted count."""

    @abstractmethod
    def update_entry(
        self,
        seq: int,
        *,
        content: str | None,
        headline: str | None,
        blocks,
        tool_call_id: str | None = None,
        name: str | None = None,
        tool_state: str | None = None,
        tool_input: Any = None,
        metadata: Any = UNCHANGED,
    ) -> None:
        """Refresh event fields without changing its sequence."""

    @abstractmethod
    def count(self, session_id: str) -> int:
        """Count events belonging to the selected session."""

    @abstractmethod
    def claim_session(self, session_id: str, agent_id: str | None) -> int:
        """Assign only unowned rows to the canonical agent."""

    @abstractmethod
    def reconcile_session_rows(
        self,
        source_ids: set[str],
        target_id: str,
        dedup_keys: set[str],
        *,
        agent_id: str | None = None,
    ) -> tuple[int, int, int]:
        """Reconcile proven import rows, preserving surviving seqs."""

    @abstractmethod
    def existing_seqs(self, seqs: set[int]) -> set[int]:
        """Return only the requested sequences present in this store."""

    @abstractmethod
    def contents_by_seqs(self, seqs: set[int]) -> dict[int, str | None]:
        """Read exact event content without including adjacent rows."""

    @abstractmethod
    def estimate_purge(
        self,
        *,
        before: str,
        kinds: tuple[str, ...] | None = None,
    ) -> dict:
        """Estimate retention deletion without modifying history."""

    @abstractmethod
    def purge(
        self,
        *,
        before: str,
        dry_run: bool = False,
        kinds: tuple[str, ...] | None = None,
    ) -> int:
        """Delete matching retained history without reusing sequences."""

    @abstractmethod
    def note_write_failure(self, exc: BaseException) -> None:
        """Record degraded durability so callers cannot evict history."""

    @property
    @abstractmethod
    def closed(self) -> bool:
        """Whether this handle has been retired."""

    @abstractmethod
    def close(self) -> None:
        """Retire the handle and release its owned resources."""
