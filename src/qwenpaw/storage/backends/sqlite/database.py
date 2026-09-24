# -*- coding: utf-8 -*-
"""Serialized asynchronous SQLite transport."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import aiosqlite

from ...config import StorageConfig
from ...contracts.database import Database, Transaction, TABLES
from ...errors import StorageError
from .backup import backup_sqlite


class SQLiteTransaction(Transaction):
    """Keep cursors and SQLite parameter binding inside the driver."""

    def __init__(self, connection: aiosqlite.Connection) -> None:
        self._connection = connection

    async def execute(self, sql: str, *args: Any) -> None:
        async with self._connection.execute(sql, args):
            pass

    async def fetch(self, sql: str, *args: Any) -> list[dict]:
        async with self._connection.execute(sql, args) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

    async def one(self, sql: str, *args: Any) -> dict | None:
        async with self._connection.execute(sql, args) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row is not None else None

    async def many(self, sql: str, rows: Sequence[tuple]) -> None:
        async with self._connection.executemany(sql, rows):
            pass


class SQLiteDatabase(Database):
    """Own exactly one worker-backed connection and transaction lock."""

    def __init__(self, config: StorageConfig, root: Path) -> None:
        super().__init__(config, root)
        self._connection: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    def _table(self, name: str) -> str:
        return f'"{name}"'

    def index(self, name: str) -> str:
        if name not in (f"history_session", f"history_created"):
            raise ValueError(f"Unknown storage index: {name}")
        return f'"{name}"'

    def bind(self, index: int) -> str:
        return f"?"

    def clock(self) -> str:
        return f"((julianday('now') - 2440587.5) * 86400.0)"

    async def open(self, *, create: bool = False) -> None:
        if self._connection is not None:
            raise StorageError(f"Storage is already open")
        cfg = self.config.sqlite
        path = cfg.database_path(self.root).resolve()
        if create:
            await asyncio.to_thread(
                path.parent.mkdir,
                parents=True,
                exist_ok=True,
            )
        uri = f"{path.as_uri()}?mode={'rwc' if create else 'rw'}"
        connection = await aiosqlite.connect(
            uri,
            uri=True,
            timeout=cfg.busy_timeout_seconds,
            isolation_level=None,
        )
        try:
            connection.row_factory = aiosqlite.Row
            await connection.execute(f"PRAGMA foreign_keys=ON")
            await connection.execute(f"PRAGMA journal_mode=WAL")
            await connection.execute(f"PRAGMA synchronous=FULL")
        except BaseException:
            await connection.close()
            raise
        self._connection = connection

    # asynccontextmanager exposes a synchronous context-manager factory.
    @asynccontextmanager
    async def transaction(  # pylint: disable=invalid-overridden-method
        self,
        *,
        write: bool = False,
    ) -> AsyncIterator[Transaction]:
        async with self._lock:
            if self._connection is None:
                raise StorageError(f"Storage is not open")
            connection = self._connection
            try:
                await connection.execute(
                    f"BEGIN IMMEDIATE" if write else f"BEGIN",
                )
                yield SQLiteTransaction(connection)
                await connection.commit()
            except BaseException:
                # Drain enqueued work before the connection is reused.
                cleanup = asyncio.create_task(connection.rollback())
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    await cleanup
                raise

    async def close(self) -> None:
        async with self._lock:
            if self._connection is not None:
                connection, self._connection = self._connection, None
                await connection.close()

    async def existing_tables(self, tx: Transaction) -> set[str]:
        rows = await tx.fetch(
            f"SELECT name FROM sqlite_master WHERE type = 'table'",
        )
        return {row[f"name"] for row in rows} & TABLES

    async def table_columns(self, tx: Transaction, table: str) -> list[str]:
        rows = await tx.fetch(f"PRAGMA table_info({self.table(table)})")
        return [row[f"name"] for row in rows]

    async def create_namespace(self, tx: Transaction) -> None:
        """SQLite's namespace is the already opened database file."""

    async def backup_native(
        self,
        *,
        migration_id: str,
        prior_identity: dict,
    ) -> Path:
        return await backup_sqlite(
            self.config.sqlite.database_path(self.root),
            migration_id=migration_id,
            prior_identity=prior_identity,
        )
