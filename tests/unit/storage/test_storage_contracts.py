# -*- coding: utf-8 -*-
"""Run retained SQLite behavior against independently selected backends."""

import asyncio

import pytest

from qwenpaw.agents.context.scroll.history import HistoryStore as LegacyStore
from qwenpaw.agents.context.types import LogEntry
from qwenpaw.storage.contracts.history import HistoryStore
from qwenpaw.storage.errors import StorageError, StorageMaintenanceError
from qwenpaw.storage.factory import create_legacy_history, create_storage
from qwenpaw.storage.models import StorageScope


async def invoke(store, method, *args, **kwargs):
    """Compare old sync behavior with the async contract only in tests."""
    operation = getattr(store, method)
    if isinstance(store, LegacyStore):
        return await asyncio.to_thread(operation, *args, **kwargs)
    return await operation(*args, **kwargs)


@pytest.mark.asyncio
async def test_legacy_and_async_history_share_retention_contract(db, tmp_path):
    legacy = create_legacy_history(tmp_path / f"old.db")
    scope = StorageScope(f"tenant", f"workspace", f"agent")
    try:
        async with create_storage(db.config, db.root) as runtime:
            history = await runtime.history(scope)
            assert isinstance(history, HistoryStore)
            for store in (legacy, history):
                event = LogEntry(
                    kind=f"tool_result",
                    content=f"old content",
                    created_at=f"2020-01-01T00:00:00Z",
                )
                seq = await invoke(
                    store,
                    f"append",
                    session_id=f"session",
                    entry=event,
                    dedup_key=f"same",
                )
                assert (
                    await invoke(
                        store,
                        f"append",
                        session_id=f"session",
                        entry=event,
                        dedup_key=f"same",
                    )
                    == seq
                )
                count = await invoke(
                    store,
                    f"append_many",
                    session_id=f"session",
                    entries=[(event, f"same"), (event, f"another")],
                )
                assert count == 1
                estimate = await invoke(
                    store,
                    f"estimate_purge",
                    before=f"2021-01-01",
                    kinds=(f"tool_result",),
                )
                assert estimate == {f"rows": 2, f"content_bytes": 22}
                assert (
                    await invoke(
                        store,
                        f"purge",
                        before=f"2021-01-01",
                        dry_run=True,
                    )
                    == 2
                )
                assert await invoke(store, f"count", f"session") == 2
                assert (
                    await invoke(
                        store,
                        f"purge",
                        before=f"2021-01-01",
                        kinds=(f"model_turn",),
                    )
                    == 0
                )
                assert (
                    await invoke(
                        store,
                        f"purge",
                        before=f"2021-01-01",
                    )
                    == 2
                )
                assert await invoke(store, f"existing_seqs", {seq}) == set()
                next_seq = await invoke(
                    store,
                    f"append",
                    session_id=f"session",
                    entry=event,
                )
                assert next_seq > seq + 1
    finally:
        legacy.close()


@pytest.mark.asyncio
async def test_runtime_closes_handles_without_closing_other_owners(db):
    async with create_storage(db.config, db.root) as runtime:
        history = await runtime.history(
            StorageScope(f"tenant", f"workspace", f"agent"),
        )
        await history.append(
            session_id=f"session",
            entry=LogEntry(kind=f"model_turn"),
        )
    assert history.closed
    with pytest.raises(StorageError, match=f"closed"):
        await history.count(f"session")
    with pytest.raises(StorageError, match=f"closed"):
        runtime.records(f"tenant")
    # The fixture is a separate transport; runtime did not close its pool.
    async with db.transaction() as tx:
        row = await tx.one(f"SELECT COUNT(*) AS n FROM {db.table('history')}")
    assert row[f"n"] == 1


@pytest.mark.asyncio
async def test_runtime_rejects_frozen_storage_and_can_reopen(db):
    async with db.transaction(write=True) as tx:
        await tx.execute(f"UPDATE {db.table('metadata')} SET status='frozen'")
    with pytest.raises(StorageMaintenanceError):
        async with create_storage(db.config, db.root):
            pytest.fail(f"Frozen storage must not reach application code")
    async with db.transaction(write=True) as tx:
        await tx.execute(f"UPDATE {db.table('metadata')} SET status='active'")
    async with create_storage(db.config, db.root) as runtime:
        assert await runtime.records(f"tenant").put(f"models", f"id", {}) == 1


@pytest.mark.asyncio
async def test_purge_cannot_delete_another_scope(db):
    async with create_storage(db.config, db.root) as runtime:
        a = await runtime.history(StorageScope(f"a", f"work", f"agent"))
        b = await runtime.history(StorageScope(f"b", f"work", f"agent"))
        for store in (a, b):
            await store.append(
                session_id=f"same",
                entry=LogEntry(
                    kind=f"model_turn",
                    created_at=f"2020-01-01",
                ),
            )
        assert await a.purge(before=f"2021-01-01") == 1
        assert await a.count(f"same") == 0
        assert await b.count(f"same") == 1
