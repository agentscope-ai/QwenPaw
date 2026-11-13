# -*- coding: utf-8 -*-
"""Tests that mutable views can be recreated from conversation facts."""

import json
import sqlite3
from contextlib import closing

import pytest
from pathlib import Path

from qwenpaw.app.chats.transcript import TranscriptStore
from qwenpaw.agents.context.scroll.history import HistoryStore
from qwenpaw.agents.context.types import LogEntry
from qwenpaw.agents.context.scroll.memoryspace import MemorySpace
from qwenpaw.schemas import Message, TextContent

_IDENTITY = {
    "session_id": "session",
    "user_id": "user",
    "channel": "console",
}


def test_ui_and_runtime_projections_rebuild_from_events(
    tmp_path: Path,
) -> None:
    store = TranscriptStore(tmp_path / "session.db")
    message = Message(
        id="user-message",
        role="user",
        content=[TextContent(text="hello")],
    ).completed()
    state = {
        "agent": {
            "state": {
                "context": [{"role": "user", "content": "hello"}],
            },
        },
    }
    try:
        store.start_turn(**_IDENTITY, turn_id="turn")
        store.upsert_message(
            session_id="session",
            turn_id="turn",
            message=message,
            ordinal=0,
        )
        store.write_runtime_state(
            **_IDENTITY,
            turn_id="turn",
            state=state,
        )
        store.finish_turn(
            session_id="session",
            turn_id="turn",
            status="completed",
        )
        before = store.get_page(**_IDENTITY)
        assert before is not None
        with closing(sqlite3.connect(store.path)) as connection, connection:
            event_seq = connection.execute(
                "SELECT MAX(seq) FROM event_log",
            ).fetchone()[0]
            watermark = connection.execute(
                "SELECT last_event_seq FROM projection_watermarks "
                "WHERE projector_name = 'conversation'",
            ).fetchone()[0]
            assert watermark == event_seq
            projection_queries = {
                "transcript_messages": (
                    "SELECT * FROM transcript_messages ORDER BY rowid"
                ),
                "session_runtime": (
                    "SELECT * FROM session_runtime ORDER BY rowid"
                ),
                "current_context_revision": (
                    "SELECT * FROM current_context_revision ORDER BY rowid"
                ),
                "projection_turn_usage": (
                    "SELECT * FROM projection_turn_usage ORDER BY rowid"
                ),
            }
            raw_before = {
                table: connection.execute(query).fetchall()
                for table, query in projection_queries.items()
            }

        store.rebuild_projections()

        after = store.get_page(**_IDENTITY)
        runtime = store.read_runtime_state(**_IDENTITY)
        assert after == before
        assert runtime is not None
        assert runtime.state == state
        with closing(sqlite3.connect(store.path)) as connection, connection:
            raw_after = {
                table: connection.execute(query).fetchall()
                for table, query in projection_queries.items()
            }
        assert raw_after == raw_before
        assert [event.event_type for event in _events(store)] == [
            "session.created",
            "turn.started",
            "message.committed",
            "runtime.committed",
            "turn.completed",
        ]
    finally:
        store.close()


def _events(store: TranscriptStore):
    """Read raw events without exposing a production convenience API."""
    from qwenpaw.app.chats.event_store import ConversationEventStore

    reader = ConversationEventStore(store.path)
    try:
        return list(reader.iter_events())
    finally:
        reader.close()


def test_recall_projection_rebuilds_inside_the_session_db(
    tmp_path: Path,
) -> None:
    path = tmp_path / "session.db"
    store = TranscriptStore(path)
    try:
        store.write_runtime_state(**_IDENTITY, state={"agent": {}})
        history = HistoryStore(path)
        try:
            history.append(
                session_id="session",
                agent_id="agent",
                entry=LogEntry(
                    kind="model_turn",
                    role="user",
                    content="remember me",
                ),
                dedup_key="message-1",
            )
        finally:
            history.close()

        with closing(sqlite3.connect(path)) as connection, connection:
            event_seq = connection.execute(
                "SELECT MAX(seq) FROM event_log",
            ).fetchone()[0]
            watermark = connection.execute(
                "SELECT last_event_seq FROM projection_watermarks "
                "WHERE projector_name = 'conversation'",
            ).fetchone()[0]
            assert watermark == event_seq

        store.rebuild_projections()

        reader = HistoryStore(path)
        try:
            assert reader.count("session") == 1
            assert reader.contents_by_seqs({1}) == {1: "remember me"}
            assert reader.purge(before="9999-01-01T00:00:00+00:00") == 1
        finally:
            reader.close()
        store.rebuild_projections()
        rebuilt = HistoryStore(path)
        try:
            assert rebuilt.count("session") == 0
        finally:
            rebuilt.close()
    finally:
        store.close()


