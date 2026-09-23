# -*- coding: utf-8 -*-
"""Bounded, checksummed snapshots for portable backend migration."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path

from .database import Database, Transaction
from .errors import StorageIdentityError, StorageMaintenanceError
from .records import encode
from .schema import identity

ORDER = {
    f"stores": (f"store_id",),
    f"history": (f"store_id", f"seq"),
    f"checkpoints": (f"store_id", f"session_id"),
    f"records": (f"tenant_id", f"collection", f"record_id"),
    f"usage": (f"tenant_id", f"event_id"),
}
BATCH_SIZE = 500


def _write_batch(path: Path, rows: list[dict], digest) -> None:
    with path.open(f"ab") as stream:
        for row in rows:
            content = f"{encode(row)}\n".encode(f"utf-8")
            stream.write(content)
            digest.update(content)
        stream.flush()
        os.fsync(stream.fileno())


def _open_text(path: Path):
    return path.open(f"r", encoding=f"utf-8")


def _read_batch(stream) -> list[dict]:
    rows = []
    for _ in range(BATCH_SIZE):
        line = stream.readline()
        if not line:
            break
        rows.append(json.loads(line))
    return rows


def _file_digest(path: Path) -> str:
    with path.open(f"rb") as stream:
        return hashlib.file_digest(stream, f"sha256").hexdigest()


async def export_snapshot(db: Database, directory: Path) -> dict:
    """Export only a frozen dataset; never follow a moving source."""
    await asyncio.to_thread(directory.mkdir, parents=True, mode=0o700)
    manifest = {f"identity": {}, f"tables": {}}
    async with db.transaction() as tx:
        meta = await identity(db, tx)
        if meta[f"status"] not in (f"frozen", f"prepared", f"retired"):
            raise StorageMaintenanceError(f"Snapshot requires frozen writes")
        manifest[f"identity"] = meta
        for table, keys in ORDER.items():
            path = directory / f"{table}.jsonl"
            await asyncio.to_thread(path.touch, mode=0o600, exist_ok=False)
            digest = hashlib.sha256()
            offset = 0
            while True:
                rows = await tx.fetch(
                    f"SELECT * FROM {db.table(table)} "
                    f"ORDER BY {', '.join(keys)} "
                    f"LIMIT {BATCH_SIZE} OFFSET {offset}",
                )
                if not rows:
                    break
                await asyncio.to_thread(_write_batch, path, rows, digest)
                offset += len(rows)
            manifest[f"tables"][table] = {
                f"rows": offset,
                f"sha256": digest.hexdigest(),
            }
    await asyncio.to_thread(
        (directory / f"manifest.json").write_text,
        encode(manifest),
        encoding=f"utf-8",
    )
    return manifest


async def read_manifest(directory: Path) -> dict:
    """Verify immutable snapshot files before importing any target rows."""
    raw = await asyncio.to_thread(
        (directory / f"manifest.json").read_text,
        encoding=f"utf-8",
    )
    manifest = json.loads(raw)
    if set(manifest[f"tables"]) != set(ORDER):
        raise StorageIdentityError(f"Snapshot table manifest is invalid")
    for table, details in manifest[f"tables"].items():
        actual = await asyncio.to_thread(
            _file_digest,
            directory / f"{table}.jsonl",
        )
        if actual != details[f"sha256"]:
            raise StorageIdentityError(f"Snapshot checksum mismatch: {table}")
    return manifest


async def import_snapshot(
    db: Database,
    tx: Transaction,
    directory: Path,
    manifest: dict,
) -> None:
    """Replace exact managed tables within a caller-owned transaction."""
    for table in reversed(ORDER):
        await tx.execute(f"DELETE FROM {db.table(table)}")
    # Leases describe live ownership, not portable business data. Tokens
    # cannot survive switching because every write also checks the epoch.
    await tx.execute(f"DELETE FROM {db.table('leases')}")
    for table in ORDER:
        path = directory / f"{table}.jsonl"
        stream = await asyncio.to_thread(_open_text, path)
        count = 0
        digest = hashlib.sha256()
        try:
            while True:
                rows = await asyncio.to_thread(_read_batch, stream)
                if not rows:
                    break
                columns = list(rows[0])
                # Column names originate in the snapshot, so validate them
                # against the actual fixed target schema before quoting.
                expected_columns = await table_columns(db, tx, table)
                if set(columns) != set(expected_columns):
                    raise StorageIdentityError(f"Invalid columns: {table}")
                sql = (
                    f"INSERT INTO {db.table(table)} "
                    f"({', '.join(columns)}) VALUES ({db.binds(len(columns))})"
                )
                await tx.many(
                    sql,
                    [tuple(row[key] for key in columns) for row in rows],
                )
                for row in rows:
                    digest.update(f"{encode(row)}\n".encode(f"utf-8"))
                count += len(rows)
        finally:
            await asyncio.to_thread(stream.close)
        expected = manifest[f"tables"][table]
        if (
            count != expected[f"rows"]
            or digest.hexdigest() != expected[f"sha256"]
        ):
            raise StorageIdentityError(
                f"Snapshot changed while reading: {table}",
            )
    await validate_references(db, tx)


async def table_columns(
    db: Database,
    tx: Transaction,
    table: str,
) -> list[str]:
    """Read columns only for a validated product-owned table."""
    qualified = db.table(table)
    if db.postgres:
        cfg = db.config.postgresql
        rows = await tx.fetch(
            f"SELECT column_name AS name FROM information_schema.columns "
            f"WHERE table_schema=$1 AND table_name=$2 "
            f"ORDER BY ordinal_position",
            cfg.schema_name,
            f"{cfg.table_prefix}{table}",
        )
    else:
        rows = await tx.fetch(f"PRAGMA table_info({qualified})")
    return [row[f"name"] for row in rows]


async def validate_references(db: Database, tx: Transaction) -> None:
    """Reject changed store identities and reused sequence high-water marks."""
    histories, stores = db.table(f"history"), db.table(f"stores")
    bad = await tx.one(
        f"SELECT h.store_id FROM {histories} h LEFT JOIN {stores} s "
        f"ON s.store_id=h.store_id WHERE s.store_id IS NULL "
        f"OR h.seq>=s.next_seq LIMIT 1",
    )
    if bad:
        raise StorageIdentityError(
            f"Invalid history store or sequence high-water mark",
        )
    bad = await tx.one(
        f"SELECT c.store_id FROM {db.table('checkpoints')} c "
        f"LEFT JOIN {stores} s ON s.store_id=c.store_id "
        f"WHERE s.store_id IS NULL OR c.generation<>s.generation LIMIT 1",
    )
    if bad:
        raise StorageIdentityError(f"Checkpoint history identity mismatch")
