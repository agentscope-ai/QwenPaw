# -*- coding: utf-8 -*-
"""Tenant-bound history with stable identities across backend migration."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from ..agents.context.types import LogEntry
from .database import Database, Transaction
from .errors import StorageIdentityError, MigrationConflictError
from .records import encode
from .schema import fence_write

COLUMNS = (
    f"session_id",
    f"agent_id",
    f"kind",
    f"role",
    f"name",
    f"content",
    f"tool_call_id",
    f"tool_input",
    f"tool_state",
    f"headline",
    f"blocks",
    f"metadata",
    f"created_at",
    f"dedup_key",
)
JSON_COLUMNS = frozenset((f"tool_input", f"blocks", f"metadata"))


class History:
    """Bind every operation to one previously validated history store."""

    def __init__(self, db: Database, store: dict, epoch: int) -> None:
        self.db = db
        self.store = store
        self.epoch = epoch
        self.closed = False
        self.degraded = False
        self.write_failures = 0

    @property
    def store_id(self) -> str:
        return self.store[f"store_id"]

    @classmethod
    async def open(
        cls,
        db: Database,
        *,
        tenant_id: str,
        workspace_id: str,
        agent_id: str,
        epoch: int,
    ) -> History:
        """Resolve store identity within its tenant and workspace."""
        args = (tenant_id, workspace_id, agent_id)
        select = (
            f"SELECT * FROM {db.table('stores')} "
            f"WHERE tenant_id={db.bind(1)} AND workspace_id={db.bind(2)} "
            f"AND agent_id={db.bind(3)}"
        )
        async with db.transaction() as tx:
            store = await tx.one(select, *args)
        if store is None:
            async with db.transaction(write=True) as tx:
                await fence_write(db, tx, epoch)
                await tx.execute(
                    f"INSERT INTO {db.table('stores')} VALUES "
                    f"({db.binds(5)}, 1) "
                    f"ON CONFLICT (tenant_id, workspace_id, agent_id) "
                    f"DO NOTHING",
                    str(uuid4()),
                    *args,
                    str(uuid4()),
                )
                store = await tx.one(select, *args)
        assert store is not None
        return cls(db, store, epoch)

    @staticmethod
    def _values(session_id: str, agent_id: str, entry: LogEntry, key):
        values = {
            f"session_id": session_id,
            f"agent_id": agent_id,
            f"dedup_key": key,
        }
        for column in COLUMNS:
            if column not in values:
                value = getattr(entry, column)
                if column in JSON_COLUMNS and value is not None:
                    value = encode(value)
                values[column] = value
        if values[f"created_at"] is None:
            values[f"created_at"] = datetime.now(timezone.utc).isoformat()
        return tuple(values[column] for column in COLUMNS)

    async def _append(
        self,
        tx: Transaction,
        session_id: str,
        entry: LogEntry,
        dedup_key: str | None,
    ) -> tuple[int, bool]:
        db = self.db
        if dedup_key is not None:
            existing = await tx.one(
                f"SELECT seq FROM {db.table('history')} "
                f"WHERE store_id={db.bind(1)} AND session_id={db.bind(2)} "
                f"AND dedup_key={db.bind(3)}",
                self.store_id,
                session_id,
                dedup_key,
            )
            if existing:
                return existing[f"seq"], False
        sequence = await tx.one(
            f"UPDATE {db.table('stores')} SET next_seq=next_seq+1 "
            f"WHERE store_id={db.bind(1)} RETURNING next_seq",
            self.store_id,
        )
        assert sequence is not None
        seq = sequence[f"next_seq"] - 1
        values = self._values(
            session_id,
            self.store[f"agent_id"],
            entry,
            dedup_key,
        )
        columns = f", ".join(COLUMNS)
        await tx.execute(
            f"INSERT INTO {db.table('history')} (store_id, seq, {columns}) "
            f"VALUES ({db.binds(len(values) + 2)})",
            self.store_id,
            seq,
            *values,
        )
        return seq, True

    async def append(
        self,
        *,
        session_id: str,
        entry: LogEntry,
        agent_id: str | None = None,
        dedup_key: str | None = None,
    ) -> int:
        """Commit an event and return its stable, store-local sequence."""
        if agent_id not in (None, self.store[f"agent_id"]):
            raise StorageIdentityError(f"History belongs to another agent")
        async with self.db.transaction(write=True) as tx:
            await fence_write(self.db, tx, self.epoch)
            seq, _ = await self._append(tx, session_id, entry, dedup_key)
        return seq

    async def append_many(
        self,
        *,
        session_id: str,
        entries: Sequence[tuple[LogEntry, str | None]],
        agent_id: str | None = None,
    ) -> int:
        """Persist a bounded import batch in one transaction."""
        if agent_id not in (None, self.store[f"agent_id"]):
            raise StorageIdentityError(f"History belongs to another agent")
        inserted = 0
        async with self.db.transaction(write=True) as tx:
            await fence_write(self.db, tx, self.epoch)
            for entry, key in entries:
                _, added = await self._append(tx, session_id, entry, key)
                inserted += added
        return inserted

    async def update_entry(self, seq: int, **changes: Any) -> None:
        """Update a row without allowing its owning scope to change."""
        allowed = {
            f"content",
            f"headline",
            f"blocks",
            f"tool_call_id",
            f"name",
            f"tool_state",
            f"tool_input",
            f"metadata",
        }
        if not changes or not changes.keys() <= allowed:
            raise ValueError(f"Unsupported history update")
        columns = list(changes)
        values = [
            (
                encode(changes[key])
                if key in JSON_COLUMNS and changes[key] is not None
                else changes[key]
            )
            for key in columns
        ]
        db = self.db
        assignments = f", ".join(
            f"{key}={db.bind(index)}" for index, key in enumerate(columns, 1)
        )
        async with db.transaction(write=True) as tx:
            await fence_write(db, tx, self.epoch)
            row = await tx.one(
                f"UPDATE {db.table('history')} SET {assignments} "
                f"WHERE store_id={db.bind(len(values) + 1)} "
                f"AND seq={db.bind(len(values) + 2)} RETURNING seq",
                *values,
                self.store_id,
                seq,
            )
            if row is None:
                raise StorageIdentityError(f"History event no longer exists")

    async def rows(
        self,
        *,
        session_id: str | None = None,
        after: int = 0,
        through: int | None = None,
        limit: int = 1000,
    ) -> list[dict]:
        """Read a bounded page in stable sequence order."""
        if not 1 <= limit <= 10000:
            raise ValueError(f"History page limit must be between 1 and 10000")
        db = self.db
        args: list[Any] = [self.store_id, after]
        where = f"store_id={db.bind(1)} AND seq>{db.bind(2)}"
        for column, value in ((f"session_id", session_id), (f"seq", through)):
            if value is not None:
                args.append(value)
                operator = f"<=" if column == f"seq" else f"="
                where = f"{where} AND {column}{operator}{db.bind(len(args))}"
        args.append(limit)
        async with db.transaction() as tx:
            return await tx.fetch(
                f"SELECT * FROM {db.table('history')} WHERE {where} "
                f"ORDER BY seq LIMIT {db.bind(len(args))}",
                *args,
            )

    async def _select_seqs(self, seqs: set[int]) -> list[dict]:
        if not seqs:
            return []
        db = self.db
        rows = []
        ordered = sorted(seqs)
        async with db.transaction() as tx:
            for start in range(0, len(ordered), 500):
                batch = ordered[start : start + 500]
                rows.extend(
                    await tx.fetch(
                        f"SELECT seq, content FROM {db.table('history')} "
                        f"WHERE store_id={db.bind(1)} "
                        f"AND seq IN ({db.binds(len(batch), 2)})",
                        self.store_id,
                        *batch,
                    ),
                )
        return rows

    async def existing_seqs(self, seqs: set[int]) -> set[int]:
        return {row[f"seq"] for row in await self._select_seqs(seqs)}

    async def contents_by_seqs(self, seqs: set[int]) -> dict[int, str | None]:
        return {
            row[f"seq"]: row[f"content"]
            for row in await self._select_seqs(seqs)
        }

    async def count(self, session_id: str) -> int:
        db = self.db
        async with db.transaction() as tx:
            row = await tx.one(
                f"SELECT COUNT(*) AS count FROM {db.table('history')} "
                f"WHERE store_id={db.bind(1)} AND session_id={db.bind(2)}",
                self.store_id,
                session_id,
            )
        assert row is not None
        return row[f"count"]

    async def save_checkpoint(
        self,
        session_id: str,
        payload: dict,
        *,
        revision: int,
        entries: Sequence[tuple[LogEntry, str | None]] = (),
    ) -> int:
        """Atomically persist a checkpoint and any accompanying events."""
        db = self.db
        encoded = encode(payload)
        async with db.transaction(write=True) as tx:
            await fence_write(db, tx, self.epoch)
            for entry, key in entries:
                await self._append(tx, session_id, entry, key)
            if revision == 0:
                row = await tx.one(
                    f"INSERT INTO {db.table('checkpoints')} VALUES "
                    f"({db.binds(3)}, 1, {db.bind(4)}) "
                    f"ON CONFLICT (store_id, session_id) DO NOTHING "
                    f"RETURNING revision",
                    self.store_id,
                    session_id,
                    self.store[f"generation"],
                    encoded,
                )
            else:
                row = await tx.one(
                    f"UPDATE {db.table('checkpoints')} SET "
                    f"revision=revision+1, payload={db.bind(1)} "
                    f"WHERE store_id={db.bind(2)} AND session_id={db.bind(3)} "
                    f"AND revision={db.bind(4)} AND generation={db.bind(5)} "
                    f"RETURNING revision",
                    encoded,
                    self.store_id,
                    session_id,
                    revision,
                    self.store[f"generation"],
                )
            if row is None:
                raise MigrationConflictError(f"Checkpoint revision changed")
        return row[f"revision"]

    async def load_checkpoint(
        self,
        session_id: str,
    ) -> tuple[dict, int] | None:
        db = self.db
        async with db.transaction() as tx:
            row = await tx.one(
                f"SELECT * FROM {db.table('checkpoints')} "
                f"WHERE store_id={db.bind(1)} AND session_id={db.bind(2)}",
                self.store_id,
                session_id,
            )
        if row is None:
            return None
        if row[f"generation"] != self.store[f"generation"]:
            raise StorageIdentityError(
                f"Checkpoint history generation changed",
            )
        return json.loads(row[f"payload"]), row[f"revision"]

    def note_write_failure(self, exc: BaseException) -> None:
        self.degraded = True
        self.write_failures += 1
        self.last_write_failure = type(exc).__name__

    async def close(self) -> None:
        """Release this handle, leaving the application pool alive."""
        self.closed = True
