# -*- coding: utf-8 -*-
"""Round-trip real backends, including conflicts and post-switch writes."""

import pytest

from qwenpaw.agents.context.types import LogEntry
from qwenpaw.storage.config import StorageConfig
from qwenpaw.storage.database import Database
from qwenpaw.storage.errors import (
    MigrationConflictError,
    StorageMaintenanceError,
)
from qwenpaw.storage.history import History
from qwenpaw.storage.leases import Leases
from qwenpaw.storage.migration import activate, migrate, plan
from qwenpaw.storage.records import Records
from qwenpaw.storage.schema import initialize, identity


@pytest.mark.asyncio
async def test_bidirectional_switch_preserves_ids_and_new_data(db, tmp_path):
    local = Database(
        StorageConfig(deployment_id=f"local"),
        tmp_path / f"local",
    )
    await local.open(create=True)
    await initialize(local)
    try:
        history = await History.open(
            db,
            tenant_id=f"tenant",
            workspace_id=f"workspace",
            agent_id=f"agent",
            epoch=1,
        )
        await history.append(
            session_id=f"session",
            dedup_key=f"first",
            entry=LogEntry(kind=f"model_turn", content=f"old"),
        )
        await history.save_checkpoint(f"session", {f"seq": 1}, revision=0)
        # Deleted high sequence values must never be reused after migration.
        async with db.transaction(write=True) as tx:
            await tx.execute(f"UPDATE {db.table('stores')} SET next_seq=51")
        approved = await plan(db, local)
        result = await migrate(
            db,
            local,
            approved,
            backup_root=tmp_path / f"backups",
        )
        with pytest.raises(StorageMaintenanceError):
            await Records(local, f"tenant", result[f"epoch"]).put(
                f"config",
                f"a",
                {},
            )
        epoch = await activate(db, local, result[f"job_id"])
        moved = await History.open(
            local,
            tenant_id=f"tenant",
            workspace_id=f"workspace",
            agent_id=f"agent",
            epoch=epoch,
        )
        assert moved.store_id == history.store_id
        assert await moved.load_checkpoint(f"session") == ({f"seq": 1}, 1)
        assert (
            await moved.append(
                session_id=f"session",
                entry=LogEntry(kind=f"model_turn", content=f"new"),
            )
            == 51
        )
        reverse = await plan(local, db)
        assert reverse[f"requires_overwrite"]
        with pytest.raises(MigrationConflictError):
            await migrate(
                local,
                db,
                reverse,
                backup_root=tmp_path / f"backups",
            )
        result = await migrate(
            local,
            db,
            reverse,
            backup_root=tmp_path / f"backups",
            overwrite_hash=reverse[f"plan_hash"],
        )
        await activate(local, db, result[f"job_id"])
        rows = await history.rows()
        assert [(r[f"seq"], r[f"content"]) for r in rows] == [
            (1, f"old"),
            (51, f"new"),
        ]
        with pytest.raises(StorageMaintenanceError):
            await history.append(
                session_id=f"session",
                entry=LogEntry(kind=f"model_turn"),
            )
    finally:
        await local.close()


@pytest.mark.asyncio
async def test_target_change_invalidates_approval_without_freezing_source(
    db,
    tmp_path,
):
    target = Database(
        StorageConfig(deployment_id=f"local"),
        tmp_path / f"target",
    )
    await target.open(create=True)
    await initialize(target)
    try:
        approved = await plan(db, target)
        await Records(target, f"tenant", 1).put(f"config", f"changed", {})
        with pytest.raises(MigrationConflictError):
            await migrate(
                db,
                target,
                approved,
                backup_root=tmp_path / f"backups",
            )
        assert (await identity(db))[f"status"] == f"active"
        assert await Records(target, f"tenant", 1).get(
            f"config",
            f"changed",
        ) == ({}, 1)
    finally:
        await target.close()


@pytest.mark.asyncio
async def test_alias_cannot_copy_a_namespace_onto_itself(db, tmp_path):
    approved = await plan(db, db)
    with pytest.raises(MigrationConflictError):
        await migrate(db, db, approved, backup_root=tmp_path / f"backups")
    assert (await identity(db))[f"status"] == f"active"


@pytest.mark.asyncio
async def test_recovery_after_target_commit_keeps_both_ends_fenced(
    db,
    tmp_path,
    monkeypatch,
):
    from qwenpaw.storage import migration

    target = Database(
        StorageConfig(deployment_id=f"local"),
        tmp_path / f"target",
    )
    await target.open(create=True)
    await initialize(target)
    await Records(db, f"tenant", 1).put(f"config", f"key", {f"value": 7})
    approved = await plan(db, target)
    original = migration.export_snapshot

    async def fail_verification(database, directory):
        if directory.name == f"verification":
            raise OSError(f"simulated process failure after target commit")
        return await original(database, directory)

    monkeypatch.setattr(migration, f"export_snapshot", fail_verification)
    try:
        with pytest.raises(OSError):
            await migrate(
                db,
                target,
                approved,
                backup_root=tmp_path / f"backups",
            )
        source_identity, target_identity = await identity(db), await identity(
            target,
        )
        assert source_identity[f"status"] == f"frozen"
        assert target_identity[f"status"] == f"prepared"
        monkeypatch.setattr(migration, f"export_snapshot", original)
        result = await migration.recover(
            db,
            target,
            source_identity[f"migration_id"],
            backup_root=tmp_path / f"backups",
        )
        assert result[f"status"] == f"awaiting_restart"
        epoch = await activate(db, target, result[f"job_id"])
        assert await Records(target, f"tenant", epoch).get(
            f"config",
            f"key",
        ) == ({f"value": 7}, 1)
        with pytest.raises(StorageMaintenanceError):
            await Records(db, f"tenant", 1).put(f"config", f"later", {})
    finally:
        await target.close()


@pytest.mark.asyncio
async def test_active_session_must_drain_before_migration(db, tmp_path):
    target = Database(
        StorageConfig(deployment_id=f"local"),
        tmp_path / f"target",
    )
    await target.open(create=True)
    await initialize(target)
    try:
        leases = Leases(db, 1)
        lease = await leases.acquire(f"store", f"session", f"instance")
        approved = await plan(db, target)
        with pytest.raises(StorageMaintenanceError, match=f"Drain"):
            await migrate(
                db,
                target,
                approved,
                backup_root=tmp_path / f"backups",
            )
        assert (await identity(db))[f"status"] == f"active"
        assert (await identity(target))[f"status"] == f"active"
        await leases.release(lease)
    finally:
        await target.close()
