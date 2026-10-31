# -*- coding: utf-8 -*-
"""Tests for the independent durable chat transcript store."""

from contextlib import contextmanager
import threading

import pytest

from qwenpaw.app.chats.transcript import TranscriptCursor, TranscriptStore
from qwenpaw.schemas import (
    DataContent,
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

    store = TranscriptStore(db_path)
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


def test_runtime_reset_keeps_durable_transcript_history(tmp_path):
    store = TranscriptStore(tmp_path / "session.db")
    _start(store, "turn-1")
    store.upsert_message(
        session_id="session-1",
        turn_id="turn-1",
        message=_message("message-1", "visible before compact"),
        ordinal=0,
    )
    store.finish_turn(
        session_id="session-1",
        turn_id="turn-1",
        status="completed",
    )
    store.write_runtime_state(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        state={"agent": {"state": {"context": ["old"]}}},
    )

    generation, _ = store.write_runtime_state(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        state={"agent": {"state": {"context": ["summary"]}}},
        reset_context=True,
    )
    page = store.get_page(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )

    assert generation == 1
    assert page is not None
    assert [message.id for message in page.messages] == ["message-1"]
    assert page.messages[0].content[0].text == "visible before compact"
    store.close()


def test_user_message_index_anchor_reads_target_turn(tmp_path):
    store = TranscriptStore(tmp_path / "session.db")
    for number in range(1, 8):
        turn_id = f"turn-{number}"
        _start(store, turn_id)
        store.upsert_message(
            session_id="session-1",
            turn_id=turn_id,
            message=_message(
                f"message-{number}",
                f"  user   message {number}  ",
            ).model_copy(
                update={
                    "metadata": {
                        "qwenpaw_client_message_id": f"client-{number}",
                    },
                },
            ),
            ordinal=0,
        )
        store.upsert_message(
            session_id="session-1",
            turn_id=turn_id,
            message=_message(
                f"assistant-{number}",
                f"assistant response {number}",
                role="assistant",
            ),
            ordinal=1,
        )
        store.finish_turn(
            session_id="session-1",
            turn_id=turn_id,
            status="completed",
        )

    index = store.get_user_message_page(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )

    assert index is not None
    assert [item.message_id for item in index.items] == [
        f"message-{number}" for number in range(1, 8)
    ]
    assert index.items[2].preview == "user message 3"
    assert index.items[2].client_message_id == "client-3"
    assert index.total == 7
    forward = store.get_page(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        after_message_id="message-2",
        limit=2,
    )
    assert [item.id for item in forward.messages] == [
        "message-3",
        "assistant-3",
        "message-4",
        "assistant-4",
    ]
    short_tail = store.get_page(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        after_message_id="message-6",
        limit=5,
    )
    assert [item.id for item in short_tail.messages] == [
        "message-7",
        "assistant-7",
    ]
    end = store.get_page(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        after_message_id="message-7",
        limit=2,
    )
    assert not end.messages
    with pytest.raises(ValueError, match="boundary message not found"):
        store.get_page(
            session_id="session-1",
            user_id="user-1",
            channel="console",
            after_message_id="unknown",
            limit=2,
        )
    recent = store.get_user_message_page(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        limit=3,
    )
    assert recent.total == 7
    assert [item.message_id for item in recent.items] == [
        "message-5",
        "message-6",
        "message-7",
    ]
    assert recent.has_more
    _start(store, "later-turn")
    store.upsert_message(
        session_id="session-1",
        turn_id="later-turn",
        message=_message("later-message", "new input"),
        ordinal=0,
    )
    older = store.get_user_message_page(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        before=recent.next_before,
        limit=3,
    )
    assert older.total == 7
    assert [item.message_id for item in older.items] == [
        "message-2",
        "message-3",
        "message-4",
    ]

    page = store.get_page(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        before=index.items[2].anchor,
        limit=5,
    )

    assert page is not None
    assert [message.id for message in page.messages] == [
        "message-1",
        "assistant-1",
        "message-2",
        "assistant-2",
        "message-3",
        "assistant-3",
    ]

    newest_page = store.get_page(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        before=index.items[-1].anchor,
        limit=5,
    )

    assert newest_page is not None
    assert [message.id for message in newest_page.messages][-2:] == [
        "message-7",
        "assistant-7",
    ]
    store.close()


def test_database_snapshot_restores_history_and_keeps_active_turn(
    tmp_path,
    monkeypatch,
):
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

    original_copy = TranscriptStore._fork_copy_turn

    def fail_after_copy(target, *args, **kwargs):
        original_copy(target, *args, **kwargs)
        raise RuntimeError("interrupted restore")

    before = store.get_page(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )
    with monkeypatch.context() as patch:
        patch.setattr(TranscriptStore, "_fork_copy_turn", fail_after_copy)
        with pytest.raises(RuntimeError, match="interrupted restore"):
            store.restore_database(
                snapshot,
                session_id="session-1",
                user_id="user-1",
                channel="console",
            )
    assert (
        store.get_page(
            session_id="session-1",
            user_id="user-1",
            channel="console",
        )
        == before
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
    store.rebuild_projections()
    rebuilt = store.get_page(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )
    assert rebuilt == page
    assert (
        store.read_runtime_state(
            session_id="session-1",
            user_id="user-1",
            channel="console",
        )
        == runtime
    )
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
    restored = TranscriptStore(snapshot_path)
    page = restored.get_page(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )

    assert page is not None
    assert not page.messages
    restored.rebuild_projections()
    assert (
        restored.get_page(
            session_id="session-1",
            user_id="user-1",
            channel="console",
        )
        == page
    )
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
        finished_at="2026-10-26T04:40:31+00:00",
    )

    page = store.get_page(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )

    assert page is not None
    metadata = page.messages[0].metadata
    assert metadata is not None
    expected = {
        "status": wire_status,
        "finished_at": "2026-10-26T04:40:31+00:00",
    }
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
        max_bytes=3_500,
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
        max_bytes=3_500,
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
        max_bytes=3_500,
    )
    assert older is not None
    assert [message.id for message in older.messages] == ["old-user"]
    assert older.has_more is False
    store.close()