def test_legacy_history_import_is_exact_and_idempotent(tmp_path: Path) -> None:
    legacy_path = tmp_path / "history.db"
    legacy = HistoryStore(legacy_path)
    try:
        legacy.append(
            session_id="session",
            agent_id="original-agent",
            entry=LogEntry(
                kind="model_turn",
                role="user",
                content="legacy row",
            ),
            dedup_key="legacy-message",
        )
        legacy.append(
            session_id="another-session",
            entry=LogEntry(kind="model_turn", content="not imported"),
            dedup_key="other-message",
        )
    finally:
        legacy.close()

    path = tmp_path / "transcripts" / "session.db"
    store = TranscriptStore(path)
    try:
        store.write_runtime_state(**_IDENTITY, state={"agent": {}})
        history = HistoryStore(path)
        try:
            assert (
                history.import_legacy_database(
                    legacy_path,
                    session_id="session",
                    agent_id="fallback-agent",
                )
                == 1
            )
            assert (
                history.import_legacy_database(
                    legacy_path,
                    session_id="session",
                    agent_id="fallback-agent",
                )
                == 0
            )
            assert history.count("session") == 1
            assert history.count("another-session") == 0
        finally:
            history.close()
    finally:
        store.close()


@pytest.mark.parametrize(
    "collision",
    ["seq", "key", "content", "identity", "overlap", "exact"],
)
def test_legacy_recall_conflicts_survive_rebuild_restore_and_fork(
    tmp_path: Path,
    monkeypatch,
    collision: str,
) -> None:
    source = HistoryStore(tmp_path / "legacy.db")
    for seq in range(1, 4):
        source.append(
            session_id="session",
            dedup_key=f"message-{seq}",
            entry=LogEntry(
                kind="model_turn",
                role="user",
                content=f"SOURCE_{seq}",
                tool_call_id=f"tool-{seq}",
                blocks=[{"type": "text", "text": f"SOURCE_{seq}"}],
            ),
        )
    originals = [
        dict(row)
        for row in source._conn.execute(
            "SELECT * FROM conversation_history ORDER BY seq",
        )
    ]
    source.close()
    store = TranscriptStore(tmp_path / "session.db")
    history = HistoryStore(store.path)
    for seq in range(1, 4):
        store.start_turn(**_IDENTITY, turn_id=f"legacy:{seq}")
        store.upsert_message(
            session_id="session",
            turn_id=f"legacy:{seq}",
            ordinal=0,
            message=Message(
                id=f"message-{seq}",
                role="user",
                content=[TextContent(text=f"SOURCE_{seq}")],
            ).completed(),
        )
        store.finish_turn(
            session_id="session",
            turn_id=f"legacy:{seq}",
            status="completed",
        )
    before_migration_snapshot = store.export_database(**_IDENTITY)
    occupied = dict(originals[0])
    if collision != "exact":
        occupied["content"] = "DESTINATION_SECRET"
        occupied["blocks"] = '[{"type":"text","text":"BLOCK_SECRET"}]'
    if collision == "seq":
        occupied["dedup_key"] = "other"
    if collision == "key":
        occupied["seq"] = 4
    if collision == "identity":
        occupied["session_id"] = "other-session"
    if collision == "overlap":
        occupied["dedup_key"] = "message-2"
    with history._conn:
        history._conn.execute(
            "INSERT INTO conversation_history ("
            + ",".join(occupied)
            + ") VALUES ("
            + ",".join("?" for _ in occupied)
            + ")",
            tuple(occupied.values()),
        )
    with history._conn:
        history._rebuild_fts()
    mapping = {f"message-{i}": f"legacy:{i}" for i in range(1, 4)}
    if collision == "overlap":
        # Fail after mutation starts: archive, projection and marker roll back.
        with monkeypatch.context() as patch:

            def fail(**_kwargs):
                raise sqlite3.OperationalError("injected write failure")

            patch.setattr(history, "_append_conversation_fact", fail)
            with pytest.raises(sqlite3.OperationalError):
                history.import_legacy_database(
                    source.path,
                    session_id="session",
                    turn_by_key=mapping,
                )
        assert [
            dict(row)
            for row in history._conn.execute(
                "SELECT * FROM conversation_history",
            )
        ] == [occupied]
    history.import_legacy_database(
        source.path,
        session_id="session",
        turn_by_key=mapping,
    )
    before = [
        dict(row)
        for row in history._conn.execute(
            "SELECT * FROM conversation_history ORDER BY seq",
        )
    ]
    blocked = {
        row["seq"] for row in before if row["kind"] == "migration_conflict"
    }
    expected = {
        "seq": {1},
        "key": {1, 4},
        "content": {1},
        "identity": {1},
        "overlap": {1, 2},
        "exact": set(),
    }
    assert blocked == expected[collision]
    assert history.contents_by_seqs({3}) == {3: "SOURCE_3"}
    for seq in blocked:
        assert "unavailable" in history.contents_by_seqs({seq})[seq]
        history.update_entry(
            seq,
            content="OVERWRITE_SECRET",
            blocks=[],
            headline=None,
        )
    if blocked:
        assert (
            history.append(
                session_id="session",
                dedup_key="message-1",
                entry=LogEntry(kind="model_turn", content="RESUME_SECRET"),
            )
            in blocked
        )
    space = MemorySpace(history_db_path=store.path, session_id="session")
    try:
        assert "SECRET" not in json.dumps(space.expand(1, 4))
        assert not space.search("DESTINATION_SECRET")
        if blocked:
            assert not space.recall_tool("tool-1")
        for table in ("content_objects", "event_log"):
            with pytest.raises(sqlite3.DatabaseError):
                space.sql_query("SELECT * FROM hist." + table)
    finally:
        space.close()
    archived = []
    for row in history._conn.execute(
        "SELECT payload FROM content_objects WHERE codec='recall-entry-v1'",
    ):
        conflict = json.loads(row[0]).get("migration_conflict")
        if conflict:
            archived.extend(conflict["source_records"])
            archived.extend(conflict["destination_records"])
    if blocked:
        assert occupied in archived
        assert originals[0] in archived
    event_count = store._conn.execute(
        "SELECT COUNT(*) FROM event_log",
    ).fetchone()
    assert (
        history.import_legacy_database(
            source.path,
            session_id="session",
            turn_by_key=mapping,
        )
        == 0
    )
    assert (
        store._conn.execute("SELECT COUNT(*) FROM event_log").fetchone()
        == event_count
    )
    for seq in range(1, 4):
        store.write_runtime_state(
            **_IDENTITY,
            turn_id=f"legacy:{seq}",
            state={
                "agent": {
                    "scroll": {
                        "continuation_summary": "summary",
                        "index": {"session_id": "session"},
                    },
                },
                "turn": seq,
            },
            migration_approximate=True,
        )
    runtime = store.read_runtime_state(**_IDENTITY)
    history.close()
    store.rebuild_projections()
    history = HistoryStore(store.path)
    assert [
        dict(row)
        for row in history._conn.execute(
            "SELECT * FROM conversation_history ORDER BY seq",
        )
    ] == before
    assert store.read_runtime_state(**_IDENTITY) == runtime
    snapshot = store.export_database(**_IDENTITY)
    store.write_runtime_state(**_IDENTITY, state={"changed": True})
    store.restore_database(snapshot, **_IDENTITY)
    assert store.read_runtime_state(**_IDENTITY) == runtime
    child = TranscriptStore(tmp_path / "child.db")
    child.fork_completed_turn_from(
        source_path=store.path,
        source_session_id="session",
        source_chat_id="chat",
        turn_id="legacy:2",
        target_session_id="child",
        target_user_id="user",
        target_channel="console",
    )
    child_history = HistoryStore(child.path)
    assert child_history.existing_seqs({3, 4}) == set()
    if blocked:
        assert (
            child_history.append(
                session_id="child",
                dedup_key="message-1",
                entry=LogEntry(kind="model_turn", content="FORK_SECRET"),
            )
            == 1
        )
        assert "SECRET" not in json.dumps(
            child_history.contents_by_seqs({1, 2}),
        )
    child_history.close()
    child.close()
    history.close()
    store.restore_database(before_migration_snapshot, **_IDENTITY)
    store.rebuild_projections()
    assert (
        store._conn.execute(
            "SELECT COUNT(*) FROM conversation_history",
        ).fetchone()[0]
        == 0
    )
    store.restore_database(snapshot, **_IDENTITY)
    store.rebuild_projections()
    assert store.read_runtime_state(**_IDENTITY) == runtime
    assert [
        dict(row)
        for row in store._conn.execute(
            "SELECT * FROM conversation_history ORDER BY seq",
        )
    ] == before
    store.close()
