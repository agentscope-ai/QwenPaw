# -*- coding: utf-8 -*-
"""Exercise real SQLite and PostgreSQL storage isolation and cancellation."""

import asyncio
import time

import pytest
from pydantic import ValidationError

from qwenpaw.storage.config import PostgreSQLConfig, StorageConfig
from qwenpaw.storage.database import Database
from qwenpaw.storage.errors import (
    MigrationConflictError,
    StorageIdentityError,
    StorageMaintenanceError,
)
from qwenpaw.storage.records import Records
from qwenpaw.storage.schema import initialize


@pytest.mark.asyncio
async def test_records_isolate_tenants_and_reject_lost_updates(db):
    a, b = Records(db, f"a", 1), Records(db, f"b", 1)
    assert await a.put(f"models", f"same", {f"model": f"a"}) == 1
    assert await b.get(f"models", f"same") is None
    assert await b.put(f"models", f"same", {f"model": f"b"}) == 1
    assert await a.put(f"models", f"same", {f"model": f"new"}, revision=1) == 2
    with pytest.raises(MigrationConflictError):
        await a.put(f"models", f"same", {f"model": f"stale"}, revision=1)
    assert await a.get(f"models", f"same") == ({f"model": f"new"}, 2)
    assert await b.get(f"models", f"same") == ({f"model": f"b"}, 1)


@pytest.mark.asyncio
async def test_usage_is_idempotent_and_preserves_distinct_events(db):
    records = Records(db, f"tenant", 1)
    payload = {f"prompt_tokens": 100}
    results = await asyncio.gather(
        *(records.record_usage(f"request", payload) for _ in range(5)),
    )
    assert sum(results) == 1
    assert await records.record_usage(f"other", {f"prompt_tokens": 200})
    with pytest.raises(MigrationConflictError):
        await records.record_usage(f"request", {f"prompt_tokens": 500})
    async with db.transaction() as tx:
        rows = await tx.fetch(f"SELECT * FROM {db.table('usage')}")
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_maintenance_and_stale_epoch_block_writes(db):
    records = Records(db, f"tenant", 1)
    async with db.transaction(write=True) as tx:
        await tx.execute(f"UPDATE {db.table('metadata')} SET status='frozen'")
    with pytest.raises(StorageMaintenanceError):
        await records.put(f"models", f"one", {})
    async with db.transaction(write=True) as tx:
        await tx.execute(
            f"UPDATE {db.table('metadata')} SET status='active', epoch=2",
        )
    with pytest.raises(StorageMaintenanceError):
        await records.put(f"models", f"one", {})
    assert await Records(db, f"tenant", 2).put(f"models", f"one", {}) == 1


@pytest.mark.asyncio
async def test_wrong_deployment_cannot_adopt_or_write(db):
    db.config.deployment_id = f"another-deployment"
    with pytest.raises(StorageIdentityError):
        await initialize(db)
    with pytest.raises(StorageMaintenanceError):
        await Records(db, f"tenant", 1).put(f"models", f"one", {})


@pytest.mark.asyncio
async def test_cancellation_rolls_back_before_connection_reuse(db):
    started = asyncio.Event()

    async def interrupted():
        async with db.transaction(write=True) as tx:
            await tx.execute(
                f"INSERT INTO {db.table('records')} "
                f"VALUES ({db.binds(3)}, 1, '{{}}')",
                f"tenant",
                f"models",
                f"cancelled",
            )
            started.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(interrupted())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await Records(db, f"tenant", 1).get(f"models", f"cancelled") is None
    assert await Records(db, f"tenant", 1).put(f"models", f"next", {}) == 1


@pytest.mark.asyncio
async def test_slow_database_does_not_block_loop(db):
    if not db.postgres:
        # pylint: disable-next=protected-access
        await db._sqlite.create_function(f"test_sleep", 1, time.sleep)
    ticks = 0

    async def slow_query():
        async with db.transaction() as tx:
            fn = f"pg_sleep" if db.postgres else f"test_sleep"
            await tx.one(f"SELECT {fn}(0.15)")

    task = asyncio.create_task(slow_query())
    while not task.done():
        ticks += 1
        await asyncio.sleep(0.01)
    await task
    assert ticks >= 5


@pytest.mark.parametrize(f"name", [f"x;DROP TABLE x", f"a.b", f"é", f"a" * 41])
def test_schema_identifier_validation(name):
    with pytest.raises(ValidationError):
        PostgreSQLConfig(schema=name)


def test_pool_validation_and_identifier_qualification(tmp_path):
    with pytest.raises(ValidationError):
        PostgreSQLConfig(pool_min_size=5, pool_max_size=2)
    config = StorageConfig(
        backend=f"postgresql",
        postgresql=PostgreSQLConfig(schema=f"team", table_prefix=f"prod_"),
    )
    db = Database(config, tmp_path)
    assert db.table(f"history") == f'"team"."prod_history"'
    with pytest.raises(ValueError):
        db.table(f"history;DROP TABLE metadata")


@pytest.mark.asyncio
async def test_missing_sqlite_source_is_not_created(tmp_path):
    config = StorageConfig(deployment_id=f"deployment")
    db = Database(config, tmp_path)
    with pytest.raises(Exception, match=f"unable to open"):
        await db.open()
    assert not config.sqlite.database_path(tmp_path).exists()
