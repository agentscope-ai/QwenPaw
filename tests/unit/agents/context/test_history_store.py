# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access,unused-argument
"""Unit tests for the durable :class:`HistoryStore`.

Covers append + idempotency (the ``ux_dedup`` net behind resume/migration),
in-place ``update_entry`` with FTS sync, retention ``purge``, the degraded
durability flag, and corruption quarantine.
"""

import asyncio
import logging
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


def test_created_at_index_exists_for_date_filtered_recall(
    store: HistoryStore,
):
    indexes = {
        row["name"]
        for row in store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'",
        )
    }

    assert "ch_created_at" in indexes


def test_created_at_index_migrates_existing_populated_store(
    tmp_path: Path,
):
    """An upgrade backfills the new index without losing legacy rows."""
    db_path = tmp_path / "history.db"
    legacy = HistoryStore(db_path)
    with legacy._conn:
        legacy._conn.execute("DROP INDEX ch_created_at")
        legacy._conn.executemany(
            "INSERT INTO conversation_history"
            "(session_id, kind, created_at) VALUES (?, ?, ?)",
            [
                ("legacy", "model_turn", f"2024-01-{(i % 28) + 1:02d}")
                for i in range(5000)
            ],
        )
    legacy.close()

    migrated = HistoryStore(db_path)
    try:
        indexes = {
            row["name"]
            for row in migrated._conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'",
            )
        }
        assert "ch_created_at" in indexes
        assert migrated.count("legacy") == 5000
    finally:
        migrated.close()


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


def test_append_many_batches_and_deduplicates(store: HistoryStore):
    inserted = store.append_many(
        session_id="s",
        entries=[
            (_entry("one"), "m1"),
            (_entry("two"), "m2"),
            (_entry("duplicate"), "m1"),
        ],
    )
    assert inserted == 2
    assert store.count("s") == 2

    assert (
        store.append_many(
            session_id="s",
            entries=[(_entry("one again"), "m1")],
        )
        == 0
    )
    assert store.count("s") == 2


def test_append_many_populates_fts(store: HistoryStore):
    if not store._fts:
        pytest.skip("SQLite build lacks FTS5")
    store.append_many(
        session_id="s",
        entries=[(_entry("batch aardvark"), "m1")],
    )
    rows = store._conn.execute(
        "SELECT rowid FROM conversation_history_fts WHERE "
        "conversation_history_fts MATCH 'aardvark'",
    ).fetchall()
    assert len(rows) == 1


def test_same_dedup_key_different_session_does_not_collide(
    store: HistoryStore,
):
    a = store.append(session_id="s1", dedup_key="m1", entry=_entry())
    b = store.append(session_id="s2", dedup_key="m1", entry=_entry())
    assert a != b
    assert store.count("s1") == 1 and store.count("s2") == 1


def test_reconcile_rows_uses_exact_file_keys_and_claims_agent(
    store: HistoryStore,
):
    selected_seq = store.append(
        session_id="sync:shared-stem",
        agent_id=None,
        dedup_key="selected",
        entry=_entry("selected row"),
    )
    unrelated_seq = store.append(
        session_id="sync:shared-stem",
        agent_id=None,
        dedup_key="other-file",
        entry=_entry("unrelated row"),
    )

    moved, deduplicated, claimed = store.reconcile_session_rows(
        {"sync:shared-stem"},
        "canonical",
        {"selected"},
        agent_id="agent-1",
    )

    assert (moved, deduplicated, claimed) == (1, 0, 0)
    selected = store._conn.execute(
        "SELECT session_id, agent_id FROM conversation_history WHERE seq = ?",
        (selected_seq,),
    ).fetchone()
    assert tuple(selected) == ("canonical", "agent-1")
    unrelated = store._conn.execute(
        "SELECT session_id, agent_id FROM conversation_history WHERE seq = ?",
        (unrelated_seq,),
    ).fetchone()
    assert tuple(unrelated) == ("sync:shared-stem", None)


