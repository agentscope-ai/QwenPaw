# -*- coding: utf-8 -*-
"""Asynchronous durable history operations independent of the SQL driver."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any

from ...agents.context.types import LogEntry


class HistoryStore(ABC):
    """Bind history and checkpoint operations to one stable store."""

    closed: bool
    degraded: bool
    write_failures: int

    @property
    @abstractmethod
    def store_id(self) -> str:
        """Stable store identity, preserved across backend migration."""

    @abstractmethod
    async def append(
        self,
        *,
        session_id: str,
        entry: LogEntry,
        agent_id: str | None = None,
        dedup_key: str | None = None,
    ) -> int:
        """Persist an event; retries with the same key return its seq."""

    @abstractmethod
    async def append_many(
        self,
        *,
        session_id: str,
        entries: Sequence[tuple[LogEntry, str | None]],
        agent_id: str | None = None,
    ) -> int:
        """Persist a batch atomically and return the inserted count."""

    @abstractmethod
    async def update_entry(self, seq: int, **changes: Any) -> None:
        """Refresh event fields without changing its sequence."""

    @abstractmethod
    async def rows(
        self,
        *,
        session_id: str | None = None,
        after: int = 0,
        through: int | None = None,
        limit: int = 1000,
    ) -> list[dict]:
        """Read a bounded sequence-ordered page within this store."""

    @abstractmethod
    async def existing_seqs(self, seqs: set[int]) -> set[int]:
        """Return only the requested sequences present in this store."""

    @abstractmethod
    async def contents_by_seqs(self, seqs: set[int]) -> dict[int, str | None]:
        """Read exact event content without including adjacent rows."""

    @abstractmethod
    async def count(self, session_id: str) -> int:
        """Count events belonging to the selected session."""

    @abstractmethod
    async def save_checkpoint(
        self,
        session_id: str,
        payload: dict,
        *,
        revision: int,
        entries: Sequence[tuple[LogEntry, str | None]] = (),
    ) -> int:
        """Commit history and a revision-checked checkpoint atomically."""

    @abstractmethod
    async def load_checkpoint(
        self,
        session_id: str,
    ) -> tuple[dict, int] | None:
        """Read a checkpoint only if its history generation matches."""

    @abstractmethod
    def note_write_failure(self, exc: BaseException) -> None:
        """Mark durability degraded without changing the operation result."""

    @abstractmethod
    async def close(self) -> None:
        """Retire the handle and release its owned resources."""

    @abstractmethod
    async def estimate_purge(
        self,
        *,
        before: str,
        kinds: tuple[str, ...] | None = None,
    ) -> dict:
        """Estimate retained-history deletion without modifying rows."""

    @abstractmethod
    async def purge(
        self,
        *,
        before: str,
        dry_run: bool = False,
        kinds: tuple[str, ...] | None = None,
    ) -> int:
        """Delete only matching history inside the bound store."""
