# -*- coding: utf-8 -*-
"""Tests for catalog-routed per-session transcript databases."""

from __future__ import annotations

import concurrent.futures
import sqlite3
import threading
from pathlib import Path

import pytest

from qwenpaw.app.chats.transcript import TranscriptCursor, TranscriptStore
from qwenpaw.app.chats.transcript_catalog import TranscriptCatalog
from qwenpaw.schemas import Message, TextContent


def _message(message_id: str, text: str) -> Message:
    return Message(
        id=message_id,
        role="user",
        content=[TextContent(text=text)],
    ).completed()


def _start(catalog: TranscriptCatalog, session_id: str) -> None:
    catalog.start_turn(
        session_id=session_id,
        user_id="user-1",
        channel="console",
        turn_id=f"turn-{session_id}",
        source="qwenpaw",
    )


def _upsert(catalog: TranscriptCatalog, session_id: str) -> None:
    catalog.upsert_message(
        session_id=session_id,
        turn_id=f"turn-{session_id}",
        message=_message(f"message-{session_id}", session_id),
        ordinal=0,
    )


def test_routes_sessions_to_hash_sharded_databases(tmp_path: Path) -> None:
    catalog = TranscriptCatalog(tmp_path)
    _start(catalog, "session/one")
    _start(catalog, "session-two")
    _upsert(catalog, "session/one")
    _upsert(catalog, "session-two")

    files = sorted((tmp_path / "transcripts").glob("*/*.db"))
    assert len(files) == 2
    assert all("session" not in path.name for path in files)
    assert all(len(path.parent.name) == 2 for path in files)

    first = catalog.get_page(
        session_id="session/one",
        user_id="user-1",
        channel="console",
    )
    second = catalog.get_page(
        session_id="session-two",
        user_id="user-1",
        channel="console",
    )
    assert first is not None
    assert second is not None
    assert [message.id for message in first.messages] == [
        "message-session/one",
    ]
    assert [message.id for message in second.messages] == [
        "message-session-two",
    ]
    catalog.close()


def test_file_key_hashes_the_complete_canonical_identity() -> None:
    # pylint: disable=protected-access
    first = TranscriptCatalog._file_key(
        session_id="same-session",
        user_id="user-1",
        channel="console",
    )
    second = TranscriptCatalog._file_key(
        session_id="same-session",
        user_id="user-2",
        channel="console",
    )
    repeated = TranscriptCatalog._file_key(
        session_id="same-session",
        user_id="user-1",
        channel="console",
    )
    # pylint: enable=protected-access

    assert first != second
    assert first == repeated
    assert len(first) == 64


def test_different_sessions_do_not_share_a_writer_lock(tmp_path: Path) -> None:
    catalog = TranscriptCatalog(tmp_path)
    _start(catalog, "session-a")
    _start(catalog, "session-b")
    entered = threading.Event()
    release = threading.Event()

    def hold_first_writer() -> None:
        with catalog._lease(  # pylint: disable=protected-access
            session_id="session-a",
            user_id="user-1",
            channel="console",
            create=False,
        ) as handle:
            assert handle is not None
            # pylint: disable-next=protected-access
            with handle.store._transaction():
                entered.set()
                assert release.wait(timeout=5)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(hold_first_writer)
        assert entered.wait(timeout=5)
        second = executor.submit(_upsert, catalog, "session-b")
        second.result(timeout=2)
        release.set()
        first.result(timeout=5)
    catalog.close()


def test_lru_reopens_evicted_session_without_losing_history(
    tmp_path: Path,
) -> None:
    catalog = TranscriptCatalog(tmp_path, max_open_stores=1)
    _start(catalog, "session-a")
    _upsert(catalog, "session-a")
    _start(catalog, "session-b")
    _upsert(catalog, "session-b")

    assert len(catalog._handles) == 1  # pylint: disable=protected-access
    page = catalog.get_page(
        session_id="session-a",
        user_id="user-1",
        channel="console",
    )
    assert page is not None
    assert [message.id for message in page.messages] == ["message-session-a"]
    # pylint: disable=protected-access
    assert len(catalog._handles) == 1
    handle = next(iter(catalog._handles.values()))
    assert handle.store._cleanup_executor is None
    # pylint: enable=protected-access
    catalog.close()