def test_reconcile_rows_deduplicates_source_and_fts(store: HistoryStore):
    if not store._fts:
        pytest.skip("SQLite build lacks FTS5")
    kept = store.append(
        session_id="canonical",
        dedup_key="shared",
        entry=_entry("canonical copy"),
    )
    duplicate = store.append(
        session_id="sync:file",
        dedup_key="shared",
        entry=_entry("legacy duplicate token"),
    )

    moved, deduplicated, claimed = store.reconcile_session_rows(
        {"sync:file"},
        "canonical",
        {"shared"},
    )

    assert (moved, deduplicated, claimed) == (0, 1, 0)
    assert store.count("sync:file") == 0
    assert store.count("canonical") == 1
    assert duplicate != kept
    hits = store._conn.execute(
        "SELECT rowid FROM conversation_history_fts "
        "WHERE conversation_history_fts MATCH 'legacy'",
    ).fetchall()
    assert hits == []


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


def test_purge_dry_run_reports_count_without_deleting(store: HistoryStore):
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
    would = store.purge(before="2025-01-01T00:00:00+00:00", dry_run=True)
    assert would == 1
    assert store.count("s") == 2  # nothing actually removed
    # A real purge then matches the previewed count.
    assert store.purge(before="2025-01-01T00:00:00+00:00") == 1
    assert store.count("s") == 1


def test_estimate_purge_reports_rows_and_bytes(store: HistoryStore):
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
    est = store.estimate_purge(before="2025-01-01T00:00:00+00:00")
    assert est["rows"] == 1
    assert est["content_bytes"] == len("ancient")
    # Estimating never deletes.
    assert store.count("s") == 2


def test_purge_kinds_drops_only_tool_output(store: HistoryStore):
    old = "2020-01-01T00:00:00+00:00"
    store.append(
        session_id="s",
        dedup_key="turn",
        entry=_entry("conversation", kind="model_turn", created_at=old),
    )
    store.append(
        session_id="s",
        dedup_key="result",
        entry=_entry("big tool output", kind="tool_result", created_at=old),
    )
    # Both rows are old, but kinds restricts the delete to tool output.
    est = store.estimate_purge(
        before="2025-01-01T00:00:00+00:00",
        kinds=("tool_result",),
    )
    assert est["rows"] == 1
    assert est["content_bytes"] == len("big tool output")

    removed = store.purge(
        before="2025-01-01T00:00:00+00:00",
        kinds=("tool_result",),
    )
    assert removed == 1
    assert store.count("s") == 1  # the conversation turn survives


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


class _NoFTSConn:
    """Delegates to a real connection but fails the FTS5 table creation,
    simulating a SQLite build without the FTS5 module."""

    def __init__(self, real):
        self._real = real

    def execute(self, sql, *args, **kwargs):
        if "CREATE VIRTUAL TABLE" in sql:
            raise sqlite3.OperationalError("no such module: fts5")
        return self._real.execute(sql, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)


@pytest.mark.usefixtures("capture_qwenpaw_logs")
def test_init_fts_degrades_and_warns_without_fts5(tmp_path: Path, caplog):
    """A SQLite build without FTS5 must not break the store: history.db still
    works and search degrades to LIKE, with one warning logged."""
    HistoryStore._fts_unavailable_warned = False  # reset the per-process flag
    store = HistoryStore(tmp_path / "history.db")
    real = store._conn
    try:
        store._conn = _NoFTSConn(real)
        with caplog.at_level(logging.WARNING):
            store._init_fts()
        assert store._fts is False
        assert any("FTS5" in r.getMessage() for r in caplog.records)

        # The store stays usable with FTS disabled: append + read still work.
        store._conn = real
        seq = store.append(session_id="s", dedup_key="x", entry=_entry("hi"))
        assert seq > 0
        assert store.count("s") == 1
    finally:
        store._conn = real
        store.close()
        HistoryStore._fts_unavailable_warned = False


def test_note_write_failure_sets_degraded(store: HistoryStore):
    assert store.degraded is False
    store.note_write_failure(sqlite3.OperationalError("disk full"))
    assert store.degraded is True
    assert store.write_failures == 1
    store.note_write_failure(OSError("still bad"))
    assert store.write_failures == 2  # counted, stays degraded


