# -*- coding: utf-8 -*-
"""Bounded asynchronous PostgreSQL transport."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import asyncpg

from ...config import StorageConfig
from ...contracts.database import Database, Transaction, TABLES
from ...errors import StorageError


class PostgresTransaction(Transaction):
    """Keep native parameters and records inside the driver."""

    def __init__(self, connection: asyncpg.Connection) -> None:
        self._connection = connection

    async def execute(self, sql: str, *args: Any) -> None:
        await self._connection.execute(sql, *args)

    async def fetch(self, sql: str, *args: Any) -> list[dict]:
        return [dict(row) for row in await self._connection.fetch(sql, *args)]

    async def one(self, sql: str, *args: Any) -> dict | None:
        row = await self._connection.fetchrow(sql, *args)
        return dict(row) if row is not None else None

    async def many(self, sql: str, rows: Sequence[tuple]) -> None:
        await self._connection.executemany(sql, rows)


class PostgresDatabase(Database):
    """Own one pool for an explicitly qualified application namespace."""

    def __init__(self, config: StorageConfig, root: Path) -> None:
        super().__init__(config, root)
        self._pool: asyncpg.Pool | None = None

    def _table(self, name: str) -> str:
        cfg = self.config.postgresql
        return f'"{cfg.schema_name}"."{cfg.table_prefix}{name}"'

    def index(self, name: str) -> str:
        if name not in (f"history_session", f"history_created"):
            raise ValueError(f"Unknown storage index: {name}")
        return f'"{self.config.postgresql.table_prefix}{name}"'

    def bind(self, index: int) -> str:
        return f"${index}"

    def clock(self) -> str:
        return f"EXTRACT(EPOCH FROM clock_timestamp())"

    async def open(self, *, create: bool = False) -> None:
        if self._pool is not None:
            raise StorageError(f"Storage is already open")
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

    # asynccontextmanager exposes a synchronous context-manager factory.
    @asynccontextmanager
    async def transaction(  # pylint: disable=invalid-overridden-method
        self,
        *,
        write: bool = False,
    ) -> AsyncIterator[Transaction]:
        if self._pool is None:
            raise StorageError(f"Storage is not open")
        timeout = self.config.postgresql.acquire_timeout_seconds
        async with self._pool.acquire(timeout=timeout) as connection:
            async with connection.transaction():
                yield PostgresTransaction(connection)

    async def close(self) -> None:
        if self._pool is not None:
            pool, self._pool = self._pool, None
            try:
                await asyncio.wait_for(pool.close(), timeout=10)
            except TimeoutError:
                pool.terminate()
                raise

    async def existing_tables(self, tx: Transaction) -> set[str]:
        cfg = self.config.postgresql
        rows = await tx.fetch(
            f"SELECT table_name AS name FROM information_schema.tables "
            f"WHERE table_schema = $1",
            cfg.schema_name,
        )
        return {
            row[f"name"][len(cfg.table_prefix) :]
            for row in rows
            if row[f"name"].startswith(cfg.table_prefix)
            and row[f"name"][len(cfg.table_prefix) :] in TABLES
        }

    async def table_columns(self, tx: Transaction, table: str) -> list[str]:
        self.table(table)
        cfg = self.config.postgresql
        rows = await tx.fetch(
            f"SELECT column_name AS name FROM information_schema.columns "
            f"WHERE table_schema=$1 AND table_name=$2 "
            f"ORDER BY ordinal_position",
            cfg.schema_name,
            f"{cfg.table_prefix}{table}",
        )
        return [row[f"name"] for row in rows]

    async def create_namespace(self, tx: Transaction) -> None:
        schema = self.config.postgresql.schema_name
        await tx.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')

    async def backup_native(
        self,
        *,
        migration_id: str,
        prior_identity: dict,
    ) -> None:
        """The mandatory namespace snapshot is PostgreSQL's backup."""
