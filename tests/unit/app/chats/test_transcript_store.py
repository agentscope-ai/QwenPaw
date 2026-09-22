# -*- coding: utf-8 -*-
"""Tests for the independent durable chat transcript store."""

import sqlite3
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
        source="qwenpaw",
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

    revision = store.upsert_message(
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

    assert revision == 2
    assert page is not None
    restored = page.messages[0]
    assert restored.metadata is not None
    assert restored.metadata["client_id"] == "client-1"
    assert restored.metadata["custom"] == {"value": 1}
    assert restored.metadata["timestamp"]
    assert page.messages[0].content[1].filename == "report.txt"
    store.close()


def test_page_projects_database_times_without_overwriting_payload(tmp_path):
    store = TranscriptStore(tmp_path / "session.db")
    store.start_turn(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        turn_id="turn-1",
        source="qwenpaw",
        created_at="2026-09-20T12:00:00+00:00",
    )
    store.upsert_message(
        session_id="session-1",
        turn_id="turn-1",
        message=Message(
            id="user-1",
            role="user",
            content=[TextContent(text="question")],
        ),
        ordinal=0,
        created_at="2026-09-20T12:00:01+00:00",
    )
    store.upsert_message(
        session_id="session-1",
        turn_id="turn-1",
        message=Message(
            id="assistant-1",
            role="assistant",
            content=[TextContent(text="answer")],
            metadata={
                "timestamp": "2026-09-20T12:00:02+00:00",
                "finished_at": "2026-09-20T12:00:04+00:00",
            },
        ),
        ordinal=1,
        created_at="2026-09-20T12:00:03+00:00",
    )
    store.finish_turn(
        session_id="session-1",
        turn_id="turn-1",
        status="completed",
        finished_at="2026-09-20T12:00:05+00:00",
    )

    page = store.get_page(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )

    assert page is not None
    user, assistant = page.messages
    assert user.metadata == {
        "timestamp": "2026-09-20T12:00:01+00:00",
        "qwenpaw_turn_state": {"status": "completed"},
        "qwenpaw_transcript_position": {
            "turn_id": "turn-1",
            "turn_seq": 1,
            "ordinal": 0,
            "partial_before": False,
            "partial_after": True,
        },
    }
    assert user.status == RunStatus.Completed
    assert assistant.metadata == {
        "timestamp": "2026-09-20T12:00:02+00:00",
        "finished_at": "2026-09-20T12:00:04+00:00",
        "qwenpaw_transcript_position": {
            "turn_id": "turn-1",
            "turn_seq": 1,
            "ordinal": 1,
            "partial_before": True,
            "partial_after": False,
        },
    }
    assert assistant.status == RunStatus.Completed
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


def test_transcript_remains_readable_after_store_reopen(tmp_path):
    db_path = tmp_path / "session.db"
    store = TranscriptStore(db_path)
    _start(store, "turn-1")
    store.upsert_message(
        session_id="session-1",
        turn_id="turn-1",
        message=_message("message-1", "persisted"),
        ordinal=0,
    )
    store.finish_turn(
        session_id="session-1",
        turn_id="turn-1",
        status="completed",
    )
    store.close()

    reopened = TranscriptStore(db_path)
    page = reopened.get_page(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )

    assert page is not None
    assert [message.id for message in page.messages] == ["message-1"]
    assert page.messages[0].content[0].text == "persisted"
    reopened.close()


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
                "UPDATE transcript_sessions SET updated_at = updated_at "
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


def test_turn_and_message_writes_are_idempotent(tmp_path):
    store = TranscriptStore(tmp_path / "session.db")

    assert _start(store, "turn-1") == 1
    assert _start(store, "turn-1") == 1
    message = _message("message-1", "same")
    first_revision = store.upsert_message(
        session_id="session-1",
        turn_id="turn-1",
        message=message,
        ordinal=0,
    )
    second_revision = store.upsert_message(
        session_id="session-1",
        turn_id="turn-1",
        message=message,
        ordinal=0,
    )

    assert first_revision == second_revision == 2
    assert (
        store._conn.execute(  # pylint: disable=protected-access
            "SELECT COUNT(*) FROM transcript_turns",
        ).fetchone()[0]
        == 1
    )
    assert (
        store._conn.execute(  # pylint: disable=protected-access
            "SELECT COUNT(*) FROM transcript_messages",
        ).fetchone()[0]
        == 1
    )
    terminal_revision = store.finish_turn(
        session_id="session-1",
        turn_id="turn-1",
        status="completed",
    )
    assert (
        store.finish_turn(
            session_id="session-1",
            turn_id="turn-1",
            status="completed",
        )
        == terminal_revision
    )
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

    first_revision = store.attach_turn_usage(
        session_id="session-1",
        turn_id="turn-1",
        usage=usage,
        context_usage=context_usage,
    )
    second_revision = store.attach_turn_usage(
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

    assert first_revision == second_revision
    assert page is not None
    assert TURN_USAGE_META_KEY not in (page.messages[1].metadata or {})
    metadata = page.messages[2].metadata
    assert metadata is not None
    assert metadata["custom"] == {"preserved": True}
    assert metadata[TURN_USAGE_META_KEY] == {
        "usage": usage,
        "context_usage": context_usage,
    }
    assert page.revision == first_revision
    store.close()


def test_identical_text_with_distinct_ids_is_not_deduplicated(tmp_path):
    store = TranscriptStore(tmp_path / "session.db")
    for index in (1, 2):
        turn_id = f"turn-{index}"
        _start(store, turn_id)
        store.upsert_message(
            session_id="session-1",
            turn_id=turn_id,
            message=_message(f"message-{index}", "same text"),
            ordinal=0,
        )
        store.finish_turn(
            session_id="session-1",
            turn_id=turn_id,
            status="completed",
        )

    page = store.get_page(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )

    assert page is not None
    assert [message.id for message in page.messages] == [
        "message-1",
        "message-2",
    ]
    assert [message.content[0].text for message in page.messages] == [
        "same text",
        "same text",
    ]
    store.close()


def test_message_identity_cannot_move_between_turns(tmp_path):
    store = TranscriptStore(tmp_path / "session.db")
    _start(store, "turn-1")
    _start(store, "turn-2")
    message = _message("message-1", "same")
    store.upsert_message(
        session_id="session-1",
        turn_id="turn-1",
        message=message,
        ordinal=0,
    )

    with pytest.raises(ValueError, match="another turn"):
        store.upsert_message(
            session_id="session-1",
            turn_id="turn-2",
            message=message,
            ordinal=0,
        )
    store.close()


def test_session_identity_is_enforced(tmp_path):
    store = TranscriptStore(tmp_path / "session.db")
    _start(store, "turn-1")

    with pytest.raises(ValueError, match="identity mismatch"):
        store.start_turn(
            session_id="session-1",
            user_id="other-user",
            channel="console",
            turn_id="turn-2",
            source="qwenpaw",
        )
    with pytest.raises(ValueError, match="identity mismatch"):
        store.get_page(
            session_id="session-1",
            user_id="user-1",
            channel="other-channel",
        )
    store.close()


def test_pagination_is_item_bounded_and_chronological(tmp_path):
    store = TranscriptStore(tmp_path / "session.db")
    for number in range(1, 5):
        turn_id = f"turn-{number}"
        _start(store, turn_id)
        for ordinal in range(2):
            store.upsert_message(
                session_id="session-1",
                turn_id=turn_id,
                message=_message(
                    f"message-{number}-{ordinal}",
                    f"turn {number} message {ordinal}",
                ),
                ordinal=ordinal,
            )
        store.finish_turn(
            session_id="session-1",
            turn_id=turn_id,
            status="completed",
        )

    latest = store.get_page(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        limit=2,
    )
    assert latest is not None
    assert latest.has_more is True
    assert latest.next_before == TranscriptCursor(turn_seq=4, ordinal=0)
    assert [message.id for message in latest.messages] == [
        "message-4-0",
        "message-4-1",
    ]

    older = store.get_page(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        before=latest.next_before,
        limit=2,
    )
    assert older is not None
    assert older.has_more is True
    assert older.next_before == TranscriptCursor(turn_seq=3, ordinal=0)
    assert [message.id for message in older.messages] == [
        "message-3-0",
        "message-3-1",
    ]
    store.close()


def test_high_fanout_turn_spans_pages_without_losing_items(tmp_path):
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

    cursor = None
    message_ids: list[str] = []
    page_sizes: list[int] = []
    while True:
        page = store.get_page(
            session_id="session-1",
            user_id="user-1",
            channel="console",
            before=cursor,
            limit=2,
        )
        assert page is not None
        message_ids = [message.id for message in page.messages] + message_ids
        page_sizes.append(page.item_count)
        if not page.has_more:
            break
        assert page.next_before is not None
        cursor = page.next_before

    assert page_sizes == [2, 2, 1]
    assert message_ids == [f"message-{ordinal}" for ordinal in range(5)]
    store.close()


def test_page_byte_limit_always_returns_one_oversized_item(tmp_path):
    store = TranscriptStore(tmp_path / "session.db")
    _start(store, "turn-1")
    for ordinal in range(2):
        store.upsert_message(
            session_id="session-1",
            turn_id="turn-1",
            message=_message(
                f"message-{ordinal}",
                "x" * 2_000,
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
        limit=50,
        max_bytes=100,
    )

    assert page is not None
    assert [message.id for message in page.messages] == ["message-1"]
    assert page.payload_bytes > 100
    assert page.max_bytes_reached is True
    assert page.has_more is True
    assert page.next_before == TranscriptCursor(turn_seq=1, ordinal=1)
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


def test_history_import_is_atomic_idempotent_and_partial(tmp_path):
    store = TranscriptStore(tmp_path / "session.db")
    turns = [
        (
            "import-turn-1",
            [
                _message("import-user-1", "question"),
                _message("import-answer-1", "answer", role="assistant"),
            ],
        ),
        (
            "import-turn-2",
            [_message("import-user-2", "next")],
        ),
    ]

    imported = store.import_history_if_missing(
        session_id="import-session",
        user_id="user-1",
        channel="console",
        source="harness_import",
        turns=turns,
    )
    repeated = store.import_history_if_missing(
        session_id="import-session",
        user_id="user-1",
        channel="console",
        source="harness_import",
        turns=turns,
    )
    page = store.get_page(
        session_id="import-session",
        user_id="user-1",
        channel="console",
    )

    assert imported is True
    assert repeated is False
    assert page is not None
    assert page.completeness == "partial"
    assert page.revision == 7
    assert [message.id for message in page.messages] == [
        "import-user-1",
        "import-answer-1",
        "import-user-2",
    ]
    assert {
        row[0]
        for row in store._conn.execute(  # pylint: disable=protected-access
            "SELECT DISTINCT source FROM transcript_turns",
        )
    } == {"harness_import"}
    store.close()


def test_history_import_does_not_replace_existing_live_session(tmp_path):
    store = TranscriptStore(tmp_path / "session.db")
    _start(store, "live-turn", session_id="shared-session")
    store.upsert_message(
        session_id="shared-session",
        turn_id="live-turn",
        message=_message("live-message", "live"),
        ordinal=0,
    )

    imported = store.import_history_if_missing(
        session_id="shared-session",
        user_id="user-1",
        channel="console",
        source="harness_import",
        turns=[("import-turn", [_message("import-message", "old")])],
    )
    page = store.get_page(
        session_id="shared-session",
        user_id="user-1",
        channel="console",
    )

    assert imported is False
    assert page is not None
    assert page.completeness == "complete"
    assert [message.id for message in page.messages] == ["live-message"]
    store.close()


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_failed_replacement_does_not_hide_original(tmp_path, status):
    store = TranscriptStore(tmp_path / "session.db")
    _start(store, "original")
    original = _message("assistant-old", "old", role="assistant")
    store.upsert_message(
        session_id="session-1",
        turn_id="original",
        message=original,
        ordinal=0,
    )
    store.finish_turn(
        session_id="session-1",
        turn_id="original",
        status="completed",
    )
    _start(store, "replacement")
    store.upsert_message(
        session_id="session-1",
        turn_id="replacement",
        message=_message("assistant-new", "new", role="assistant"),
        ordinal=0,
        replaces_message_id="assistant-old",
    )
    store.finish_turn(
        session_id="session-1",
        turn_id="replacement",
        status=status,
    )

    page = store.get_page(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )
    assert page is not None
    assert [message.id for message in page.messages] == [
        "assistant-old",
        "assistant-new",
    ]
    store.close()


def test_completed_replacement_hides_original(tmp_path):
    store = TranscriptStore(tmp_path / "session.db")
    _start(store, "original")
    store.upsert_message(
        session_id="session-1",
        turn_id="original",
        message=_message("assistant-old", "old", role="assistant"),
        ordinal=0,
    )
    store.finish_turn(
        session_id="session-1",
        turn_id="original",
        status="completed",
    )
    _start(store, "replacement")
    store.upsert_message(
        session_id="session-1",
        turn_id="replacement",
        message=_message("assistant-new", "new", role="assistant"),
        ordinal=0,
        replaces_message_id="assistant-old",
    )
    store.finish_turn(
        session_id="session-1",
        turn_id="replacement",
        status="completed",
    )

    page = store.get_page(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )
    assert page is not None
    assert [message.id for message in page.messages] == ["assistant-new"]
    store.close()


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_failed_turn_replacement_keeps_original_turn(
    tmp_path,
    status,
):
    store = TranscriptStore(tmp_path / "session.db")
    _start(store, "original")
    for ordinal, message in enumerate(
        [
            _message("user-old", "question"),
            _message("assistant-old", "old", role="assistant"),
        ],
    ):
        store.upsert_message(
            session_id="session-1",
            turn_id="original",
            message=message,
            ordinal=ordinal,
        )
    store.finish_turn(
        session_id="session-1",
        turn_id="original",
        status="completed",
    )
    _start(store, "replacement", replaces_turn_id="original")
    store.upsert_message(
        session_id="session-1",
        turn_id="replacement",
        message=_message("user-new", "question"),
        ordinal=0,
    )
    store.finish_turn(
        session_id="session-1",
        turn_id="replacement",
        status=status,
    )

    page = store.get_page(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )

    assert page is not None
    assert [message.id for message in page.messages] == [
        "user-old",
        "assistant-old",
        "user-new",
    ]
    store.close()


def test_completed_turn_replacement_hides_whole_original_turn(tmp_path):
    store = TranscriptStore(tmp_path / "session.db")
    _start(store, "original")
    for ordinal, message in enumerate(
        [
            _message("user-old", "question"),
            _message("tool-old", "tool", role="assistant"),
            _message("assistant-old", "old", role="assistant"),
        ],
    ):
        store.upsert_message(
            session_id="session-1",
            turn_id="original",
            message=message,
            ordinal=ordinal,
        )
    store.finish_turn(
        session_id="session-1",
        turn_id="original",
        status="completed",
    )
    _start(store, "replacement", replaces_turn_id="original")
    for ordinal, message in enumerate(
        [
            _message("user-new", "question"),
            _message("assistant-new", "new", role="assistant"),
        ],
    ):
        store.upsert_message(
            session_id="session-1",
            turn_id="replacement",
            message=message,
            ordinal=ordinal,
        )
    store.finish_turn(
        session_id="session-1",
        turn_id="replacement",
        status="completed",
    )

    page = store.get_page(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        limit=2,
    )

    assert page is not None
    assert page.has_more is False
    assert [message.id for message in page.messages] == [
        "user-new",
        "assistant-new",
    ]
    store.close()


def test_delete_session_cascades(tmp_path):
    store = TranscriptStore(tmp_path / "session.db")
    _start(store, "turn-1")
    store.upsert_message(
        session_id="session-1",
        turn_id="turn-1",
        message=_message("message-1", "text"),
        ordinal=0,
    )
    store.upsert_message(
        session_id="session-1",
        turn_id="turn-1",
        message=_message("assistant-1", "answer", role="assistant"),
        ordinal=1,
    )
    store.attach_turn_usage(
        session_id="session-1",
        turn_id="turn-1",
        usage={"total_tokens": 10},
        context_usage={"estimated_tokens": 5},
    )

    assert store.has_session("session-1") is True
    assert store.has_session("missing") is False
    assert store.delete_session("session-1") is True
    assert store.delete_session("session-1") is False
    assert (
        store._conn.execute(  # pylint: disable=protected-access
            "SELECT COUNT(*) FROM transcript_sessions",
        ).fetchone()[0]
        == 0
    )
    assert (
        store._conn.execute(  # pylint: disable=protected-access
            "SELECT COUNT(*) FROM transcript_turns",
        ).fetchone()[0]
        == 0
    )
    assert (
        store._conn.execute(  # pylint: disable=protected-access
            "SELECT COUNT(*) FROM transcript_messages",
        ).fetchone()[0]
        == 0
    )


def test_message_anchor_lookups_use_indexed_columns(tmp_path):
    store = TranscriptStore(tmp_path / "session.db")
    _start(store, "turn-1")
    message = Message(
        id="message-1",
        role="user",
        content=[TextContent(text="question")],
        metadata={"qwenpaw_client_message_id": "client-1"},
    ).completed()
    store.upsert_message(
        session_id="session-1",
        turn_id="turn-1",
        message=message,
        ordinal=0,
    )

    assert (
        store.find_turn_for_message(
            session_id="session-1",
            message_id="message-1",
        )
        == "turn-1"
    )
    assert (
        store.find_turn_for_message(
            session_id="session-1",
            client_message_id="client-1",
        )
        == "turn-1"
    )
    plan = store._conn.execute(  # pylint: disable=protected-access
        "EXPLAIN QUERY PLAN SELECT turn_id FROM transcript_messages "
        "WHERE session_id = ? AND client_message_id = ? "
        "ORDER BY created_at DESC LIMIT 1",
        ("session-1", "client-1"),
    ).fetchall()
    assert any("transcript_messages_client" in row[3] for row in plan)
    store.close()


def test_scheduled_delete_hides_before_physical_cleanup(tmp_path):
    store = TranscriptStore(tmp_path / "session.db")
    _start(store, "turn-1")
    store.upsert_message(
        session_id="session-1",
        turn_id="turn-1",
        message=_message("message-1", "question"),
        ordinal=0,
    )
    cleanup_started = threading.Event()
    allow_cleanup = threading.Event()
    physical_cleanup = getattr(store, "_purge_deleted_session")

    def blocked_cleanup(session_id):
        cleanup_started.set()
        allow_cleanup.wait(timeout=5)
        return physical_cleanup(session_id)

    setattr(store, "_purge_deleted_session", blocked_cleanup)
    assert store.schedule_delete_session("session-1") is True
    assert cleanup_started.wait(timeout=5)

    assert store.has_session("session-1") is False
    assert (
        store.get_page(
            session_id="session-1",
            user_id="user-1",
            channel="console",
        )
        is None
    )
    row = store._conn.execute(  # pylint: disable=protected-access
        "SELECT deleted_at FROM transcript_sessions WHERE session_id = ?",
        ("session-1",),
    ).fetchone()
    assert row is not None and row["deleted_at"] is not None

    allow_cleanup.set()
    store.close()


def test_open_retries_interrupted_physical_cleanup(tmp_path):
    db_path = tmp_path / "session.db"
    store = TranscriptStore(db_path)
    _start(store, "turn-1")
    store.upsert_message(
        session_id="session-1",
        turn_id="turn-1",
        message=_message("message-1", "question"),
        ordinal=0,
    )
    store.close()
    connection = sqlite3.connect(db_path)
    connection.execute(
        "UPDATE transcript_sessions SET deleted_at = ? WHERE session_id = ?",
        ("2026-09-21T00:00:00+00:00", "session-1"),
    )
    connection.commit()
    connection.close()

    reopened = TranscriptStore(db_path)
    reopened.close()
    connection = sqlite3.connect(db_path)
    assert (
        connection.execute(
            "SELECT COUNT(*) FROM transcript_sessions",
        ).fetchone()[0]
        == 0
    )
    assert (
        connection.execute(
            "SELECT COUNT(*) FROM transcript_messages",
        ).fetchone()[0]
        == 0
    )
    connection.close()


def test_background_cleanup_releases_lock_between_batches(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.app.chats import transcript as transcript_module

    store = TranscriptStore(tmp_path / "session.db")
    _start(store, "turn-delete")
    for ordinal in range(2):
        store.upsert_message(
            session_id="session-1",
            turn_id="turn-delete",
            message=_message(f"delete-{ordinal}", "old"),
            ordinal=ordinal,
        )
    _start(store, "turn-keep", session_id="session-2")
    store.upsert_message(
        session_id="session-2",
        turn_id="turn-keep",
        message=_message("keep-1", "visible"),
        ordinal=0,
    )
    between_batches = threading.Event()
    continue_cleanup = threading.Event()

    def pause_between_batches(_seconds):
        between_batches.set()
        continue_cleanup.wait(timeout=5)

    monkeypatch.setattr(transcript_module, "_DELETE_BATCH_SIZE", 1)
    monkeypatch.setattr(transcript_module.time, "sleep", pause_between_batches)
    assert store.schedule_delete_session("session-1") is True
    assert between_batches.wait(timeout=5)

    page = store.get_page(
        session_id="session-2",
        user_id="user-1",
        channel="console",
    )
    assert page is not None
    assert [message.id for message in page.messages] == ["keep-1"]

    continue_cleanup.set()
    store.close()


def test_newer_schema_is_rejected_without_overwrite(tmp_path):
    db_path = tmp_path / "session.db"
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA user_version=99")
    connection.close()

    with pytest.raises(RuntimeError, match="newer than supported"):
        TranscriptStore(db_path)

    connection = sqlite3.connect(db_path)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 99
    connection.close()


def test_schema_v1_migrates_replacement_turn_column(tmp_path):
    db_path = tmp_path / "session.db"
    store = TranscriptStore(db_path)
    _start(store, "turn-1")
    store.upsert_message(
        session_id="session-1",
        turn_id="turn-1",
        message=Message(
            id="message-1",
            role="user",
            content=[TextContent(text="question")],
            metadata={"qwenpaw_client_message_id": "client-1"},
        ).completed(),
        ordinal=0,
    )
    store.close()
    connection = sqlite3.connect(db_path)
    connection.execute(
        "ALTER TABLE transcript_turns DROP COLUMN replaces_turn_id",
    )
    connection.execute("DROP INDEX transcript_messages_client")
    connection.execute(
        "ALTER TABLE transcript_messages DROP COLUMN client_message_id",
    )
    connection.execute("PRAGMA user_version=1")
    connection.close()

    migrated = TranscriptStore(db_path)
    columns = {
        row[1]
        for row in migrated._conn.execute(  # pylint: disable=protected-access
            "PRAGMA table_info(transcript_turns)",
        )
    }

    assert "replaces_turn_id" in columns
    message_columns = {
        row[1]
        for row in migrated._conn.execute(  # pylint: disable=protected-access
            "PRAGMA table_info(transcript_messages)",
        )
    }
    assert "client_message_id" in message_columns
    assert (
        migrated.find_turn_for_message(
            session_id="session-1",
            client_message_id="client-1",
        )
        == "turn-1"
    )
    assert (
        migrated._conn.execute(  # pylint: disable=protected-access
            "PRAGMA user_version",
        ).fetchone()[0]
        == 3
    )
    migrated.close()
