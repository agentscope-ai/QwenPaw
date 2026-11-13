# -*- coding: utf-8 -*-
"""Canonical content, versioning and atomicity checks for block storage."""

import json
import sqlite3
from contextlib import closing

import pytest

from qwenpaw.app.chats.transcript import TranscriptStore
from qwenpaw.schemas import DataContent, Message, TextContent

IDENTITY = {"session_id": "session", "user_id": "user", "channel": "console"}


@pytest.fixture(name="store")
def transcript_store(tmp_path):
    value = TranscriptStore(tmp_path / "session.db")
    value.start_turn(**IDENTITY, turn_id="turn")
    yield value
    value.close()


def _save(store, message):
    store.upsert_message(
        session_id="session",
        turn_id="turn",
        ordinal=0,
        message=message,
    )


def _blocks(store):
    with closing(sqlite3.connect(store.path)) as connection, connection:
        return connection.execute(
            "SELECT block_id, version, payload_json FROM transcript_blocks "
            "ORDER BY ordinal",
        ).fetchall()


def test_blocks_reader_closes_connection(store, monkeypatch):
    connect = sqlite3.connect
    connections = []

    def track_connect(*args, **kwargs):
        connection = connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", track_connect)
    try:
        assert _blocks(store) == []
        assert len(connections) == 1
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connections[0].execute("SELECT 1")
    finally:
        for connection in connections:
            connection.close()


def test_bodies_have_one_source_and_stable_versions(store):
    message = Message(
        id="message",
        role="user",
        content=[
            TextContent(text="first"),
            DataContent(data={"output": "tool result"}),
        ],
    ).completed()
    _save(store, message)
    original = _blocks(store)
    with closing(sqlite3.connect(store.path)) as connection, connection:
        envelope = json.loads(
            connection.execute(
                "SELECT envelope_json FROM transcript_messages",
            ).fetchone()[0],
        )
    assert "content" not in envelope
    _save(store, message)
    assert _blocks(store) == original
    changed = message.model_copy(
        update={
            "content": [TextContent(text="changed"), message.content[1]],
        },
    )
    _save(store, changed)
    updated = _blocks(store)
    store.rebuild_projections()
    assert _blocks(store) == updated
    assert updated[0][0] == original[0][0]
    assert updated[0][1] == 2
    assert updated[1] == original[1]
    restored = store.get_page(**IDENTITY).messages[0]
    assert restored.content == changed.content
    _save(store, message.model_copy(update={"content": []}))
    assert _blocks(store) == []
    assert store.get_page(**IDENTITY).messages[0].content == []


def test_block_failure_rolls_back_message_envelope(store):
    original = Message(
        id="message",
        role="user",
        content=[TextContent(text="original")],
    ).completed()
    _save(store, original)
    with closing(sqlite3.connect(store.path)) as connection, connection:
        connection.executescript(
            """
            CREATE TRIGGER reject_block BEFORE UPDATE ON transcript_blocks
            BEGIN SELECT RAISE(ABORT, 'injected failure'); END;
        """,
        )
    with pytest.raises(sqlite3.IntegrityError, match="injected failure"):
        _save(
            store,
            original.model_copy(
                update={
                    "metadata": {"changed": True},
                    "content": [TextContent(text="replacement")],
                },
            ),
        )
    restored = store.get_page(**IDENTITY).messages[0]
    assert restored.content == original.content
    assert "changed" not in restored.metadata


def test_schema_rejects_duplicate_body_and_orphan_block(store):
    _save(store, Message(id="message", role="user", content=[]).completed())
    with closing(sqlite3.connect(store.path)) as connection, connection:
        connection.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE transcript_messages SET envelope_json = ?",
                ('{"content": []}',),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO transcript_blocks VALUES "
                "('session', 'missing', 'block', 0, 'text', 'hash', "
                "'{}', 2, 1)",
            )
