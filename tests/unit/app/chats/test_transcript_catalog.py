# -*- coding: utf-8 -*-
"""Tests for catalog-routed per-session transcript databases."""

from __future__ import annotations

import concurrent.futures
import threading
from pathlib import Path

from qwenpaw.app.chats.transcript import TranscriptStore
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
    assert len(catalog._handles) == 1  # pylint: disable=protected-access
    catalog.close()


def test_lazily_migrates_one_session_from_shared_v3(tmp_path: Path) -> None:
    legacy = TranscriptStore(tmp_path / "transcript.db", retention_days=0)
    legacy.start_turn(
        session_id="legacy-session",
        user_id="user-1",
        channel="console",
        turn_id="legacy-turn",
        source="qwenpaw",
    )
    legacy.upsert_message(
        session_id="legacy-session",
        turn_id="legacy-turn",
        message=_message("legacy-message", "legacy"),
        ordinal=0,
    )
    legacy.close()

    catalog = TranscriptCatalog(tmp_path)
    page = catalog.get_page(
        session_id="legacy-session",
        user_id="user-1",
        channel="console",
    )

    assert page is not None
    assert [message.id for message in page.messages] == ["legacy-message"]
    row = catalog._conn.execute(  # pylint: disable=protected-access
        "SELECT migration_state, file_key FROM transcript_files "
        "WHERE session_id = 'legacy-session'",
    ).fetchone()
    assert row["migration_state"] == "migrated_v3"
    path = catalog._store_path(  # pylint: disable=protected-access
        row["file_key"],
    )
    assert path.is_file()
    assert (tmp_path / "transcript.db").is_file()
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


def test_deleted_legacy_session_cannot_be_migrated_again(
    tmp_path: Path,
) -> None:
    legacy = TranscriptStore(tmp_path / "transcript.db", retention_days=0)
    legacy.start_turn(
        session_id="legacy-session",
        user_id="user-1",
        channel="console",
        turn_id="legacy-turn",
        source="qwenpaw",
    )
    legacy.close()

    catalog = TranscriptCatalog(tmp_path)
    assert catalog.has_session("legacy-session") is True
    page = catalog.get_page(
        session_id="legacy-session",
        user_id="user-1",
        channel="console",
    )
    assert page is not None
    assert catalog.delete_session("legacy-session") is True
    assert catalog.has_session("legacy-session") is False
    assert (
        catalog.get_page(
            session_id="legacy-session",
            user_id="user-1",
            channel="console",
        )
        is None
    )
    catalog.close()