def test_append_works_from_a_worker_thread(store: HistoryStore):
    """The write-through in compress is offloaded via asyncio.to_thread, so
    the connection (opened check_same_thread=False, guarded by its lock) must
    be usable from a thread other than the one that created it — a plain
    sqlite3 connection would raise ProgrammingError here."""
    store.append(session_id="s", dedup_key="loop", entry=_entry("on-thread"))

    async def drive():
        # Runs the blocking append on a worker thread, exactly as
        # ScrollContextManager._persist_guarded_async does.
        return await asyncio.to_thread(
            store.append,
            session_id="s",
            dedup_key="worker",
            entry=_entry("off-thread"),
        )

    seq = asyncio.run(drive())
    assert seq > 0
    assert store.count("s") == 2


def test_concurrent_threaded_appends_are_serialized(store: HistoryStore):
    """The lock must let many worker-thread appends land without corruption or
    a cross-thread SQLite error — every distinct dedup_key gets its own row."""

    async def drive():
        await asyncio.gather(
            *(
                asyncio.to_thread(
                    store.append,
                    session_id="s",
                    dedup_key=f"k{i}",
                    entry=_entry(f"row-{i}"),
                )
                for i in range(25)
            ),
        )

    asyncio.run(drive())
    assert store.count("s") == 25


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


@pytest.mark.parametrize("legacy_rebuild", [False, True])
def test_purge_recall_rows_preserves_search_exclusion(store, legacy_rebuild):
    if not store._fts:
        pytest.skip("SQLite build lacks FTS5")
    store.append(
        session_id="s",
        entry=_entry("expired", created_at="2020-01-01"),
    )
    for name in ("recall_history", "recall_history_python"):
        store.append(
            session_id="s",
            entry=_entry("recall output", name=name, created_at="2020-01-01"),
        )
    recent = store.append(
        session_id="s",
        entry=_entry("zebra", created_at="2099-01-01"),
    )
    if legacy_rebuild:
        with store._conn:
            store._conn.execute(
                "INSERT INTO conversation_history_fts"
                "(conversation_history_fts) VALUES('rebuild')",
            )
    assert store.purge(before="2026-01-01", dry_run=True) == 3
    assert store.count("s") == 4
    assert store.purge(before="2026-01-01") == 3
    assert store.count("s") == 1
    assert _fts_hits(store, "zebra") == [recent]
    assert _fts_hits(store, "recall") == []
    with store._conn:
        store._check_fts()


def _fts_hits(store, term):
    return [
        row[0]
        for row in store._conn.execute(
            "SELECT rowid FROM conversation_history_fts "
            "WHERE conversation_history_fts MATCH ?",
            (term,),
        )
    ]


@pytest.mark.parametrize(
    "old_name,new_name",
    [
        (None, "recall_history"),
        ("recall_history", None),
        ("recall_history_python", "recall_history"),
    ],
)
def test_update_moves_into_and_out_of_search(store, old_name, new_name):
    seq = store.append(session_id="s", entry=_entry("aardvark", name=old_name))
    store.update_entry(
        seq,
        content="zebra",
        name=new_name,
        headline=None,
        blocks=None,
    )
    assert _fts_hits(store, "aardvark") == []
    assert _fts_hits(store, "zebra") == ([seq] if new_name is None else [])
    assert store.count("s") == 1


def test_reconcile_unindexed_recall_duplicate(store):
    for session in ("canonical", "source"):
        store.append(
            session_id=session,
            dedup_key="same",
            entry=_entry("recall output", name="recall_history"),
        )
    assert store.reconcile_session_rows(
        {"source"},
        "canonical",
        {"same"},
    ) == (0, 1, 0)
    assert store.count("canonical") == 1
    assert store.count("source") == 0


def _damage_fts(store):
    with store._conn:
        store._conn.execute(
            "UPDATE conversation_history_fts_data SET block=x'00' WHERE id>10",
        )