def test_page_byte_limit_splits_one_message_by_content_block(tmp_path):
    store = TranscriptStore(tmp_path / "session.db")
    _start(store, "turn-1")
    store.upsert_message(
        session_id="session-1",
        turn_id="turn-1",
        message=Message(
            id="large-user",
            role="user",
            content=[
                TextContent(text=f"{label}:" + "x" * 1_000)
                for label in ("first", "second", "third")
            ],
        ).completed(),
        ordinal=0,
    )
    store.finish_turn(
        session_id="session-1",
        turn_id="turn-1",
        status="completed",
    )

    pages = []
    before = None
    max_bytes = 2_500
    while True:
        page = store.get_page(
            session_id="session-1",
            user_id="user-1",
            channel="console",
            before=before,
            limit=20,
            max_bytes=max_bytes,
        )
        assert page is not None
        message_bytes = sum(
            len(message.model_dump_json().encode("utf-8"))
            for message in page.messages
        )
        assert message_bytes + 1_024 <= max_bytes
        pages.append(page)
        if not page.has_more:
            break
        before = page.next_before

    assert len(pages) == 3
    assert [page.messages[0].content[0].text[:5] for page in pages] == [
        "third",
        "secon",
        "first",
    ]
    assert pages[0].next_before == TranscriptCursor(
        turn_seq=1,
        ordinal=0,
        content_before=2,
    )
    assert pages[1].next_before == TranscriptCursor(
        turn_seq=1,
        ordinal=0,
        content_before=1,
    )
    assert pages[2].has_more is False
    store.close()


def test_page_byte_limit_splits_one_oversized_text_block(tmp_path):
    store = TranscriptStore(tmp_path / "session.db")
    text = "历史内容" * 3_000
    _start(store, "turn-1")
    store.upsert_message(
        session_id="session-1",
        turn_id="turn-1",
        message=Message(
            id="large-text",
            role="assistant",
            content=[TextContent(text=text)],
        ).completed(),
        ordinal=0,
    )
    store.finish_turn(
        session_id="session-1",
        turn_id="turn-1",
        status="completed",
    )

    pages = []
    before = None
    max_bytes = 4_096
    while True:
        page = store.get_page(
            session_id="session-1",
            user_id="user-1",
            channel="console",
            before=before,
            max_bytes=max_bytes,
        )
        assert page is not None
        assert len(page.messages) == 1
        message_bytes = len(
            page.messages[0].model_dump_json().encode("utf-8"),
        )
        assert message_bytes + 1_024 <= max_bytes
        pages.append(page)
        if not page.has_more:
            break
        before = page.next_before

    assert len(pages) > 1
    restored = "".join(
        page.messages[0].content[0].text for page in reversed(pages)
    )
    assert restored == text
    assert pages[-1].has_more is False
    store.close()


