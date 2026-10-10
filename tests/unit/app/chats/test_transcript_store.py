# -*- coding: utf-8 -*-
"""Tests for the independent durable chat transcript store."""

from contextlib import contextmanager
import threading

import pytest

from qwenpaw.app.chats.transcript import TranscriptCursor, TranscriptStore
from qwenpaw.schemas import (
    FileContent,
    Message,
    MessageType,
    RunStatus,
    TextContent,
)
from qwenpaw.token_usage.turn_usage import TURN_USAGE_META_KEY


def _message(message_id: str, text: str, *, role: str = "user") -> Message:
    return Message(
        id=message_id,
        role=role,
        content=[TextContent(text=text)],
        metadata={"client_id": f"client-{message_id}"},
    ).completed()


def _start(
    store: TranscriptStore,
    turn_id: str,
    *,
    session_id: str = "session-1",
    replaces_turn_id: str | None = None,
) -> int:
    return store.start_turn(
        session_id=session_id,
        user_id="user-1",
        channel="console",
        turn_id=turn_id,
        replaces_turn_id=replaces_turn_id,
    )


def test_message_round_trip_preserves_attachment_and_metadata(tmp_path):
    store = TranscriptStore(tmp_path / "session.db")
    _start(store, "turn-1")
    message = Message(
        id="message-1",
        role="user",
        content=[
            TextContent(text="inspect"),
            FileContent(
                filename="report.txt",
                file_url="/tmp/report.txt",
            ),
        ],
        metadata={"client_id": "client-1", "custom": {"value": 1}},
    ).completed()

    store.upsert_message(
        session_id="session-1",
        turn_id="turn-1",
        message=message,
        ordinal=0,
    )
    page = store.get_page(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )

    assert page is not None
    restored = page.messages[0]
    assert restored.metadata is not None
    assert restored.metadata["client_id"] == "client-1"
    assert restored.metadata["custom"] == {"value": 1}
    assert restored.metadata["timestamp"]
    assert page.messages[0].content[1].filename == "report.txt"
    store.close()


def test_start_turn_rejects_missing_session_row(tmp_path, monkeypatch):
    store = TranscriptStore(tmp_path / "session.db")
    monkeypatch.setattr(store, "_session_row", lambda _session_id: None)

    with pytest.raises(RuntimeError, match="failed to create"):
        _start(store, "turn-1")
    store.close()


def test_existing_empty_database_initializes_missing_schema(tmp_path):
    db_path = tmp_path / "session.db"
    db_path.touch()

    store = TranscriptStore(db_path, initialize_schema=False)
    _start(store, "turn-1")
    store.close()


def test_runtime_snapshot_reset_advances_context_generation(tmp_path):
    store = TranscriptStore(tmp_path / "session.db")
    generation, inserted = store.write_runtime_state(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        state={"agent": {"state": {"context": ["old"]}}},
    )
    assert (generation, inserted) == (0, True)
    store.set_current_usage(
        session_id="session-1",
        usage={"total_tokens": 12},
        context_usage={
            "estimated_tokens": 8,
            "max_input_length": 100,
            "context_usage_ratio": 8,
        },
    )

    generation, _ = store.write_runtime_state(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        state={"agent": {"state": {"context": []}}},
        reset_context=True,
    )
    snapshot = store.read_runtime_state(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )

    assert generation == 1
    assert snapshot is not None
    assert snapshot.context_generation == 1
    assert snapshot.state["agent"]["state"]["context"] == []
    assert snapshot.current_usage == {
        "usage": None,
        "context_usage": {
            "estimated_tokens": 0,
            "max_input_length": 100,
            "context_usage_ratio": 0,
        },
    }
    store.close()


