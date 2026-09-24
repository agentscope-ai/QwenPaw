# -*- coding: utf-8 -*-
"""One-time import of legacy history files without automatic repair."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from ..contracts.database import Database
from ..errors import StorageIdentityError, MigrationConflictError
from ..repositories.history import COLUMNS
from ..repositories.records import encode
from ..schema import fence_write, identity


def snapshot_history(source: Path, destination: Path) -> None:
    """Copy committed SQLite state, preserving the source and its sidecars."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise MigrationConflictError(f"Legacy snapshot already exists")
    uri = f"{source.resolve().as_uri()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=5)) as origin:
        # Reading must not instantiate HistoryStore, whose corruption
        # recovery renames the authoritative files and resets sequences.
        with closing(sqlite3.connect(destination)) as target:
            origin.backup(target)
        # FTS damage alone is irrelevant here: only authoritative rows and
        # their high-water mark are imported, and the target rebuilds search.
        origin.execute(f"SELECT seq FROM conversation_history LIMIT 1")


def _read_history_batch(source: Path, after: int) -> tuple[list[dict], int]:
    uri = f"{source.resolve().as_uri()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            f"SELECT * FROM conversation_history WHERE seq>? "
            f"ORDER BY seq LIMIT 500",
            (after,),
        ).fetchall()
        allocated = connection.execute(
            f"SELECT seq FROM sqlite_sequence "
            f"WHERE name='conversation_history'",
        ).fetchone()
    return [dict(row) for row in rows], allocated[0] if allocated else 0


def _read_checkpoint(path: Path) -> dict:
    with path.open(encoding=f"utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise StorageIdentityError(f"Invalid legacy checkpoint: {path.name}")
    return value


async def import_history(
    db: Database,
    source: Path,
    *,
    tenant_id: str,
    workspace_id: str,
    agent_id: str,
    epoch: int,
    backup_directory: Path,
    checkpoints: dict[str, Path] | None = None,
) -> str:
    """Import a stopped legacy runtime as one atomic, identity-bound store.

    The caller owns the maintenance window and supplies the canonical
    session ID mapping. Filenames are never guessed from sanitized IDs.
    """
    meta = await identity(db)
    stable_name = encode(
        [
            meta[f"dataset_id"],
            tenant_id,
            workspace_id,
            agent_id,
        ],
    )
    store_id = str(uuid5(NAMESPACE_URL, stable_name))
    generation = str(uuid5(NAMESPACE_URL, f"{store_id}:legacy-generation"))
    snapshot = backup_directory / f"{store_id}.db"
    await asyncio.to_thread(snapshot_history, source, snapshot)
    async with db.transaction(write=True) as tx:
        await fence_write(db, tx, epoch)
        existing = await tx.one(
            f"SELECT store_id FROM {db.table('stores')} "
            f"WHERE tenant_id={db.bind(1)} AND workspace_id={db.bind(2)} "
            f"AND agent_id={db.bind(3)}",
            tenant_id,
            workspace_id,
            agent_id,
        )
        if existing:
            raise MigrationConflictError(f"Legacy target store already exists")
        await tx.execute(
            f"INSERT INTO {db.table('stores')} VALUES ({db.binds(5)}, 1)",
            store_id,
            tenant_id,
            workspace_id,
            agent_id,
            generation,
        )
        last_seq = 0
        high_water = 0
        while True:
            rows, allocated = await asyncio.to_thread(
                _read_history_batch,
                snapshot,
                last_seq,
            )
            high_water = max(high_water, allocated)
            if not rows:
                break
            columns = f", ".join(COLUMNS)
            await tx.many(
                f"INSERT INTO {db.table('history')} "
                f"(store_id, seq, {columns}) "
                f"VALUES ({db.binds(len(COLUMNS) + 2)})",
                [
                    (
                        store_id,
                        row[f"seq"],
                        *(row[column] for column in COLUMNS),
                    )
                    for row in rows
                ],
            )
            last_seq = rows[-1][f"seq"]
        await tx.execute(
            f"UPDATE {db.table('stores')} SET next_seq={db.bind(1)} "
            f"WHERE store_id={db.bind(2)}",
            max(last_seq, high_water) + 1,
            store_id,
        )
        for session_id, path in (checkpoints or {}).items():
            payload = await asyncio.to_thread(_read_checkpoint, path)
            await tx.execute(
                f"INSERT INTO {db.table('checkpoints')} "
                f"VALUES ({db.binds(3)}, 1, {db.bind(4)})",
                store_id,
                session_id,
                generation,
                encode(payload),
            )
    return store_id
