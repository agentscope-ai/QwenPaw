# -*- coding: utf-8 -*-
"""Tests that mutable views can be recreated from conversation facts."""

import sqlite3
from pathlib import Path

from qwenpaw.app.chats.transcript import TranscriptStore
from qwenpaw.agents.context.scroll.history import HistoryStore
from qwenpaw.agents.context.types import LogEntry
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
        with sqlite3.connect(store.path) as connection:
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
        with sqlite3.connect(store.path) as connection:
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

        with sqlite3.connect(path) as connection:
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
