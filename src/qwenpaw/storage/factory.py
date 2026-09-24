# -*- coding: utf-8 -*-
"""Select drivers and own repository lifetimes at the application edge."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from weakref import WeakSet

from ..agents.context.scroll.history import HistoryStore as LegacyHistoryStore
from .backends.sqlite.legacy_history import SQLiteHistoryStore
from .backends.postgres.database import PostgresDatabase
from .backends.sqlite.database import SQLiteDatabase
from .config import StorageBackend, StorageConfig
from .contracts.database import Database
from .contracts.history import HistoryStore
from .errors import StorageError, StorageMaintenanceError
from .models import StorageScope
from .repositories.history import SqlHistoryStore
from .repositories.leases import Leases
from .repositories.records import Records
from .schema import initialize, validate


def create_database(config: StorageConfig, root: Path) -> Database:
    """Select transport without opening connections or creating data."""
    drivers = {
        StorageBackend.SQLITE: SQLiteDatabase,
        StorageBackend.POSTGRESQL: PostgresDatabase,
    }
    return drivers[config.backend](config, root)


class StorageRuntime:
    """One application's open storage and scoped repository handles."""

    def __init__(self, database: Database, epoch: int) -> None:
        self.database = database
        self.epoch = epoch
        self._histories: WeakSet[HistoryStore] = WeakSet()
        self._closed = False

    def _check_open(self) -> None:
        if self._closed:
            raise StorageError(f"Storage runtime is closed")

    async def history(self, scope: StorageScope) -> HistoryStore:
        """Bind a history handle without exposing SQL details to callers."""
        self._check_open()
        history = await SqlHistoryStore.open(
            self.database,
            tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id,
            agent_id=scope.agent_id,
            epoch=self.epoch,
        )
        self._histories.add(history)
        return history

    def records(self, tenant_id: str) -> Records:
        """Bind records to an explicit tenant and activation epoch."""
        self._check_open()
        if not tenant_id:
            raise ValueError(f"Tenant ID must not be empty")
        return Records(self.database, tenant_id, self.epoch)

    def leases(self) -> Leases:
        """Create lease operations for the current activation epoch."""
        self._check_open()
        return Leases(self.database, self.epoch)

    async def close(self) -> None:
        """Retire handles before closing their shared transport."""
        if self._closed:
            return
        self._closed = True
        try:
            for history in self._histories:
                await history.close()
        finally:
            self._histories.clear()
            await self.database.close()


@asynccontextmanager
async def create_storage(
    config: StorageConfig,
    root: Path,
    *,
    create: bool = False,
) -> AsyncIterator[StorageRuntime]:
    """Open active storage and guarantee cleanup on failed initialization."""
    database = create_database(config, root)
    await database.open(create=create)
    runtime = None
    try:
        meta = (
            await initialize(database) if create else await validate(database)
        )
        if meta[f"status"] != f"active":
            raise StorageMaintenanceError(
                f"Storage is awaiting migration recovery or activation",
            )
        runtime = StorageRuntime(database, meta[f"epoch"])
        yield runtime
    finally:
        if runtime is not None:
            await runtime.close()
        else:
            await database.close()


def create_legacy_history(path: Path) -> LegacyHistoryStore:
    """Construct the old local format without an async-to-sync adapter."""
    return SQLiteHistoryStore(path)
