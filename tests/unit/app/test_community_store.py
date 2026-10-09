# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Community sync durability and account isolation use real atomic file IO."""

import pytest

from qwenpaw.app import community_store as store

pytestmark = [pytest.mark.unit, pytest.mark.p0]


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(
        store,
        "_STATE_PATH",
        tmp_path / "community" / "state.json",
    )


async def connect(account="alice", generation="generation-1"):
    await store.save_connection(
        {
            "account_id": account,
            "connection_id": generation,
            "access_token": "test-only",
            "sync_enabled": True,
        },
    )


def event(remote_id="reply:1", created_at=10):
    return {
        "remote_id": remote_id,
        "event_type": "reply",
        "title": "A reply",
        "body": "Details",
        "created_at": created_at,
        "read": False,
    }


@pytest.mark.asyncio
async def test_duplicate_sync_preserves_read_and_delete_across_reload():
    await connect()
    assert await store.ingest("alice", [event()], {"page": 1}) == 1
    first = (await store.list_events())[0]
    assert first["agent_id"] == ""
    await store.mark_read([first["id"]])
    assert await store.ingest("alice", [event()], {"page": 1}) == 0
    assert (await store.list_events())[0]["read"]
    assert await store.delete_event(first["id"])
    await store.ingest("alice", [event()], {"page": 1})
    assert await store.list_events() == []
    assert (await store.get_sync_state())["cursor"] == {"page": 1}


@pytest.mark.asyncio
async def test_disconnect_and_account_switch_reject_inflight_sync():
    await connect()
    await store.ingest("alice", [event()], {})
    await store.disconnect()
    assert await store.get_connection() is None
    assert await store.ingest("alice", [event()], {}) == 0
    await connect("bob", "generation-2")
    assert await store.list_events() == []
    assert await store.ingest("alice", [event()], {}) == 0
    assert not await store.save_connection(
        {"account_id": "alice"},
        expected_account_id="alice",
    )
    assert not await store.update_sync_state("alice", {"last_error": "stale"})


@pytest.mark.asyncio
async def test_same_account_reconnect_rejects_old_generation():
    await connect()
    await connect(generation="generation-2")
    assert await store.ingest("alice", [event()], {}, "generation-1") == 0
    assert await store.ingest("alice", [event()], {}, "generation-2") == 1


@pytest.mark.asyncio
async def test_pause_keeps_mail_and_prevents_further_ingest():
    await connect()
    await store.ingest("alice", [event()], {})
    connection = await store.get_connection()
    connection["sync_enabled"] = False
    await store.save_connection(connection, expected_account_id="alice")
    assert await store.ingest("alice", [event("reply:2")], {}) == 0
    assert len(await store.list_events()) == 1


@pytest.mark.asyncio
async def test_retention_keeps_tombstones_and_credentials_private(monkeypatch):
    monkeypatch.setattr(store, "_MAX_VISIBLE_EVENTS", 1)
    await connect()
    await store.ingest("alice", [event("reply:1", 1), event("reply:2", 2)], {})
    assert len(await store.list_events()) == 1
    assert await store.ingest("alice", [event("reply:1", 1)], {}) == 0
    assert store._STATE_PATH.stat().st_mode & 0o777 == 0o600


@pytest.mark.asyncio
async def test_separate_runtime_owner_directories_isolate_accounts(
    tmp_path,
    monkeypatch,
):
    await connect()
    await store.ingest("alice", [event()], {})
    first_path = store._STATE_PATH
    monkeypatch.setattr(
        store,
        "_STATE_PATH",
        tmp_path / "hub-other-owner" / "state.json",
    )
    assert await store.get_connection() is None
    assert await store.list_events() == []
    await connect("bob")
    await store.ingest("bob", [event()], {})
    bob_id = (await store.list_events())[0]["id"]
    monkeypatch.setattr(store, "_STATE_PATH", first_path)
    assert (await store.get_connection())["account_id"] == "alice"
    assert (await store.list_events())[0]["id"] != bob_id


@pytest.mark.asyncio
async def test_inbox_scope_tracks_account_generation_without_credentials():
    assert await store.inbox_snapshot() == ([], None)
    await connect()
    await store.ingest("alice", [event()], {})
    events, first_scope = await store.inbox_snapshot()
    assert len(events) == 1
    assert isinstance(first_scope, str) and len(first_scope) == 64
    assert "alice" not in first_scope and "test-only" not in first_scope
    await connect(generation="generation-2")
    _, next_scope = await store.inbox_snapshot()
    assert next_scope != first_scope
    await store.disconnect()
    assert await store.inbox_snapshot() == ([], None)
