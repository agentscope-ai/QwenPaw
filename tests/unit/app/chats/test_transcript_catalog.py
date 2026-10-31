# -*- coding: utf-8 -*-
"""Tests for catalog-routed per-session transcript databases."""

from __future__ import annotations

import concurrent.futures
import json
import sqlite3
import threading
from pathlib import Path

import pytest

from qwenpaw.app.chats import transcript_schema
from qwenpaw.app.chats.transcript import TranscriptStore
from qwenpaw.app.chats.models import ChatSpec
from qwenpaw.app.chats.transcript_catalog import TranscriptCatalog
from qwenpaw.agents.context.scroll.history import HistoryStore
from qwenpaw.agents.context.types import LogEntry
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


def test_routes_sessions_to_storage_id_databases(tmp_path: Path) -> None:
    catalog = TranscriptCatalog(tmp_path)
    _start(catalog, "session/one")
    _start(catalog, "session-two")
    _upsert(catalog, "session/one")
    _upsert(catalog, "session-two")

    files = sorted((tmp_path / "transcripts").glob("*.db"))
    assert len(files) == 2
    assert all("session" not in path.name for path in files)
    assert all(len(path.stem) == 36 for path in files)

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


def test_catalog_rebuilds_direct_path_and_allows_shared_session_id(
    tmp_path: Path,
) -> None:
    storage_id = "11111111-1111-4111-8111-111111111111"
    chat = ChatSpec(
        storage_id=storage_id,
        session_id="shared-group",
        user_id="user-a",
        channel="feishu",
    )
    chat_b = ChatSpec(
        storage_id="22222222-2222-4222-8222-222222222222",
        session_id="shared-group",
        user_id="user-b",
        channel="feishu",
    )
    (tmp_path / "chats.json").write_text(
        json.dumps(
            {
                "version": 1,
                "chats": [
                    chat.model_dump(mode="json"),
                    chat_b.model_dump(mode="json"),
                ],
            },
        ),
        encoding="utf-8",
    )
    catalog = TranscriptCatalog(tmp_path)
    catalog.start_turn(
        session_id="shared-group",
        user_id="user-a",
        channel="feishu",
        turn_id="turn-a",
    )
    catalog.start_turn(
        session_id="shared-group",
        user_id="user-b",
        channel="feishu",
        turn_id="turn-b",
    )
    with pytest.raises(ValueError, match="ambiguous"):
        catalog.finish_turn(
            session_id="shared-group",
            turn_id="turn-a",
            status="completed",
        )
    catalog.finish_turn(
        session_id="shared-group",
        user_id="user-a",
        channel="feishu",
        turn_id="turn-a",
        status="completed",
    )
    catalog.finish_turn(
        session_id="shared-group",
        user_id="user-b",
        channel="feishu",
        turn_id="turn-b",
        status="completed",
    )
    assert (tmp_path / "transcripts" / f"{storage_id}.db").is_file()
    catalog.close()

    (tmp_path / "transcript_catalog.db").unlink()
    reopened = TranscriptCatalog(tmp_path)
    try:
        assert reopened.has_session(
            session_id="shared-group",
            user_id="user-a",
            channel="feishu",
        )
        assert reopened.has_session(
            session_id="shared-group",
            user_id="user-b",
            channel="feishu",
        )
    finally:
        reopened.close()


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
    row = catalog._resolve_catalog_row(  # pylint: disable=protected-access
        session_id="session-a",
    )
    storage_id = str(row["storage_id"])
    handle = catalog._handles[storage_id]  # pylint: disable=protected-access
    _upsert(catalog, "session-a")
    assert (  # pylint: disable=protected-access
        catalog._handles[storage_id] is handle
    )
    _finish(catalog, "session-a")
    assert not catalog._handles  # pylint: disable=protected-access
    monkeypatch.setattr(
        transcript_schema,
        "SCHEMA",
        "INVALID SQL: existing store must not recreate its schema",
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


def test_page_forwards_content_block_limit(tmp_path: Path) -> None:
    catalog = TranscriptCatalog(tmp_path)
    _start(catalog, "session-a")
    catalog.upsert_message(
        session_id="session-a",
        turn_id="turn-session-a",
        message=Message(
            id="message-a",
            role="assistant",
            content=[
                TextContent(text="first"),
                TextContent(text="second"),
                TextContent(text="third"),
            ],
        ).completed(),
        ordinal=0,
    )
    _finish(catalog, "session-a")

    newest = catalog.get_page(
        session_id="session-a",
        user_id="user-1",
        channel="console",
        max_content_blocks=2,
    )
    assert newest is not None
    assert [block.text for block in newest.messages[0].content] == [
        "second",
        "third",
    ]
    assert newest.has_more is True
    assert newest.next_before is not None

    older = catalog.get_page(
        session_id="session-a",
        user_id="user-1",
        channel="console",
        before=newest.next_before,
        max_content_blocks=2,
    )
    assert older is not None
    assert [block.text for block in older.messages[0].content] == ["first"]
    assert older.has_more is False
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


def test_read_only_catalog_does_not_recover_running_turn(
    tmp_path: Path,
) -> None:
    writer = TranscriptCatalog(tmp_path)
    _start(writer, "session-a")
    _upsert(writer, "session-a")
    writer.upsert_message(
        session_id="session-a",
        turn_id="turn-session-a",
        message=Message(
            id="assistant-session-a",
            role="assistant",
            content=[TextContent(text="partial reply")],
        ).completed(),
        ordinal=1,
    )

    reader = TranscriptCatalog(
        tmp_path,
        recover_orphaned_turns=False,
    )
    page = reader.get_page(
        session_id="session-a",
        user_id="user-1",
        channel="console",
    )

    assert page is not None
    assert [message.id for message in page.messages] == [
        "message-session-a",
    ]
    reader.close()
    writer.finish_turn(
        session_id="session-a",
        turn_id="turn-session-a",
        status="cancelled",
    )
    writer.close()


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


def test_delete_retries_after_database_unlink_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = TranscriptCatalog(tmp_path)
    _start(catalog, "session-a")
    _finish(catalog, "session-a")
    database = next((tmp_path / "transcripts").glob("*.db"))
    unlink = Path.unlink
    failed = False

    def fail_once(path: Path, *args, **kwargs) -> None:
        nonlocal failed
        if path == database and not failed:
            failed = True
            raise OSError("database is busy")
        unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_once)
    with pytest.raises(OSError, match="database is busy"):
        catalog.delete_session("session-a", "user-1", "console")
    assert catalog.has_session(
        session_id="session-a",
        user_id="user-1",
        channel="console",
    )
    assert database.exists()
    assert catalog.delete_session("session-a", "user-1", "console")
    assert not database.exists()
    catalog.close()


