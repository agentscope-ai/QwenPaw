# -*- coding: utf-8 -*-
"""Backend-neutral connection and transaction contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Any

from ..config import StorageConfig

# Only product-owned identifiers may pass through table().
TABLES = frozenset(
    (
        f"metadata",
        f"stores",
        f"history",
        f"checkpoints",
        f"records",
        f"usage",
        f"leases",
        f"migration_jobs",
    ),
)


class Transaction(ABC):
    """A caller-owned atomic operation without driver-specific row types."""

    @abstractmethod
    async def execute(self, sql: str, *args: Any) -> None:
        """Execute one parameterized statement."""

    @abstractmethod
    async def fetch(self, sql: str, *args: Any) -> list[dict]:
        """Fetch a caller-bounded set of rows."""

    @abstractmethod
    async def one(self, sql: str, *args: Any) -> dict | None:
        """Fetch the first row without materializing an unbounded result."""

    @abstractmethod
    async def many(self, sql: str, rows: Sequence[tuple]) -> None:
        """Execute a bounded batch in this transaction."""


class Database(ABC):
    """Own transport and dialect details for one storage namespace."""

    def __init__(self, config: StorageConfig, root: Path) -> None:
        self.config = config
        self.root = root

    def table(self, name: str) -> str:
        """Only allow identifiers owned by the storage schema."""
        if name not in TABLES:
            raise ValueError(f"Unknown storage table: {name}")
        return self._table(name)

    @abstractmethod
    def _table(self, name: str) -> str:
        """Qualify a validated product table."""

    @abstractmethod
    def index(self, name: str) -> str:
        """Name a known product index in the current namespace."""

    @abstractmethod
    def bind(self, index: int) -> str:
        """Return a native parameter placeholder."""

    def binds(self, count: int, start: int = 1) -> str:
        """Generate placeholders without rewriting caller SQL."""
        return f", ".join(self.bind(i) for i in range(start, start + count))

    @abstractmethod
    def clock(self) -> str:
        """Return a database-clock expression in epoch seconds."""

    @abstractmethod
    async def open(self, *, create: bool = False) -> None:
        """Open transport without implicitly creating a missing source."""

    @abstractmethod
    async def close(self) -> None:
        """Release connections after request owners have drained."""

    @abstractmethod
    def transaction(
        self,
        *,
        write: bool = False,
    ) -> AbstractAsyncContextManager[Transaction]:
        """Commit success or roll back failure and cancellation."""

    @abstractmethod
    async def existing_tables(self, tx: Transaction) -> set[str]:
        """Inspect owned tables without initializing them."""

    @abstractmethod
    async def table_columns(self, tx: Transaction, table: str) -> list[str]:
        """Inspect columns of a validated product table."""

    @abstractmethod
    async def create_namespace(self, tx: Transaction) -> None:
        """Prepare the namespace inside the initialization transaction."""

    @abstractmethod
    async def backup_native(
        self,
        *,
        migration_id: str,
        prior_identity: dict,
    ) -> Path | None:
        """Preserve backend-native state before a confirmed overwrite.

        Backends without a native file use the migration's mandatory
        verified logical snapshot and return None here.
        """