@pytest.mark.parametrize("reopen", [False, True, "fts_only"])
def test_fts_repair_preserves_history_and_exclusions(
    tmp_path,
    reopen,
    monkeypatch,
):
    path = tmp_path / "history.db"
    store = HistoryStore(path)
    try:
        if not store._fts:
            pytest.skip("SQLite build lacks FTS5")
        store.append(
            session_id="s",
            entry=_entry("expired", created_at="2020-01-01"),
        )
        recent = store.append(
            session_id="s",
            entry=_entry("zebra", created_at="2099-01-01"),
        )
        store.append(
            session_id="s",
            entry=_entry(
                "aardvark",
                name="recall_history",
                created_at="2099-01-01",
            ),
        )
        if reopen:
            _damage_fts(store)
            store.close()
            if reopen == "fts_only":
                # Emulate builds/damage where quick_check misses FTS damage.
                original_connect = sqlite3.connect

                class QuickCheckPasses(sqlite3.Connection):
                    def execute(self, sql, *args, **kwargs):
                        if sql == "PRAGMA quick_check":
                            sql = "SELECT 'ok'"
                        return super().execute(sql, *args, **kwargs)

                def connect(*args, **kwargs):
                    return original_connect(
                        *args,
                        factory=QuickCheckPasses,
                        **kwargs,
                    )

                monkeypatch.setattr(sqlite3, "connect", connect)
            store = HistoryStore(path)
            assert store.count("s") == 3
            assert store.quarantined_to is None
        else:
            # Simulate a missing index with intact external content. FTS
            # delete will fail even though the internal integrity check passes.
            with store._conn:
                store._conn.execute(
                    "INSERT INTO conversation_history_fts"
                    "(conversation_history_fts) VALUES('delete-all')",
                )
            assert store.purge(before="2026-01-01", dry_run=True) == 1
            assert _fts_hits(store, "zebra") == []
        assert store.purge(before="2026-01-01") == 1
        assert store.count("s") == 2
        assert _fts_hits(store, "zebra") == [recent]
        assert _fts_hits(store, "aardvark") == []
        assert _fts_hits(store, "expired") == []
        with store._conn:
            store._check_fts()
        assert not list(tmp_path.glob("*.corrupt-*"))
    finally:
        store.close()


def test_failed_repair_rolls_back_purge(store, monkeypatch):
    for word in ("aardvark", "zebra"):
        store.append(
            session_id="s",
            entry=_entry(word, created_at="2020-01-01"),
        )
    original = store._delete_fts_row
    calls = []

    def delete(row):
        calls.append(row["seq"])
        if len(calls) == 2:
            error = sqlite3.DatabaseError("database disk image is malformed")
            error.sqlite_errorcode = sqlite3.SQLITE_CORRUPT_VTAB
            raise error
        original(row)

    def rebuild():
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(store, "_delete_fts_row", delete)
    monkeypatch.setattr(store, "_rebuild_fts", rebuild)
    with pytest.raises(RuntimeError, match="history preserved"):
        store.purge(before="2026-01-01")
    assert store.count("s") == 2
    assert len(_fts_hits(store, "aardvark")) == 1
    assert len(_fts_hits(store, "zebra")) == 1
    assert not store._conn.in_transaction


def test_purge_operational_error_does_not_repair(store, monkeypatch):
    store.append(session_id="s", entry=_entry(created_at="2020-01-01"))

    def delete(row):
        raise sqlite3.OperationalError("database is locked")

    def repair():
        pytest.fail("Must not rebuild for an operational error")

    monkeypatch.setattr(store, "_delete_fts_row", delete)
    monkeypatch.setattr(store, "_repair_fts", repair)
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        store.purge(before="2026-01-01")
    assert store.count("s") == 1


def test_purge_retries_only_once(store, monkeypatch):
    store.append(session_id="s", entry=_entry(created_at="2020-01-01"))
    calls = []

    def delete(row):
        calls.append(row["seq"])
        error = sqlite3.DatabaseError("database disk image is malformed")
        error.sqlite_errorcode = sqlite3.SQLITE_CORRUPT_VTAB
        raise error

    monkeypatch.setattr(store, "_delete_fts_row", delete)
    with pytest.raises(sqlite3.DatabaseError):
        store.purge(before="2026-01-01")
    assert len(calls) == 2
    assert store.count("s") == 1


