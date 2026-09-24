# -*- coding: utf-8 -*-
"""Tests for catalog-routed per-session transcript databases."""

from __future__ import annotations

import concurrent.futures
import threading
from pathlib import Path

import pytest

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
    )


def _upsert(catalog: TranscriptCatalog, session_id: str) -> None:
    catalog.upsert_message(
        session_id=session_id,
        turn_id=f"turn-{session_id}",
        message=_message(f"message-{session_id}", session_id),
        ordinal=0,
    )


def _finish(catalog: TranscriptCatalog, session_id: str) -> None:
    catalog.finish_turn(
        session_id=session_id,
        turn_id=f"turn-{session_id}",
        status="completed",
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


def test_idle_handles_close_without_losing_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = TranscriptCatalog(tmp_path)
    _start(catalog, "session-a")
    handle = catalog._handles["session-a"]  # pylint: disable=protected-access
    _upsert(catalog, "session-a")
    assert (  # pylint: disable=protected-access
        catalog._handles["session-a"] is handle
    )
    _finish(catalog, "session-a")
    assert not catalog._handles  # pylint: disable=protected-access
    monkeypatch.setattr(
        TranscriptStore,
        "_create_schema",
        lambda _store: pytest.fail("existing store recreated its schema"),
    )
    page = catalog.get_page(
        session_id="session-a",
        user_id="user-1",
        channel="console",
    )
    assert page is not None
    assert [message.id for message in page.messages] == ["message-session-a"]
    assert not catalog._handles  # pylint: disable=protected-access
    catalog.close()


def test_reopen_cancels_orphaned_running_turn(tmp_path: Path) -> None:
    catalog = TranscriptCatalog(tmp_path)
    _start(catalog, "session-a")
    _upsert(catalog, "session-a")
    catalog.upsert_message(
        session_id="session-a",
        turn_id="turn-session-a",
        message=Message(
            id="assistant-session-a",
            role="assistant",
            content=[TextContent(text="partial reply")],
        ).completed(),
        ordinal=1,
    )
    catalog.close()

    reopened = TranscriptCatalog(tmp_path)
    page = reopened.get_page(
        session_id="session-a",
        user_id="user-1",
        channel="console",
    )

    assert page is not None
    assert [message.id for message in page.messages] == [
        "message-session-a",
        "assistant-session-a",
    ]
    assert page.messages[0].metadata is not None
    assert page.messages[0].metadata["qwenpaw_turn_state"]["status"] == (
        "canceled"
    )
    reopened.close()


def test_delete_waits_for_active_lease(tmp_path: Path) -> None:
    catalog = TranscriptCatalog(tmp_path)
    _start(catalog, "session-a")
    entered = threading.Event()
    delete_started = threading.Event()
    release = threading.Event()

    def hold_lease() -> None:
        with catalog._lease(  # pylint: disable=protected-access
            session_id="session-a",
            user_id="user-1",
            channel="console",
            create=False,
        ):
            entered.set()
            assert release.wait(timeout=5)

    def delete_session() -> bool:
        delete_started.set()
        return catalog.delete_session("session-a")

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        lease = executor.submit(hold_lease)
        assert entered.wait(timeout=5)
        deletion = executor.submit(delete_session)
        assert delete_started.wait(timeout=5)
        with pytest.raises(concurrent.futures.TimeoutError):
            deletion.result(timeout=0.1)
        release.set()
        lease.result(timeout=5)
        assert deletion.result(timeout=5) is True

    assert (
        catalog.get_page(
            session_id="session-a",
            user_id="user-1",
            channel="console",
        )
        is None
    )
    assert catalog.delete_session("session-a") is False
    catalog.close()


def test_failed_turn_write_releases_handle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = TranscriptCatalog(tmp_path)
    _start(catalog, "session-a")
    handle = catalog._handles["session-a"]  # pylint: disable=protected-access

    def fail_write(**_kwargs) -> None:
        raise RuntimeError("write failed")

    monkeypatch.setattr(handle.store, "upsert_message", fail_write)
    with pytest.raises(RuntimeError, match="write failed"):
        _upsert(catalog, "session-a")

    assert not catalog._handles  # pylint: disable=protected-access
    catalog.close()