def test_failed_turn_write_releases_handle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = TranscriptCatalog(tmp_path)
    _start(catalog, "session-a")
    row = catalog._resolve_catalog_row(  # pylint: disable=protected-access
        session_id="session-a",
    )
    storage_id = str(row["storage_id"])
    handle = catalog._handles[storage_id]  # pylint: disable=protected-access

    def fail_write(**_kwargs) -> None:
        raise RuntimeError("write failed")

    monkeypatch.setattr(handle.store, "upsert_message", fail_write)
    with pytest.raises(RuntimeError, match="write failed"):
        _upsert(catalog, "session-a")

    assert not catalog._handles  # pylint: disable=protected-access
    catalog.close()


def test_clone_session_copies_completed_history_and_agent_runtime(
    tmp_path: Path,
) -> None:
    catalog = TranscriptCatalog(tmp_path)
    _start(catalog, "parent")
    _upsert(catalog, "parent")
    catalog.write_runtime_state(
        session_id="parent",
        user_id="user-1",
        channel="console",
        state={
            "agent": {"state": {"summary": "turn boundary"}},
            "mode_state": {"mission": {"active": True}},
        },
        turn_id="turn-parent",
    )
    source_id = catalog.storage_id_for(
        session_id="parent",
        user_id="user-1",
        channel="console",
    )
    history = HistoryStore(tmp_path / "transcripts" / (source_id + ".db"))
    history.append(
        session_id="parent",
        entry=LogEntry(kind="model_turn", content="recall before clone"),
        dedup_key="clone-recall",
    )
    history.close()
    _finish(catalog, "parent")
    catalog.replace_runtime_state(
        session_id="parent",
        user_id="user-1",
        channel="console",
        state={
            "agent": {"state": {"summary": "copied"}},
            "mode_state": {"mission": {"active": True}},
        },
        context_generation=3,
        current_usage={"usage": {"total_tokens": 12}},
    )
    catalog.start_turn(
        session_id="parent",
        user_id="user-1",
        channel="console",
        turn_id="running-turn",
    )
    catalog.upsert_message(
        session_id="parent",
        turn_id="running-turn",
        message=_message("running-message", "partial"),
        ordinal=0,
    )

    assert catalog.clone_session(
        source_session_id="parent",
        source_user_id="user-1",
        source_channel="console",
        target_session_id="child",
        target_user_id="user-1",
        target_channel="console",
    )

    page = catalog.get_page(
        session_id="child",
        user_id="user-1",
        channel="console",
    )
    assert page is not None
    assert [message.id for message in page.messages] == ["message-parent"]
    runtime = catalog.read_runtime_state(
        session_id="child",
        user_id="user-1",
        channel="console",
    )
    assert runtime is not None
    assert runtime.context_generation == 3
    assert runtime.state == {"agent": {"state": {"summary": "copied"}}}
    assert runtime.current_usage == {"usage": {"total_tokens": 12}}
    child_id = catalog.storage_id_for(
        session_id="child",
        user_id="user-1",
        channel="console",
    )
    child = TranscriptStore(tmp_path / "transcripts" / (child_id + ".db"))
    try:
        child.rebuild_projections()
        assert (
            child.get_page(
                session_id="child",
                user_id="user-1",
                channel="console",
            )
            == page
        )
        assert (
            child.read_runtime_state(
                session_id="child",
                user_id="user-1",
                channel="console",
            )
            == runtime
        )
    finally:
        child.close()
    child_path = tmp_path / "transcripts" / (child_id + ".db")
    with sqlite3.connect(child_path) as connection:
        assert connection.execute(
            "SELECT session_id, content FROM conversation_history",
        ).fetchall() == [("child", "recall before clone")]
    for turn_id, target in [
        ("turn-parent", "grandchild"),
        ("continued", "continued-fork"),
    ]:
        if turn_id == "continued":
            catalog.start_turn(
                session_id="child",
                user_id="user-1",
                channel="console",
                turn_id=turn_id,
            )
            catalog.upsert_message(
                session_id="child",
                turn_id=turn_id,
                message=_message("continued-message", "continue"),
                ordinal=0,
            )
            catalog.write_runtime_state(
                session_id="child",
                user_id="user-1",
                channel="console",
                state={"agent": {"state": {"summary": target}}},
                turn_id=turn_id,
            )
            catalog.finish_turn(
                session_id="child",
                turn_id=turn_id,
                status="completed",
            )
        catalog.fork_at_turn(
            source_session_id="child",
            source_user_id="user-1",
            source_channel="console",
            source_chat_id="child-chat",
            turn_id=turn_id,
            target_session_id=target,
            target_user_id="user-1",
            target_channel="console",
            target_storage_id=(
                "22222222-2222-4222-8222-222222222222"
                if turn_id == "turn-parent"
                else "33333333-3333-4333-8333-333333333333"
            ),
        )
        fork_runtime = catalog.read_runtime_state(
            session_id=target,
            user_id="user-1",
            channel="console",
        )
        assert fork_runtime is not None
        assert "mode_state" not in fork_runtime.state
        assert fork_runtime.state["agent"]["state"]["summary"] == (
            "turn boundary" if turn_id == "turn-parent" else target
        )
    catalog.finish_turn(
        session_id="parent",
        turn_id="running-turn",
        status="cancelled",
    )
    catalog.close()


