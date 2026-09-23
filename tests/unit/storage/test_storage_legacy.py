# -*- coding: utf-8 -*-
"""Import existing SQLite data without rewriting its sequence identity."""

import json
import sqlite3

import pytest

from qwenpaw.storage.backends.sqlite.legacy_history import (
    SQLiteHistoryStore as HistoryStore,
)
from qwenpaw.agents.context.types import LogEntry
from qwenpaw.storage.repositories.history import SqlHistoryStore
from qwenpaw.storage.migration.legacy import import_history


@pytest.mark.asyncio
async def test_legacy_import_preserves_deleted_high_water_and_checkpoint(
    db,
    tmp_path,
):
    source = tmp_path / f"legacy.db"
    old = HistoryStore(source)
    old.append(
        session_id=f"chat",
        entry=LogEntry(kind=f"model_turn", content=f"keep"),
    )
    old.append(
        session_id=f"chat",
        entry=LogEntry(kind=f"model_turn", content=f"deleted"),
    )
    old.close()
    with sqlite3.connect(source) as conn:
        conn.execute(f"DELETE FROM conversation_history WHERE seq=2")
    checkpoint = tmp_path / f"session.json"
    payload = {f"agent": {f"scroll": {f"seq_by_id": {f"message": [1, 1]}}}}
    checkpoint.write_text(json.dumps(payload))
    original = source.read_bytes()
    await import_history(
        db,
        source,
        tenant_id=f"tenant",
        workspace_id=f"workspace",
        agent_id=f"agent",
        epoch=1,
        backup_directory=tmp_path / f"backup",
        checkpoints={f"chat": checkpoint},
    )
    history = await SqlHistoryStore.open(
        db,
        tenant_id=f"tenant",
        workspace_id=f"workspace",
        agent_id=f"agent",
        epoch=1,
    )
    assert await history.load_checkpoint(f"chat") == (payload, 1)
    assert await history.contents_by_seqs({1, 2}) == {1: f"keep"}
    assert (
        await history.append(
            session_id=f"chat",
            entry=LogEntry(kind=f"model_turn"),
        )
        == 3
    )
    assert source.read_bytes() == original
    assert not list(tmp_path.glob(f"legacy.db.corrupt-*"))


@pytest.mark.asyncio
async def test_corrupt_source_is_not_quarantined_or_recreated(db, tmp_path):
    source = tmp_path / f"broken.db"
    original = b"this is not a database"
    source.write_bytes(original)
    with pytest.raises(sqlite3.DatabaseError):
        await import_history(
            db,
            source,
            tenant_id=f"tenant",
            workspace_id=f"workspace",
            agent_id=f"agent",
            epoch=1,
            backup_directory=tmp_path / f"backup",
        )
    assert source.read_bytes() == original
    assert not list(tmp_path.glob(f"broken.db.corrupt-*"))
