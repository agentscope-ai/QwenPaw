# -*- coding: utf-8 -*-
"""Verify stable history identities and atomic checkpoint transitions."""

import asyncio

import pytest

from qwenpaw.agents.context.types import LogEntry
from qwenpaw.storage.errors import MigrationConflictError, StorageIdentityError
from qwenpaw.storage.repositories.history import SqlHistoryStore


async def open_history(db, tenant=f"tenant"):
    return await SqlHistoryStore.open(
        db,
        tenant_id=tenant,
        workspace_id=f"workspace",
        agent_id=f"agent",
        epoch=1,
    )


@pytest.mark.asyncio
async def test_history_deduplicates_concurrent_writers(db):
    history = await open_history(db)
    entry = LogEntry(kind=f"model_turn", content=f"original")
    seqs = await asyncio.gather(
        *(
            history.append(
                session_id=f"session",
                entry=entry,
                dedup_key=f"msg",
            )
            for _ in range(5)
        ),
    )
    assert seqs == [1] * 5
    assert await history.count(f"session") == 1
    await history.update_entry(
        1,
        content=f"extended",
        blocks=[{f"text": f"hi"}],
    )
    assert await history.contents_by_seqs({1, 2}) == {1: f"extended"}
    assert await history.existing_seqs({1, 2}) == {1}


@pytest.mark.asyncio
async def test_same_agent_and_seq_in_other_tenant_are_isolated(db):
    a, b = await open_history(db, f"a"), await open_history(db, f"b")
    for history, text in ((a, f"a-content"), (b, f"b-content")):
        assert (
            await history.append(
                session_id=f"same",
                entry=LogEntry(kind=f"model_turn", content=text),
            )
            == 1
        )
    assert a.store_id != b.store_id
    assert await a.contents_by_seqs({1}) == {1: f"a-content"}
    assert await b.contents_by_seqs({1}) == {1: f"b-content"}
    with pytest.raises(StorageIdentityError):
        await a.append(
            session_id=f"same",
            agent_id=f"other",
            entry=LogEntry(kind=f"model_turn"),
        )


@pytest.mark.asyncio
async def test_checkpoint_conflict_rolls_back_accompanying_history(db):
    history = await open_history(db)
    entry = LogEntry(kind=f"model_turn", content=f"committed")
    payload = {f"scroll": {f"seq_by_id": {f"msg": [1, 1]}}}
    assert (
        await history.save_checkpoint(
            f"session",
            payload,
            revision=0,
            entries=[(entry, f"msg")],
        )
        == 1
    )
    with pytest.raises(MigrationConflictError):
        await history.save_checkpoint(
            f"session",
            {},
            revision=0,
            entries=[(entry, f"must-rollback")],
        )
    assert await history.count(f"session") == 1
    assert await history.load_checkpoint(f"session") == (payload, 1)
    async with db.transaction(write=True) as tx:
        await tx.execute(
            f"UPDATE {db.table('checkpoints')} SET generation='wrong'",
        )
    with pytest.raises(StorageIdentityError):
        await history.load_checkpoint(f"session")