def test_startup_failed_fts_repair_preserves_file(tmp_path, monkeypatch):
    path = tmp_path / "history.db"
    store = HistoryStore(path)
    store.append(session_id="s", entry=_entry("aardvark"))
    _damage_fts(store)
    store.close()

    def rebuild(self):
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(HistoryStore, "_rebuild_fts", rebuild)
    with pytest.raises(RuntimeError, match="history preserved"):
        HistoryStore(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT content FROM conversation_history",
        ).fetchone() == ("aardvark",)
    assert not list(tmp_path.glob("*.corrupt-*"))


def test_initial_fts_backfill_excludes_recall(tmp_path):
    path = tmp_path / "history.db"
    store = HistoryStore(path)
    store.append(session_id="s", entry=_entry("zebra"))
    store.append(
        session_id="s",
        entry=_entry("aardvark", name="recall_history"),
    )
    with store._conn:
        store._conn.execute("DROP TABLE conversation_history_fts")
    store.close()
    store = HistoryStore(path)
    try:
        assert store.count("s") == 2
        assert len(_fts_hits(store, "zebra")) == 1
        assert _fts_hits(store, "aardvark") == []
    finally:
        store.close()


def test_startup_lock_does_not_quarantine(tmp_path):
    path = tmp_path / "history.db"
    store = HistoryStore(path)
    store.append(session_id="s", entry=_entry("aardvark"))
    store.close()
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("BEGIN EXCLUSIVE")
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            HistoryStore(path)
        assert conn.execute(
            "SELECT content FROM conversation_history",
        ).fetchone() == ("aardvark",)
    assert not list(tmp_path.glob("*.corrupt-*"))


