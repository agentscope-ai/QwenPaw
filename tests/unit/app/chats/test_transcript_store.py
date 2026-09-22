# -*- coding: utf-8 -*-
"""Tests for the independent durable chat transcript store."""

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
        page_sizes.append(len(page.messages))
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
