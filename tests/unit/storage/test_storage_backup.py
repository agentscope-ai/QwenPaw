# -*- coding: utf-8 -*-
"""Date-stamped backups include committed WAL and never mask write failure."""

import json
import re
import sqlite3
from contextlib import closing

import pytest

from qwenpaw.storage.backends.sqlite.backup import backup_sqlite
from qwenpaw.storage.config import StorageConfig
from qwenpaw.storage.factory import create_database
from qwenpaw.storage.migration.service import MigrationService
from qwenpaw.storage.repositories.records import Records
from qwenpaw.storage.schema import identity, initialize
from qwenpaw.storage.backends.sqlite import database as sqlite_backend


@pytest.mark.asyncio
async def test_backup_is_unique_and_reads_committed_wal(tmp_path):
    source = tmp_path / f"history.db"
    with closing(sqlite3.connect(source)) as connection:
        connection.execute(f"PRAGMA journal_mode=WAL")
        connection.execute(f"PRAGMA wal_autocheckpoint=0")
        connection.execute(f"CREATE TABLE messages (content TEXT)")
        connection.execute(f"INSERT INTO messages VALUES ('committed in WAL')")
        connection.commit()
        assert source.with_name(f"history.db-wal").exists()
        first = await backup_sqlite(
            source,
            migration_id=f"one",
            prior_identity={},
        )
        second = await backup_sqlite(
            source,
            migration_id=f"two",
            prior_identity={},
        )
    assert first != second
    assert first.parent == source.parent / f"backups"
    assert re.fullmatch(
        f"history[.]db[.]\\d{{8}}T\\d{{6}}[.]\\d{{6}}Z[.]"
        f"[0-9a-f]{{32}}[.]backup",
        first.name,
    )
    with closing(sqlite3.connect(first)) as restored:
        assert restored.execute(
            f"SELECT content FROM messages",
        ).fetchall() == [(f"committed in WAL",)]
    manifest = json.loads(first.with_name(f"{first.name}.json").read_text())
    assert manifest[f"status"] == f"verified"
    assert manifest[f"migration_id"] == f"one"
    assert len(manifest[f"sha256"]) == 64


@pytest.mark.asyncio
async def test_overwrite_creates_dated_native_backup(db, tmp_path):
    target = create_database(
        StorageConfig(deployment_id=f"target"),
        tmp_path / f"target",
    )
    await target.open(create=True)
    await initialize(target)
    try:
        await Records(target, f"tenant", 1).put(
            f"config",
            f"old",
            {f"value": 9},
        )
        approved = await MigrationService(db, target).plan()
        result = await MigrationService(db, target).migrate(
            approved,
            backup_root=tmp_path / f"jobs",
            overwrite_hash=approved[f"plan_hash"],
        )
        path = target.config.sqlite.database_path(target.root)
        backups = list((path.parent / f"backups").glob(f"state.db.*.backup"))
        assert len(backups) == 1
        assert result[f"native_backup"] == str(backups[0])
        with closing(sqlite3.connect(backups[0])) as saved:
            row = saved.execute(
                f"SELECT payload FROM records WHERE record_id='old'",
            ).fetchone()
        assert json.loads(row[0]) == {f"value": 9}
    finally:
        await target.close()


@pytest.mark.asyncio
async def test_backup_failure_aborts_overwrite(db, tmp_path, monkeypatch):
    target = create_database(
        StorageConfig(deployment_id=f"target"),
        tmp_path / f"target",
    )
    await target.open(create=True)
    await initialize(target)

    async def disk_full(*args, **kwargs):
        raise OSError(f"No space left on device")

    monkeypatch.setattr(sqlite_backend, f"backup_sqlite", disk_full)
    try:
        records = Records(target, f"tenant", 1)
        await records.put(f"config", f"keep", {f"value": 9})
        approved = await MigrationService(db, target).plan()
        with pytest.raises(OSError, match=f"No space"):
            await MigrationService(db, target).migrate(
                approved,
                backup_root=tmp_path / f"jobs",
                overwrite_hash=approved[f"plan_hash"],
            )
        assert await records.get(f"config", f"keep") == ({f"value": 9}, 1)
        assert (await identity(db))[f"status"] == f"active"
        assert (await identity(target))[f"status"] == f"active"
    finally:
        await target.close()