def test_catalog_ignores_unpublished_shared_transcript(
    tmp_path: Path,
) -> None:
    shared = TranscriptStore(tmp_path / "transcript.db", retention_days=0)
    shared.start_turn(
        session_id="shared-session",
        user_id="user-1",
        channel="console",
        turn_id="shared-turn",
        source="qwenpaw",
    )
    shared.upsert_message(
        session_id="shared-session",
        turn_id="shared-turn",
        message=_message("shared-message", "shared"),
        ordinal=0,
    )
    shared.close()

    catalog = TranscriptCatalog(tmp_path)
    page = catalog.get_page(
        session_id="shared-session",
        user_id="user-1",
        channel="console",
    )

    assert page is None
    assert catalog.has_session("shared-session") is False
    assert not list((tmp_path / "transcripts").glob("*/*.db"))
    catalog.close()


def test_catalog_v1_schema_upgrades_with_lineage_columns(
    tmp_path: Path,
) -> None:
    connection = sqlite3.connect(tmp_path / "transcript_catalog.db")
    connection.executescript(
        """
        CREATE TABLE transcript_files (
            session_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            channel TEXT NOT NULL,
            file_key TEXT NOT NULL UNIQUE,
            migration_state TEXT NOT NULL DEFAULT 'native'
                CHECK(migration_state IN ('native')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            deleted_at TEXT,
            purged_at TEXT
        );
        CREATE INDEX transcript_files_deleted
            ON transcript_files(deleted_at);
        CREATE TABLE transcript_imports (
            source_kind TEXT NOT NULL,
            source_identity TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            imported_at TEXT NOT NULL,
            result_json TEXT NOT NULL,
            PRIMARY KEY(
                source_kind, source_identity, fingerprint, schema_version
            )
        );
        PRAGMA user_version=1;
        """,
    )
    connection.close()

    catalog = TranscriptCatalog(tmp_path)

    columns = {
        row["name"]
        for row in catalog._conn.execute(  # pylint: disable=protected-access
            "PRAGMA table_info(transcript_files)",
        ).fetchall()
    }
    assert {
        "origin",
        "parent_session_id",
        "root_session_id",
        "source_revision",
        "migration_error",
    } <= columns
    assert (
        catalog._conn.execute(  # pylint: disable=protected-access
            "PRAGMA user_version",
        ).fetchone()[0]
        == 2
    )
    catalog.close()


def test_conversation_branch_materializes_at_message_anchor(
    tmp_path: Path,
) -> None:
    catalog = TranscriptCatalog(tmp_path)
    for number in range(1, 3):
        turn_id = f"parent-turn-{number}"
        catalog.start_turn(
            session_id="parent",
            user_id="user-1",
            channel="console",
            turn_id=turn_id,
            source="qwenpaw",
        )
        for ordinal in range(2):
            catalog.upsert_message(
                session_id="parent",
                turn_id=turn_id,
                message=_message(
                    f"parent-{number}-{ordinal}",
                    f"parent {number} {ordinal}",
                ),
                ordinal=ordinal,
            )
        catalog.finish_turn(
            session_id="parent",
            turn_id=turn_id,
            status="completed",
        )

    resolved = catalog.fork_session(
        parent_session_id="parent",
        child_session_id="child",
        child_user_id="user-1",
        child_channel="console",
        anchor=TranscriptCursor(turn_seq=1, ordinal=0),
    )

    assert resolved == TranscriptCursor(turn_seq=1, ordinal=0)
    child = catalog.get_page(
        session_id="child",
        user_id="user-1",
        channel="console",
    )
    assert child is not None
    assert [message.id for message in child.messages] == ["parent-1-0"]
    lineage = catalog._conn.execute(  # pylint: disable=protected-access
        "SELECT origin, parent_session_id, root_session_id, "
        "fork_turn_seq, fork_ordinal FROM transcript_files "
        "WHERE session_id = 'child'",
    ).fetchone()
    assert dict(lineage) == {
        "origin": "conversation_branch",
        "parent_session_id": "parent",
        "root_session_id": "parent",
        "fork_turn_seq": 1,
        "fork_ordinal": 0,
    }

    catalog.start_turn(
        session_id="child",
        user_id="user-1",
        channel="console",
        turn_id="child-turn",
        source="qwenpaw",
    )
    parent = catalog.get_page(
        session_id="parent",
        user_id="user-1",
        channel="console",
    )
    assert parent is not None
    assert len(parent.messages) == 4
    catalog.close()


