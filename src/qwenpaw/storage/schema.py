# -*- coding: utf-8 -*-
"""Versioned product-owned tables and dataset write fencing."""

from __future__ import annotations

from uuid import uuid4

from .contracts.database import Database, Transaction, TABLES
from .errors import StorageIdentityError, StorageMaintenanceError

FORMAT_VERSION = 1

# Text JSON preserves portable business values; backend indexes are derived.
DEFINITIONS = {
    f"metadata": f"""
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        deployment_id TEXT NOT NULL,
        dataset_id TEXT NOT NULL,
        format_version INTEGER NOT NULL,
        epoch BIGINT NOT NULL,
        revision BIGINT NOT NULL,
        status TEXT NOT NULL,
        migration_id TEXT
    """,
    f"stores": f"""
        store_id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        workspace_id TEXT NOT NULL,
        agent_id TEXT NOT NULL,
        generation TEXT NOT NULL,
        next_seq BIGINT NOT NULL CHECK (next_seq > 0),
        UNIQUE (tenant_id, workspace_id, agent_id)
    """,
    f"history": f"""
        store_id TEXT NOT NULL,
        seq BIGINT NOT NULL CHECK (seq > 0),
        session_id TEXT NOT NULL,
        agent_id TEXT,
        kind TEXT NOT NULL,
        role TEXT,
        name TEXT,
        content TEXT,
        tool_call_id TEXT,
        tool_input TEXT,
        tool_state TEXT,
        headline TEXT,
        blocks TEXT,
        metadata TEXT,
        created_at TEXT,
        dedup_key TEXT,
        PRIMARY KEY (store_id, seq),
        UNIQUE (store_id, session_id, dedup_key)
    """,
    f"checkpoints": f"""
        store_id TEXT NOT NULL,
        session_id TEXT NOT NULL,
        generation TEXT NOT NULL,
        revision BIGINT NOT NULL,
        payload TEXT NOT NULL,
        PRIMARY KEY (store_id, session_id)
    """,
    f"records": f"""
        tenant_id TEXT NOT NULL,
        collection TEXT NOT NULL,
        record_id TEXT NOT NULL,
        revision BIGINT NOT NULL,
        payload TEXT NOT NULL,
        PRIMARY KEY (tenant_id, collection, record_id)
    """,
    f"usage": f"""
        tenant_id TEXT NOT NULL,
        event_id TEXT NOT NULL,
        payload TEXT NOT NULL,
        PRIMARY KEY (tenant_id, event_id)
    """,
    f"leases": f"""
        store_id TEXT NOT NULL,
        session_id TEXT NOT NULL,
        owner_id TEXT NOT NULL,
        token BIGINT NOT NULL,
        expires_at DOUBLE PRECISION NOT NULL,
        PRIMARY KEY (store_id, session_id)
    """,
    f"migration_jobs": f"""
        job_id TEXT PRIMARY KEY,
        phase TEXT NOT NULL,
        payload TEXT NOT NULL
    """,
}


async def existing_tables(db: Database) -> set[str]:
    """Inspect the namespace without initializing or repairing anything."""
    async with db.transaction() as tx:
        return await db.existing_tables(tx)


async def identity(db: Database, tx: Transaction | None = None) -> dict:
    """Read the persisted identity; absence is never an empty dataset."""
    if tx is None:
        async with db.transaction() as connection:
            return await identity(db, connection)
    row = await tx.one(
        f"SELECT * FROM {db.table('metadata')} WHERE singleton=1",
    )
    if row is None:
        raise StorageIdentityError(f"Storage identity is missing")
    return row


async def initialize(db: Database, *, dataset_id: str | None = None) -> dict:
    """Initialize only an empty namespace, never adopt unowned tables."""
    if not db.config.deployment_id:
        raise StorageIdentityError(f"A persistent deployment_id is required")
    existing = await existing_tables(db)
    if existing:
        if existing != TABLES:
            raise StorageIdentityError(f"Incomplete or unrecognized storage")
        return await validate(db)
    async with db.transaction(write=True) as tx:
        await db.create_namespace(tx)
        for table, columns in DEFINITIONS.items():
            # Deliberately no IF NOT EXISTS: a concurrent initializer must
            # fail rather than partially adopt another deployment's tables.
            await tx.execute(f"CREATE TABLE {db.table(table)} ({columns})")
        await tx.execute(
            f"INSERT INTO {db.table('metadata')} VALUES "
            f"(1, {db.binds(2)}, {FORMAT_VERSION}, 1, 0, 'active', NULL)",
            db.config.deployment_id,
            dataset_id or str(uuid4()),
        )
        history = db.table(f"history")
        await tx.execute(
            f"CREATE INDEX {db.index('history_session')} ON {history} "
            f"(store_id, session_id, seq)",
        )
        await tx.execute(
            f"CREATE INDEX {db.index('history_created')} ON {history} "
            f"(store_id, created_at)",
        )
    return await validate(db)


async def validate(db: Database) -> dict:
    """Check ownership and format before exposing business operations."""
    row = await identity(db)
    if row[f"deployment_id"] != db.config.deployment_id:
        raise StorageIdentityError(f"Storage belongs to another deployment")
    if row[f"format_version"] != FORMAT_VERSION:
        raise StorageIdentityError(f"Unsupported storage format version")
    return row


async def fence_write(db: Database, tx: Transaction, epoch: int) -> None:
    """Serialize maintenance transitions with committed business writes."""
    row = await tx.one(
        f"UPDATE {db.table('metadata')} SET revision=revision+1 "
        f"WHERE singleton=1 AND status='active' "
        f"AND epoch={db.bind(1)} AND deployment_id={db.bind(2)} "
        f"RETURNING revision",
        epoch,
        db.config.deployment_id,
    )
    if row is None:
        raise StorageMaintenanceError(f"Storage is fenced or epoch changed")