def test_startup_fts_check_defers_while_wal_writer_is_active(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "history.db"
    initial = HistoryStore(path)
    initial.append(session_id="s", entry=_entry("aardvark"))
    initial.close()
    original_check = HistoryStore._check_fts
    attempts = []

    def check(store):
        # Only the optional probe gets a zero wait, not normal writes/repair.
        assert store._conn.execute("PRAGMA busy_timeout").fetchone()[0] == 0
        try:
            original_check(store)
        except sqlite3.DatabaseError as exc:
            attempts.append(exc.sqlite_errorcode & 0xFF)
            raise
        attempts.append("ok")

    monkeypatch.setattr(HistoryStore, "_check_fts", check)
    writer = sqlite3.connect(path)
    opened = None
    try:
        writer.execute("BEGIN IMMEDIATE")
        opened = HistoryStore(path)
        assert attempts == [sqlite3.SQLITE_BUSY]
        assert opened.count("s") == 1
        assert _fts_hits(opened, "aardvark")
        assert opened.quarantined_to is None
        assert opened._fts is True
        assert not opened._conn.in_transaction
        assert (
            opened._conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        )
        writer.rollback()
        opened.append(session_id="s", entry=_entry("zebra"))
        assert opened.count("s") == 2
    finally:
        writer.close()
        if opened is not None:
            opened.close()
    reopened = HistoryStore(path)
    try:
        assert attempts == [sqlite3.SQLITE_BUSY, "ok"]
        assert reopened.count("s") == 2
    finally:
        reopened.close()
    assert not list(tmp_path.glob("*.corrupt-*"))


@pytest.mark.parametrize(
    "code,deferred",
    [
        (sqlite3.SQLITE_LOCKED, True),
        (sqlite3.SQLITE_LOCKED_SHAREDCACHE, True),
        (sqlite3.SQLITE_BUSY_SNAPSHOT, True),
        (sqlite3.SQLITE_IOERR, False),
        (sqlite3.SQLITE_FULL, False),
    ],
)
def test_startup_fts_defers_only_contention(
    tmp_path,
    monkeypatch,
    code,
    deferred,
):
    path = tmp_path / "history.db"
    HistoryStore(path).close()

    def check(store):
        error = sqlite3.OperationalError("synthetic FTS check error")
        error.sqlite_errorcode = code
        raise error

    def repair(store):
        pytest.fail("Operational errors must not trigger FTS repair")

    monkeypatch.setattr(HistoryStore, "_check_fts", check)
    monkeypatch.setattr(HistoryStore, "_repair_fts", repair)
    if deferred:
        store = HistoryStore(path)
        try:
            assert store._fts is True
            assert not store._conn.in_transaction
            assert (
                store._conn.execute("PRAGMA busy_timeout").fetchone()[0]
                == 5000
            )
        finally:
            store.close()
    else:
        with pytest.raises(sqlite3.OperationalError, match="synthetic"):
            HistoryStore(path)
    assert not list(tmp_path.glob("*.corrupt-*"))


_FTS_QUICK_CHECK_DIAGNOSTICS = [
    "malformed inverted index for FTS5 table main.conversation_history_fts",
    "fts5: corruption found reading blob 137438953473 "
    'from table "conversation_history_fts"',
]


@pytest.mark.parametrize("diagnostic", _FTS_QUICK_CHECK_DIAGNOSTICS)
@pytest.mark.parametrize("repair_fails", [False, True])
def test_quick_check_fts_diagnostic_preserves_source(
    tmp_path,
    monkeypatch,
    diagnostic,
    repair_fails,
):
    path = tmp_path / "history.db"
    store = HistoryStore(path)
    store.append(session_id="s", entry=_entry("zebra"))
    _damage_fts(store)
    store.close()
    original_connect = sqlite3.connect
    original_rebuild = HistoryStore._rebuild_fts
    checks = []
    rebuilds = []

    class DiagnosticConnection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if sql == "PRAGMA quick_check":
                checks.append(sql)
                if len(checks) == 1:
                    return super().execute("SELECT ?", (diagnostic,))
            return super().execute(sql, *args, **kwargs)

    def connect(*args, **kwargs):
        return original_connect(*args, factory=DiagnosticConnection, **kwargs)

    def rebuild(history):
        rebuilds.append(history.path)
        if repair_fails:
            raise sqlite3.OperationalError("disk full")
        original_rebuild(history)

    monkeypatch.setattr(sqlite3, "connect", connect)
    monkeypatch.setattr(HistoryStore, "_rebuild_fts", rebuild)
    if repair_fails:
        with pytest.raises(RuntimeError, match="history preserved"):
            HistoryStore(path)
    else:
        reopened = HistoryStore(path)
        try:
            assert reopened.quarantined_to is None
            assert reopened.count("s") == 1
            assert len(_fts_hits(reopened, "zebra")) == 1
            assert len(checks) == 2
        finally:
            reopened.close()
    assert rebuilds == [path]
    conn = original_connect(path)
    try:
        assert conn.execute(
            "SELECT content FROM conversation_history",
        ).fetchall() == [("zebra",)]
    finally:
        conn.close()
    assert not list(tmp_path.glob("*.corrupt-*"))


@pytest.mark.parametrize(
    "results",
    [
        [],
        ["ok"],
        [_FTS_QUICK_CHECK_DIAGNOSTICS[1], "invalid page number 99"],
        ['fts5: corruption found reading blob 123 from table "other_fts"'],
        [
            "fts5: corruption found reading blob 123 "
            'from table "conversation_history_fts_other"',
        ],
    ],
)
def test_quick_check_does_not_misclassify_other_corruption(results):
    assert not HistoryStore._is_fts_only_corruption(results)


def test_quick_check_persistent_fts_damage_is_not_quarantined(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "history.db"
    HistoryStore(path).close()
    original_connect = sqlite3.connect
    checks = []

    class PersistentDiagnosticConnection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if sql == "PRAGMA quick_check":
                checks.append(sql)
                return super().execute(
                    "SELECT ?",
                    (_FTS_QUICK_CHECK_DIAGNOSTICS[1],),
                )
            return super().execute(sql, *args, **kwargs)

    def connect(*args, **kwargs):
        return original_connect(
            *args,
            factory=PersistentDiagnosticConnection,
            **kwargs,
        )

    monkeypatch.setattr(sqlite3, "connect", connect)
    with pytest.raises(RuntimeError, match="history preserved"):
        HistoryStore(path)
    assert len(checks) == 2
    assert not list(tmp_path.glob("*.corrupt-*"))