def test_fork_at_completed_turn_rebuilds_boundary_state(
    tmp_path: Path,
) -> None:
    catalog = TranscriptCatalog(tmp_path)
    source_storage_id = ""
    source_path = Path()

    for turn_seq in range(1, 4):
        turn_id = f"turn-{turn_seq}"
        catalog.start_turn(
            session_id="parent",
            user_id="user-1",
            channel="console",
            turn_id=turn_id,
        )
        if not source_storage_id:
            source_storage_id = catalog.storage_id_for(
                session_id="parent",
                user_id="user-1",
                channel="console",
            )
            source_path = tmp_path / "transcripts" / f"{source_storage_id}.db"
        catalog.upsert_message(
            session_id="parent",
            turn_id=turn_id,
            message=_message(f"message-{turn_seq}", f"text-{turn_seq}"),
            ordinal=0,
        )
        history = HistoryStore(source_path)
        history.append(
            session_id="parent",
            entry=LogEntry(
                kind="model_turn",
                role="user",
                content=f"recall-{turn_seq}",
            ),
            dedup_key=f"recall-{turn_seq}",
        )
        history.close()
        catalog.write_runtime_state(
            session_id="parent",
            user_id="user-1",
            channel="console",
            state={
                "agent": {
                    "scroll": {
                        "index": {
                            "session_id": "parent\x1fcontext:2",
                        },
                    },
                },
                "turn": turn_seq,
            },
            current_usage={"usage": {"total_tokens": turn_seq}},
            reset_context=turn_seq == 2,
            turn_id=turn_id,
        )
        catalog.finish_turn(
            session_id="parent",
            turn_id=turn_id,
            status="completed",
        )

    boundary_runtime = catalog.read_turn_context(
        session_id="parent",
        user_id="user-1",
        channel="console",
        turn_id="turn-2",
    )
    assert boundary_runtime is not None
    child_storage_id = "22222222-2222-4222-8222-222222222222"
    fork_seq = catalog.fork_at_turn(
        source_session_id="parent",
        source_user_id="user-1",
        source_channel="console",
        source_chat_id="parent-chat",
        turn_id="turn-2",
        target_session_id="child",
        target_user_id="user-1",
        target_channel="console",
        target_storage_id=child_storage_id,
    )

    assert fork_seq == 2
    page = catalog.get_page(
        session_id="child",
        user_id="user-1",
        channel="console",
    )
    assert page is not None
    assert [message.id for message in page.messages] == [
        "message-1",
        "message-2",
    ]
    runtime = catalog.read_runtime_state(
        session_id="child",
        user_id="user-1",
        channel="console",
    )
    assert runtime is not None
    assert runtime.context_generation == boundary_runtime.context_generation
    assert runtime.state == {
        "agent": {
            "scroll": {
                "index": {
                    "session_id": "child\x1fcontext:2",
                },
            },
        },
        "turn": 2,
    }
    assert runtime.current_usage == boundary_runtime.current_usage

    child_path = tmp_path / "transcripts" / f"{child_storage_id}.db"
    connection = sqlite3.connect(child_path)
    try:
        recalls = connection.execute(
            "SELECT session_id, content FROM conversation_history "
            "ORDER BY seq",
        ).fetchall()
        lineage = connection.execute(
            "SELECT payload_json FROM event_log "
            "WHERE event_type = 'session.forked'",
        ).fetchone()
    finally:
        connection.close()
    assert recalls == [("child", "recall-1"), ("child", "recall-2")]
    assert lineage is not None
    assert json.loads(lineage[0]) == {
        "source_chat_id": "parent-chat",
        "source_session_id": "parent",
        "source_storage_id": source_storage_id,
        "turn_id": "turn-2",
        "turn_seq": 2,
    }

    catalog.start_turn(
        session_id="child",
        user_id="user-1",
        channel="console",
        turn_id="child-turn",
    )
    catalog.finish_turn(
        session_id="child",
        turn_id="child-turn",
        status="completed",
    )
    parent = catalog.get_page(
        session_id="parent",
        user_id="user-1",
        channel="console",
    )
    assert parent is not None
    assert [message.id for message in parent.messages] == [
        "message-1",
        "message-2",
        "message-3",
    ]
    catalog.close()