def test_database_snapshot_restores_history_and_keeps_active_turn(tmp_path):
    store = TranscriptStore(tmp_path / "session.db")
    store.write_runtime_state(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        state={"agent": {"state": {"context": ["checkpoint"]}}},
    )
    _start(store, "turn-1")
    store.upsert_message(
        session_id="session-1",
        turn_id="turn-1",
        message=_message("message-1", "checkpoint"),
        ordinal=0,
    )
    store.finish_turn(
        session_id="session-1",
        turn_id="turn-1",
        status="completed",
    )
    snapshot = store.export_database(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )

    _start(store, "turn-2")
    store.upsert_message(
        session_id="session-1",
        turn_id="turn-2",
        message=_message("message-2", "later"),
        ordinal=0,
    )
    store.finish_turn(
        session_id="session-1",
        turn_id="turn-2",
        status="completed",
    )
    _start(store, "restore-turn")
    store.upsert_message(
        session_id="session-1",
        turn_id="restore-turn",
        message=_message("restore-message", "/checkpoint restore"),
        ordinal=0,
    )

    store.restore_database(
        snapshot,
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )
    store.finish_turn(
        session_id="session-1",
        turn_id="restore-turn",
        status="completed",
    )
    page = store.get_page(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )
    runtime = store.read_runtime_state(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )

    assert page is not None
    assert [message.id for message in page.messages] == [
        "message-1",
        "restore-message",
    ]
    assert runtime is not None
    assert runtime.state == {
        "agent": {"state": {"context": ["checkpoint"]}},
    }
    store.close()


def test_database_snapshot_excludes_running_turns(tmp_path):
    store = TranscriptStore(tmp_path / "session.db")
    _start(store, "checkpoint-turn")
    store.upsert_message(
        session_id="session-1",
        turn_id="checkpoint-turn",
        message=_message("checkpoint-message", "/checkpoint snap"),
        ordinal=0,
    )

    snapshot = store.export_database(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )
    snapshot_path = tmp_path / "snapshot.db"
    snapshot_path.write_bytes(snapshot)
    restored = TranscriptStore(snapshot_path, initialize_schema=False)
    page = restored.get_page(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )

    assert page is not None
    assert not page.messages
    restored.close()
    store.close()


@pytest.mark.parametrize(
    ("turn_status", "wire_status"),
    [("failed", "failed"), ("cancelled", "canceled")],
)
def test_page_projects_terminal_turn_state(
    tmp_path,
    turn_status,
    wire_status,
):
    store = TranscriptStore(tmp_path / "session.db")
    _start(store, "turn-1")
    store.upsert_message(
        session_id="session-1",
        turn_id="turn-1",
        message=Message(
            id="user-1",
            role="user",
            content=[TextContent(text="question")],
            metadata={"metadata": {"client_id": "client-1"}},
        ),
        ordinal=0,
    )
    store.finish_turn(
        session_id="session-1",
        turn_id="turn-1",
        status=turn_status,
        error={"code": "failure", "message": ""},
    )

    page = store.get_page(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )

    assert page is not None
    metadata = page.messages[0].metadata
    assert metadata is not None
    expected = {"status": wire_status}
    if turn_status == "failed":
        expected["error"] = {"code": "failure", "message": ""}
    assert metadata["metadata"]["qwenpaw_turn_state"] == expected
    store.close()


