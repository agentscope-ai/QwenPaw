# -*- coding: utf-8 -*-
"""Bounded asynchronous connections with explicit SQL dialect helpers."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import aiosqlite
import asyncpg

from .config import StorageConfig
from .errors import StorageError

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


class Transaction:
    """One connection owned by one asynchronous transaction."""

    def __init__(self, connection: Any, postgres: bool) -> None:
        self.connection = connection
        self.postgres = postgres

    async def execute(self, sql: str, *args: Any) -> None:
        """Execute a statement without retaining a cursor."""
        if self.postgres:
            await self.connection.execute(sql, *args)
        else:
            async with self.connection.execute(sql, args):
                pass

    async def fetch(self, sql: str, *args: Any) -> list[dict]:
        """Read a bounded result supplied by the caller."""
        if self.postgres:
            return [
                dict(row) for row in await self.connection.fetch(sql, *args)
            ]
        async with self.connection.execute(sql, args) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

    async def one(self, sql: str, *args: Any) -> dict | None:
        """Read the first row of a query."""
        if self.postgres:
            row = await self.connection.fetchrow(sql, *args)
        else:
            async with self.connection.execute(sql, args) as cursor:
                row = await cursor.fetchone()
        return dict(row) if row is not None else None

    async def many(self, sql: str, rows: Sequence[tuple]) -> None:
        """Write one bounded batch on the current transaction."""
        if self.postgres:
            await self.connection.executemany(sql, rows)
        else:
            async with self.connection.executemany(sql, rows):
                pass


class Database:
    """Own a process-local pool or serialized SQLite connection."""

    def __init__(self, config: StorageConfig, root: Path) -> None:
        self.config = config
        self.root = root
        self.postgres = config.backend == f"postgresql"
        self._pool: asyncpg.Pool | None = None
        self._sqlite: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    def table(self, name: str) -> str:
        """Qualify a known product table without using search_path."""
        if name not in TABLES:
            raise ValueError(f"Unknown storage table: {name}")
        if not self.postgres:
            return f'"{name}"'
        cfg = self.config.postgresql
        return f'"{cfg.schema_name}"."{cfg.table_prefix}{name}"'

    def bind(self, index: int) -> str:
        """Generate native placeholders, without translating SQL text."""
        return f"${index}" if self.postgres else f"?"

    def binds(self, count: int, start: int = 1) -> str:
        """Generate placeholders for a known number of values."""
        return f", ".join(self.bind(i) for i in range(start, start + count))

    async def open(self, *, create: bool = False) -> None:
        """Open transport; never create a missing SQLite source by accident."""
        if self._pool is not None or self._sqlite is not None:
            raise StorageError(f"Storage is already open")
        if self.postgres:
            cfg = self.config.postgresql
            statement_ms = int(cfg.statement_timeout_seconds * 1000)
            lock_ms = int(cfg.acquire_timeout_seconds * 1000)
            self._pool = await asyncpg.create_pool(
                dsn=cfg.connection_string(),
                min_size=cfg.pool_min_size,
                max_size=cfg.pool_max_size,
                timeout=cfg.connect_timeout_seconds,
                command_timeout=cfg.statement_timeout_seconds,
                server_settings={
                    f"statement_timeout": f"{statement_ms}",
                    f"lock_timeout": f"{lock_ms}",
                    f"application_name": f"qwenpaw",
                },
            )
            return
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
        self._sqlite = connection

    @asynccontextmanager
    async def transaction(
        self,
        *,
        write: bool = False,
    ) -> AsyncIterator[Transaction]:
        """Rollback failures and cancellation before connection reuse."""
        if self.postgres:
            if self._pool is None:
                raise StorageError(f"Storage is not open")
            timeout = self.config.postgresql.acquire_timeout_seconds
            async with self._pool.acquire(timeout=timeout) as connection:
                async with connection.transaction():
                    yield Transaction(connection, True)
            return
        if self._sqlite is None:
            raise StorageError(f"Storage is not open")
        async with self._lock:
            connection = self._sqlite
            try:
                await connection.execute(
                    f"BEGIN IMMEDIATE" if write else f"BEGIN",
                )
                yield Transaction(connection, False)
                await connection.commit()
            except BaseException:
                # Enqueued work completes before rollback on aiosqlite's
                # worker. Shield cleanup so a cancelled task cannot leak it.
                cleanup = asyncio.create_task(connection.rollback())
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    await cleanup
                raise

    async def close(self) -> None:
        """Release transport only after its owners have drained requests."""
        if self._pool is not None:
            pool, self._pool = self._pool, None
            try:
                await asyncio.wait_for(pool.close(), timeout=10)
            except TimeoutError:
                pool.terminate()
                raise
        if self._sqlite is not None:
            async with self._lock:
                connection, self._sqlite = self._sqlite, None
                await connection.close()