def test_conversation_branch_does_not_wait_for_unrelated_writer(
    tmp_path: Path,
) -> None:
    catalog = TranscriptCatalog(tmp_path)
    _start(catalog, "parent")
    _upsert(catalog, "parent")
    _start(catalog, "unrelated")
    entered = threading.Event()
    release = threading.Event()

    def hold_unrelated_writer() -> None:
        with catalog._lease(  # pylint: disable=protected-access
            session_id="unrelated",
            user_id="user-1",
            channel="console",
            create=False,
        ) as handle:
            assert handle is not None
            # pylint: disable-next=protected-access
            with handle.store._transaction():
                entered.set()
                assert release.wait(timeout=5)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        held = executor.submit(hold_unrelated_writer)
        assert entered.wait(timeout=5)
        forked = executor.submit(
            catalog.fork_session,
            parent_session_id="parent",
            child_session_id="child",
            child_user_id="user-1",
            child_channel="console",
        )
        assert forked.result(timeout=2) == TranscriptCursor(
            turn_seq=1,
            ordinal=0,
        )
        release.set()
        held.result(timeout=5)
    catalog.close()


def test_invalid_branch_anchor_leaves_no_catalog_or_database(
    tmp_path: Path,
) -> None:
    catalog = TranscriptCatalog(tmp_path)
    _start(catalog, "parent")
    _upsert(catalog, "parent")

    with pytest.raises(ValueError, match="fork anchor does not exist"):
        catalog.fork_session(
            parent_session_id="parent",
            child_session_id="child",
            child_user_id="user-1",
            child_channel="console",
            anchor=TranscriptCursor(turn_seq=99, ordinal=0),
        )

    assert catalog.has_session("child") is False
    child_path = catalog._store_path(  # pylint: disable=protected-access
        catalog._file_key(  # pylint: disable=protected-access
            session_id="child",
            user_id="user-1",
            channel="console",
        ),
    )
    assert child_path.exists() is False
    catalog.close()


def test_delete_tombstones_catalog_before_removing_session_file(
    tmp_path: Path,
) -> None:
    catalog = TranscriptCatalog(tmp_path)
    _start(catalog, "session-a")
    _upsert(catalog, "session-a")
    row = catalog._conn.execute(  # pylint: disable=protected-access
        "SELECT file_key FROM transcript_files WHERE session_id = 'session-a'",
    ).fetchone()
    path = catalog._store_path(  # pylint: disable=protected-access
        row["file_key"],
    )

    assert catalog.mark_session_deleted("session-a") is True
    assert (
        catalog.get_page(
            session_id="session-a",
            user_id="user-1",
            channel="console",
        )
        is None
    )
    assert (
        catalog._purge_deleted_session(  # pylint: disable=protected-access
            "session-a",
        )
        is True
    )
    assert not path.exists()
    assert catalog.has_session("session-a") is False
    tombstone = catalog._conn.execute(  # pylint: disable=protected-access
        "SELECT deleted_at, purged_at FROM transcript_files "
        "WHERE session_id = 'session-a'",
    ).fetchone()
    assert tombstone["deleted_at"]
    assert tombstone["purged_at"]
    catalog.close()