def test_page_read_does_not_wait_for_active_writer(tmp_path):
    store = TranscriptStore(tmp_path / "session.db")
    _start(store, "turn-1")
    store.upsert_message(
        session_id="session-1",
        turn_id="turn-1",
        message=_message("message-1", "committed"),
        ordinal=0,
    )
    store.finish_turn(
        session_id="session-1",
        turn_id="turn-1",
        status="completed",
    )
    writer_started = threading.Event()
    release_writer = threading.Event()
    read_finished = threading.Event()
    result = {}

    def hold_write_transaction() -> None:
        with store._transaction():  # pylint: disable=protected-access
            store._conn.execute(  # pylint: disable=protected-access
                "UPDATE transcript_sessions "
                "SET next_turn_seq = next_turn_seq "
                "WHERE session_id = ?",
                ("session-1",),
            )
            writer_started.set()
            release_writer.wait(timeout=5)

    def read_page() -> None:
        try:
            result["page"] = store.get_page(
                session_id="session-1",
                user_id="user-1",
                channel="console",
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            result["error"] = exc
        finally:
            read_finished.set()

    writer = threading.Thread(target=hold_write_transaction)
    reader = threading.Thread(target=read_page)
    writer.start()
    assert writer_started.wait(timeout=1)
    reader.start()
    try:
        assert read_finished.wait(timeout=1)
    finally:
        release_writer.set()
        writer.join(timeout=5)
        reader.join(timeout=5)

    assert "error" not in result
    page = result["page"]
    assert page is not None
    assert [message.id for message in page.messages] == ["message-1"]
    store.close()


def test_attach_turn_usage_updates_only_closing_assistant(tmp_path):
    store = TranscriptStore(tmp_path / "session.db")
    _start(store, "turn-1")
    messages = [
        _message("user-1", "question"),
        _message("reasoning-1", "thinking", role="assistant"),
        Message(
            id="assistant-1",
            role="assistant",
            content=[TextContent(text="answer")],
            metadata={"custom": {"preserved": True}},
        ).completed(),
    ]
    for ordinal, message in enumerate(messages):
        store.upsert_message(
            session_id="session-1",
            turn_id="turn-1",
            message=message,
            ordinal=ordinal,
        )
    store.finish_turn(
        session_id="session-1",
        turn_id="turn-1",
        status="completed",
    )
    usage = {"total_tokens": 461440, "cache_hit_rate": 87.28}
    context_usage = {
        "estimated_tokens": 14467,
        "max_input_length": 1000000,
        "context_usage_ratio": 1.4467,
    }

    first_attached = store.attach_turn_usage(
        session_id="session-1",
        turn_id="turn-1",
        usage=usage,
        context_usage=context_usage,
    )
    second_attached = store.attach_turn_usage(
        session_id="session-1",
        turn_id="turn-1",
        usage=usage,
        context_usage=context_usage,
    )
    page = store.get_page(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )

    assert first_attached is True
    assert second_attached is True
    assert page is not None
    assert TURN_USAGE_META_KEY not in (page.messages[1].metadata or {})
    metadata = page.messages[2].metadata
    assert metadata is not None
    assert metadata["custom"] == {"preserved": True}
    assert metadata[TURN_USAGE_META_KEY] == {
        "usage": usage,
        "context_usage": context_usage,
    }
    store.close()


def test_high_fanout_turn_stays_on_one_page(tmp_path):
    store = TranscriptStore(tmp_path / "session.db")
    _start(store, "turn-1")
    for ordinal in range(5):
        store.upsert_message(
            session_id="session-1",
            turn_id="turn-1",
            message=_message(
                f"message-{ordinal}",
                f"message {ordinal}",
                role="assistant" if ordinal else "user",
            ),
            ordinal=ordinal,
        )
    store.finish_turn(
        session_id="session-1",
        turn_id="turn-1",
        status="completed",
    )

    page = store.get_page(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        limit=1,
    )

    assert page is not None
    assert [message.id for message in page.messages] == [
        f"message-{ordinal}" for ordinal in range(5)
    ]
    assert page.has_more is False
    assert page.next_before is None
    store.close()


def test_page_byte_limit_splits_one_oversized_turn(tmp_path):
    store = TranscriptStore(tmp_path / "session.db")
    _start(store, "turn-1")
    store.upsert_message(
        session_id="session-1",
        turn_id="turn-1",
        message=_message("old-user", "old"),
        ordinal=0,
    )
    store.finish_turn(
        session_id="session-1",
        turn_id="turn-1",
        status="completed",
    )
    _start(store, "turn-2")
    for ordinal in range(2):
        store.upsert_message(
            session_id="session-1",
            turn_id="turn-2",
            message=_message(
                f"message-{ordinal}",
                "x" * 2_000,
                role="assistant" if ordinal else "user",
            ),
            ordinal=ordinal,
        )
    store.finish_turn(
        session_id="session-1",
        turn_id="turn-2",
        status="completed",
    )

    page = store.get_page(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        limit=50,
        max_bytes=100,
    )

    assert page is not None
    assert [message.id for message in page.messages] == ["message-1"]
    assert page.has_more is True
    assert page.next_before == TranscriptCursor(turn_seq=2, ordinal=1)

    middle = store.get_page(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        before=page.next_before,
        limit=50,
        max_bytes=100,
    )
    assert middle is not None
    assert [message.id for message in middle.messages] == ["message-0"]
    assert middle.has_more is True
    assert middle.next_before == TranscriptCursor(turn_seq=2, ordinal=0)

    older = store.get_page(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        before=middle.next_before,
        limit=50,
        max_bytes=100,
    )
    assert older is not None
    assert [message.id for message in older.messages] == ["old-user"]
    assert older.has_more is False
    store.close()


def test_running_turn_exposes_user_but_defers_sse_owned_outputs(tmp_path):
    store = TranscriptStore(tmp_path / "session.db")
    _start(store, "turn-1")
    store.upsert_message(
        session_id="session-1",
        turn_id="turn-1",
        message=_message("user-1", "question"),
        ordinal=0,
    )
    reasoning = Message(
        id="reasoning-1",
        type=MessageType.REASONING,
        role="assistant",
        content=[],
        status=RunStatus.InProgress,
    )
    store.upsert_message(
        session_id="session-1",
        turn_id="turn-1",
        message=reasoning,
        ordinal=1,
    )

    running = store.get_page(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )
    assert running is not None
    assert [message.id for message in running.messages] == ["user-1"]

    store.upsert_message(
        session_id="session-1",
        turn_id="turn-1",
        message=reasoning.model_copy(
            update={
                "content": [TextContent(text="thinking")],
                "status": RunStatus.Completed,
            },
        ),
        ordinal=1,
    )
    still_running = store.get_page(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )
    assert still_running is not None
    assert [message.id for message in still_running.messages] == ["user-1"]

    store.finish_turn(
        session_id="session-1",
        turn_id="turn-1",
        status="completed",
    )
    completed = store.get_page(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )
    assert completed is not None
    assert [message.id for message in completed.messages] == [
        "user-1",
        "reasoning-1",
    ]
    assert completed.messages[1].content[0].text == "thinking"
    store.close()


def test_page_uses_one_snapshot_when_running_turn_finishes(
    tmp_path,
    monkeypatch,
):
    store = TranscriptStore(tmp_path / "session.db")
    _start(store, "old-turn")
    store.upsert_message(
        session_id="session-1",
        turn_id="old-turn",
        message=_message("old-user", "old"),
        ordinal=0,
    )
    store.finish_turn(
        session_id="session-1",
        turn_id="old-turn",
        status="completed",
    )
    _start(store, "active-turn")
    store.upsert_message(
        session_id="session-1",
        turn_id="active-turn",
        message=_message("active-user", "question"),
        ordinal=0,
    )
    store.upsert_message(
        session_id="session-1",
        turn_id="active-turn",
        message=_message("active-assistant", "answer", role="assistant"),
        ordinal=1,
    )

    finish_requested = threading.Event()
    finish_completed = threading.Event()

    def finish_turn() -> None:
        assert finish_requested.wait(timeout=5)
        store.finish_turn(
            session_id="session-1",
            turn_id="active-turn",
            status="completed",
        )
        finish_completed.set()

    writer = threading.Thread(target=finish_turn)
    writer.start()
    # pylint: disable=protected-access
    original_read_connection = store._read_connection
    # pylint: enable=protected-access

    @contextmanager
    def interleaved_read_connection():
        with original_read_connection() as connection:
            snapshot_started = False

            class ConnectionProxy:
                """Finish the turn immediately before the body query."""

                def execute(self, sql, parameters=()):
                    nonlocal snapshot_started
                    if sql == "BEGIN":
                        snapshot_started = True
                    if sql.startswith("SELECT m.payload_json"):
                        finish_requested.set()
                        if not snapshot_started:
                            assert finish_completed.wait(timeout=5)
                    return connection.execute(sql, parameters)

            yield ConnectionProxy()

    monkeypatch.setattr(
        store,
        "_read_connection",
        interleaved_read_connection,
    )
    page = store.get_page(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        limit=1,
    )
    writer.join(timeout=5)

    assert not writer.is_alive()
    assert page is not None
    assert [message.id for message in page.messages] == ["active-user"]
    assert page.next_before == TranscriptCursor(turn_seq=2, ordinal=0)
    store.close()