def test_page_byte_limit_splits_one_oversized_tool_result(tmp_path):
    store = TranscriptStore(tmp_path / "session.db")
    output = "tool-result-工具输出" * 1_000
    _start(store, "turn-1")
    store.upsert_message(
        session_id="session-1",
        turn_id="turn-1",
        message=Message(
            id="large-tool-result",
            type=MessageType.PLUGIN_CALL_OUTPUT,
            role="tool",
            content=[
                DataContent(
                    data={
                        "call_id": "call-1",
                        "name": "large_tool",
                        "output": output,
                    },
                ),
            ],
        ).completed(),
        ordinal=0,
    )
    store.finish_turn(
        session_id="session-1",
        turn_id="turn-1",
        status="completed",
    )

    serialized_fragments = []
    before = None
    max_bytes = 4_096
    while True:
        page = store.get_page(
            session_id="session-1",
            user_id="user-1",
            channel="console",
            before=before,
            max_bytes=max_bytes,
        )
        assert page is not None
        assert len(page.messages) == 1
        assert page.messages[0].content == []
        message_bytes = len(
            page.messages[0].model_dump_json().encode("utf-8"),
        )
        assert message_bytes + 1_024 <= max_bytes
        fragment = page.messages[0].metadata["qwenpaw_history_fragment"]
        serialized_fragments.append(fragment["serialized_fragment"])
        if not page.has_more:
            break
        before = page.next_before

    restored = "".join(reversed(serialized_fragments))
    content = DataContent.model_validate_json(restored)
    assert content.data["output"] == output
    store.close()


def test_default_page_block_limit_splits_one_high_fanout_message(tmp_path):
    store = TranscriptStore(tmp_path / "session.db")
    _start(store, "turn-1")
    store.upsert_message(
        session_id="session-1",
        turn_id="turn-1",
        message=Message(
            id="high-fanout",
            role="assistant",
            content=[
                TextContent(text=f"block-{index:03d}") for index in range(250)
            ],
        ).completed(),
        ordinal=0,
    )
    store.finish_turn(
        session_id="session-1",
        turn_id="turn-1",
        status="completed",
    )

    pages = []
    before = None
    while True:
        page = store.get_page(
            session_id="session-1",
            user_id="user-1",
            channel="console",
            before=before,
        )
        assert page is not None
        assert sum(len(message.content) for message in page.messages) <= 40
        pages.append(page)
        if not page.has_more:
            break
        before = page.next_before

    assert [len(page.messages[0].content) for page in pages] == [
        40,
        40,
        40,
        40,
        40,
        40,
        10,
    ]
    restored = [
        content.text
        for page in reversed(pages)
        for content in page.messages[0].content
    ]
    assert restored == [f"block-{index:03d}" for index in range(250)]
    assert pages[-1].has_more is False
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
                    if sql.startswith("SELECT m.envelope_json"):
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


def test_user_input_text_preserves_full_text_and_identity(tmp_path):
    store = TranscriptStore(tmp_path / "recall.db")
    _start(store, "turn-1")
    text = f"{'long input ' * 50}\n  preserve spacing  "
    for role in ("user", "assistant"):
        store.upsert_message(
            session_id="session-1",
            turn_id="turn-1",
            message=_message(role, text, role=role),
            ordinal=0 if role == "user" else 1,
        )
    identity = {
        "session_id": "session-1",
        "user_id": "user-1",
        "channel": "console",
    }
    assert store.get_user_message_text(**identity, message_id="user") == text
    assert (
        store.get_user_message_text(
            **identity,
            message_id="assistant",
        )
        is None
    )
    assert (
        store.get_user_message_text(
            **identity,
            message_id="missing",
        )
        is None
    )
    with pytest.raises(ValueError, match="identity mismatch"):
        store.get_user_message_text(
            session_id="session-1",
            user_id="other",
            channel="console",
            message_id="user",
        )


@pytest.mark.parametrize(
    "text",
    [
        "short input",
        "x" * 160,
        "x" * 161,
        "first\nsecond",
        "two  spaces",
        " trailing ",
    ],
)
def test_user_preview_keeps_full_text_available(tmp_path, text):
    store = TranscriptStore(tmp_path / "preview.db")
    _start(store, "turn-1")
    store.upsert_message(
        session_id="session-1",
        turn_id="turn-1",
        message=_message("user", text, role="user"),
        ordinal=0,
    )
    identity = {
        "session_id": "session-1",
        "user_id": "user-1",
        "channel": "console",
    }
    page = store.get_user_message_page(**identity)
    assert page.items[0].preview == " ".join(text.split())[:160]
    assert store.get_user_message_text(**identity, message_id="user") == text
    store.close()
