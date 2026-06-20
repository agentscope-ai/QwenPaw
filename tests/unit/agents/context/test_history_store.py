# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access,unused-argument
"""Unit tests for the durable :class:`HistoryStore`.

Covers append + idempotency (the ``ux_dedup`` net behind resume/migration),
in-place ``update_entry`` with FTS sync, retention ``purge``, the degraded
durability flag, and corruption quarantine.
"""

import sqlite3
from pathlib import Path

import pytest

from qwenpaw.agents.context.scroll.history import HistoryStore
from qwenpaw.agents.context.types import LogEntry


@pytest.fixture
def store(tmp_path: Path) -> HistoryStore:
    h = HistoryStore(tmp_path / "history.db")
    yield h
    h.close()


def _entry(content="hello", **kw) -> LogEntry:
    kw.setdefault("kind", "model_turn")
    kw.setdefault("role", "assistant")
    return LogEntry(content=content, **kw)


def test_append_assigns_increasing_seq_and_counts(store: HistoryStore):
    s1 = store.append(session_id="s", dedup_key="a", entry=_entry("one"))
    s2 = store.append(session_id="s", dedup_key="b", entry=_entry("two"))
    assert s2 > s1
    assert store.count("s") == 2
    assert store.count("other") == 0


def test_append_is_idempotent_on_session_dedup_key(store: HistoryStore):
    """A second append of the same (session, dedup_key) is a no-op that
    returns the existing seq — the resume/migration safety net."""
    seq = store.append(session_id="s", dedup_key="m1", entry=_entry("first"))
    again = store.append(
        session_id="s",
        dedup_key="m1",
        entry=_entry("first again"),
    )
    assert again == seq
    assert store.count("s") == 1  # no duplicate row


def test_same_dedup_key_different_session_does_not_collide(
    store: HistoryStore,
):
    a = store.append(session_id="s1", dedup_key="m1", entry=_entry())
    b = store.append(session_id="s2", dedup_key="m1", entry=_entry())
    assert a != b
    assert store.count("s1") == 1 and store.count("s2") == 1


def test_null_dedup_key_is_never_deduped(store: HistoryStore):
    store.append(session_id="s", dedup_key=None, entry=_entry("x"))
    store.append(session_id="s", dedup_key=None, entry=_entry("x"))
    assert store.count("s") == 2


def test_update_entry_refreshes_row_in_place(store: HistoryStore):
    seq = store.append(
        session_id="s",
        dedup_key="m1",
        entry=_entry("v1", headline=None),
    )
    store.update_entry(seq, content="v2", headline="grew", blocks=[{"t": 1}])
    row = store._conn.execute(
        "SELECT content, headline FROM conversation_history WHERE seq = ?",
        (seq,),
    ).fetchone()
    assert row["content"] == "v2"
    assert row["headline"] == "grew"
    assert store.count("s") == 1  # still one row, just refreshed


def test_update_entry_refreshes_scalar_columns(store: HistoryStore):
    """A turn that grows a later tool call must not leave the scalar
    tool_call_id/name/tool_state frozen at their first-write values."""
    seq = store.append(
        session_id="s",
        dedup_key="m1",
        entry=_entry(
            "v1",
            tool_call_id="c1",
            name="grep",
            tool_state="running",
        ),
    )
    store.update_entry(
        seq,
        content="v2",
        headline=None,
        blocks=None,
        tool_call_id="c2",
        name="edit",
        tool_state="success",
    )
    row = store._conn.execute(
        "SELECT tool_call_id, name, tool_state "
        "FROM conversation_history WHERE seq = ?",
        (seq,),
    ).fetchone()
    assert row["tool_call_id"] == "c2"
    assert row["name"] == "edit"
    assert row["tool_state"] == "success"


def test_fts_search_via_raw_table(store: HistoryStore):
    if not store._fts:
        pytest.skip("SQLite build lacks FTS5")
    store.append(
        session_id="s",
        dedup_key="m1",
        entry=_entry("the tanks rolled across the bridge"),
    )
    store.append(session_id="s", dedup_key="m2", entry=_entry("quiet meadow"))
    rows = store._conn.execute(
        "SELECT rowid FROM conversation_history_fts WHERE "
        "conversation_history_fts MATCH 'tank'",  # porter stems tanks->tank
    ).fetchall()
    assert len(rows) == 1


def test_update_entry_keeps_fts_in_sync(store: HistoryStore):
    if not store._fts:
        pytest.skip("SQLite build lacks FTS5")
    seq = store.append(
        session_id="s",
        dedup_key="m1",
        entry=_entry("aardvark"),
    )
    store.update_entry(seq, content="zebra", headline=None, blocks=None)
    old = store._conn.execute(
        "SELECT rowid FROM conversation_history_fts WHERE "
        "conversation_history_fts MATCH 'aardvark'",
    ).fetchall()
    new = store._conn.execute(
        "SELECT rowid FROM conversation_history_fts WHERE "
        "conversation_history_fts MATCH 'zebra'",
    ).fetchall()
    assert old == []  # stale term removed
    assert len(new) == 1


def test_purge_drops_old_rows_and_keeps_recent(store: HistoryStore):
    store.append(
        session_id="s",
        dedup_key="old",
        entry=_entry("ancient", created_at="2020-01-01T00:00:00+00:00"),
    )
    store.append(
        session_id="s",
        dedup_key="new",
        entry=_entry("fresh", created_at="2030-01-01T00:00:00+00:00"),
    )
    removed = store.purge(before="2025-01-01T00:00:00+00:00")
    assert removed == 1
    assert store.count("s") == 1


def test_purge_retains_null_created_at(store: HistoryStore):
    # Force a NULL created_at row by writing directly (append always stamps).
    with store._conn:
        store._conn.execute(
            "INSERT INTO conversation_history(session_id, kind, created_at, "
            "dedup_key) VALUES ('s', 'model_turn', NULL, 'k')",
        )
    removed = store.purge(before="2999-01-01T00:00:00+00:00")
    assert removed == 0
    assert store.count("s") == 1


def test_note_write_failure_sets_degraded(store: HistoryStore):
    assert store.degraded is False
    store.note_write_failure(sqlite3.OperationalError("disk full"))
    assert store.degraded is True
    assert store.write_failures == 1
    store.note_write_failure(OSError("still bad"))
    assert store.write_failures == 2  # counted, stays degraded


def test_corrupt_db_is_quarantined_and_recreated(tmp_path: Path):
    db = tmp_path / "history.db"
    db.write_bytes(b"this is not a sqlite database" * 50)
    store = HistoryStore(db)
    try:
        # The bad file was moved aside, a fresh store created in its place.
        assert store.quarantined_to is not None
        assert store.quarantined_to.exists()
        # The fresh store is usable.
        store.append(session_id="s", dedup_key="m1", entry=_entry("post"))
        assert store.count("s") == 1
    finally:
        store.close()
