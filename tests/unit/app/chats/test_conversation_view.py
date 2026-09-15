"""Chat context comes from owned sources, not Provider hidden memory."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentscope.message import Msg, TextBlock, ThinkingBlock, ToolResultBlock

from qwenpaw.app.chats.conversation_view import (
    ConversationItem,
    conversation_items,
)
from qwenpaw.app.chats.replies import ChatReplyView
from qwenpaw.app.chats.session import SafeJSONSession
from qwenpaw.app.chats.timeline import (
    ChatTimelineJournal,
    voice_exchange_messages,
)
from qwenpaw.app.task_tracker import TaskTracker


def build(tmp_path):
    chat = SimpleNamespace(
        id="chat", session_id="session", user_id="user", channel="console"
    )
    workspace = SimpleNamespace(
        session=SafeJSONSession(str(tmp_path)),
        task_tracker=TaskTracker(),
        chat_manager=SimpleNamespace(touch_chat=AsyncMock()),
    )
    return ChatTimelineJournal(workspace, chat), workspace, chat


async def read(journal, order=10, max_turns=20, max_chars=8000):
    return json.loads(
        await journal.read_context(
            turn_id="current",
            order=order,
            max_turns=max_turns,
            max_chars=max_chars,
        )
    )


@pytest.mark.parametrize(
    "targets", [None, "original-input", [None], [1], [""]]
)
def test_invalid_query_association_does_not_replace_public_text(targets):
    message = voice_exchange_messages("q", "original words", timeline_order=1)[
        0
    ]
    message.metadata["query_target_input_ids"] = targets
    (item,) = conversation_items(message)
    assert item.text == "original words"
    assert item.input_ids == ("q",)
    assert item.query_target_input_ids == ()


@pytest.mark.asyncio
async def test_query_identity_keeps_ownership_cutoff_and_budget(tmp_path):
    journal, _, _ = build(tmp_path)
    journal.observe_voice_exchange(
        "query",
        "public question " * 200,
        "answer",
        timeline_order=1,
        query_target_input_ids=("old-input",),
    )
    journal.observe_voice_exchange(
        "future",
        "independent new work",
        timeline_order=2,
    )
    data = await journal.read_context(
        turn_id="old-input",
        order=2,
        max_turns=1,
        max_chars=700,
    )
    payload = json.loads(data)
    assert len(data) <= 700 and payload["omitted"]
    query, answer = payload["messages"]
    assert query["id"] == "query" and query["input_ids"] == ["query"]
    assert query["query_target_input_ids"] == ["old-input"]
    assert query["truncated"]
    assert answer["input_ids"] == ["query"]
    assert "query_target_input_ids" not in answer
    assert "future" not in data
    empty = json.loads(
        await journal.read_context(
            turn_id="query",
            order=2,
            max_turns=1,
            max_chars=700,
        )
    )
    assert empty["messages"] == []
    await journal.conversation_view().close()


def public_reply(text="result", block_id="b", order=2):
    return Msg(
        id="shared",
        name="assistant",
        role="assistant",
        content=[
            TextBlock(
                id=block_id,
                text=text,
                metadata={
                    "responds_to_input_ids": ["q"],
                    "run_id": "run",
                    "timeline_order": order,
                    "reply_phase": "final",
                },
            )
        ],
    )


async def test_current_snapshot_is_bounded_frozen_and_does_not_project_hints(
    tmp_path,
):
    from qwenpaw.runtime.message_convert import _request_input_to_msgs
    from qwenpaw.schemas import Message, TextContent

    journal, _, _ = build(tmp_path)
    journal.observe_voice_exchange(
        "q", "phrase", "BLUE_CAT", timeline_order=10
    )
    snapshot = await journal.read_context(max_turns=20, max_chars=4000)
    assert len(snapshot) <= 4000 and "BLUE_CAT" in snapshot
    for msg in _request_input_to_msgs(
        [Message(role="user", content=[TextContent(text="Print it")])],
        conversation_context=snapshot,
    ):
        journal.conversation_view().observe_message(msg)
    journal.observe_voice_exchange(
        "q2", "change phrase", "RED_CAT", timeline_order=11
    )
    latest = await journal.read_context(max_turns=20, max_chars=4000)
    assert "RED_CAT" not in snapshot and "RED_CAT" in latest
    assert "Prior public Chat conversation" not in latest
    assert not any(
        row["text"] == snapshot for row in json.loads(latest)["messages"]
    )


@pytest.mark.asyncio
async def test_generated_before_save_is_visible_then_becomes_durable(
    tmp_path,
):
    journal, workspace, chat = build(tmp_path)
    journal.observe_voice_exchange(
        "q",
        "question",
        "answer",
        timeline_order=1,
        generation_status="completed",
    )
    first = await read(journal)
    assert [r["text"] for r in first["messages"]] == ["question", "answer"]
    assert not any(r["persisted"] for r in first["messages"])
    await journal.append_voice_exchange(
        "q",
        "question",
        "answer",
        timeline_order=1,
        generation_status="completed",
    )
    await journal.reconcile()
    second = await read(journal)
    assert [r["id"] for r in second["messages"]] == [
        r["id"] for r in first["messages"]
    ]
    assert all(r["persisted"] for r in second["messages"])
    assert (
        journal.conversation_view()
        is ChatTimelineJournal(workspace, chat).conversation_view()
    )


@pytest.mark.asyncio
async def test_busy_agent_pending_journal_and_cold_reconnect(tmp_path):
    journal, workspace, chat = build(tmp_path)
    release = asyncio.Event()

    async def run(_):
        await release.wait()
        yield "data: done\n\n"

    await workspace.task_tracker.attach_or_start(chat.id, None, run)
    try:
        await journal.append_voice_exchange(
            "q", "question", "answer", timeline_order=1
        )
        assert await workspace.task_tracker.get_status(chat.id) == "running"
        assert len((await read(journal))["messages"]) == 2
        # New process-style owner, same durable file, no waiting for old run.
        fresh, _, _ = build(tmp_path)
        assert [m["text"] for m in (await read(fresh))["messages"]] == [
            "question",
            "answer",
        ]
    finally:
        release.set()
        await journal.reconcile()


@pytest.mark.asyncio
async def test_loading_old_snapshot_merges_newer_sources_without_quiet_retry(
    tmp_path,
):
    journal, workspace, _ = build(tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()
    old = voice_exchange_messages("q", "question", "old", timeline_order=1)

    async def loading(*_args):
        entered.set()
        await release.wait()
        return {
            "chat_timeline": {
                "pending": [m.model_dump(mode="json") for m in old]
            }
        }

    workspace.session.get_session_state_dict = AsyncMock(side_effect=loading)
    pending = asyncio.create_task(read(journal))
    await entered.wait()
    journal.observe_voice_exchange("q", "question", "new", timeline_order=1)
    for i in range(100):
        journal.observe_voice_exchange(
            f"u{i}", f"input{i}", timeline_order=i + 2
        )
    release.set()
    result = await pending
    assert (
        next(r["text"] for r in result["messages"] if r["id"] == "q_assistant")
        == "new"
    )
    assert all(r["order"] < 10 for r in result["messages"])
    workspace.session.get_session_state_dict.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_load_is_not_empty_history_and_later_turn_retries(
    tmp_path,
):
    journal, workspace, _ = build(tmp_path)
    workspace.session.get_session_state_dict = AsyncMock(
        side_effect=[OSError("unavailable"), {}]
    )
    journal.observe_voice_exchange("q", "question", "answer", timeline_order=1)
    result = await read(journal)
    assert result["available"] is False and len(result["messages"]) == 2
    assert (await read(journal))["available"] is True
    assert workspace.session.get_session_state_dict.await_count == 2


@pytest.mark.asyncio
async def test_cancelling_one_reader_does_not_cancel_shared_initialization(
    tmp_path,
):
    journal, workspace, _ = build(tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()

    async def loading(*_args):
        entered.set()
        await release.wait()
        return {}

    workspace.session.get_session_state_dict = AsyncMock(side_effect=loading)
    first = asyncio.create_task(read(journal))
    await entered.wait()
    second = asyncio.create_task(read(journal))
    first.cancel()
    await asyncio.gather(first, return_exceptions=True)
    release.set()
    assert (await second)["available"]
    workspace.session.get_session_state_dict.assert_awaited_once()


@pytest.mark.asyncio
async def test_generation_status_current_and_future_filter(tmp_path):
    journal, _, _ = build(tmp_path)
    for i, status in enumerate(
        ("completed", "cancelled", "failed", "incomplete"), 1
    ):
        journal.observe_voice_exchange(
            str(i),
            "question",
            status,
            timeline_order=i,
            generation_status=status,
        )
    journal.observe_voice_exchange("future", "future", "no", timeline_order=6)
    result = await read(journal, order=5)
    assert [
        r["text"] for r in result["messages"] if r["role"] == "assistant"
    ] == ["completed", "cancelled"]
    assert result["omitted"]
    assert not any(r["order"] >= 5 for r in result["messages"])


@pytest.mark.asyncio
async def test_public_agent_block_identity_and_live_before_voice_connect(
    tmp_path,
):
    journal, workspace, chat = build(tmp_path)
    replies = ChatReplyView()
    workspace.task_tracker.reply_views[chat.id] = replies
    for i in range(3):
        message = public_reply(str(201 + i), str(i), i + 1)
        message.content.extend(
            [
                ThinkingBlock(thinking="private"),
                ToolResultBlock(id="tool", name="tool", output="raw"),
            ]
        )
        replies.observe(message, "run")
    result = await read(journal)
    assert [m["text"] for m in result["messages"]] == ["201", "202", "203"]
    assert len({m["id"] for m in result["messages"]}) == 3
    assert not any(m["persisted"] for m in result["messages"])


@pytest.mark.asyncio
async def test_late_save_cannot_overwrite_newer_source_revision(tmp_path):
    journal, _, _ = build(tmp_path)
    old = voice_exchange_messages("q", "question", "old", timeline_order=1)
    journal.observe_voice_exchange("q", "question", "new", timeline_order=1)
    journal.conversation_view().mark_saved(old)
    row = (await read(journal))["messages"][-1]
    assert row["text"] == "new" and not row["persisted"]


@pytest.mark.asyncio
async def test_large_cold_history_then_updates_do_not_read_session_again(
    tmp_path,
):
    journal, workspace, _ = build(tmp_path)
    workspace.session.get_session_state_dict = AsyncMock(
        return_value={
            "chat_timeline": {
                "pending": [
                    m.model_dump(mode="json")
                    for i in range(1000)
                    for m in voice_exchange_messages(
                        str(i),
                        "question" * 30,
                        "answer" * 30,
                        timeline_order=i + 1,
                    )
                ]
            }
        }
    )
    await read(journal, order=1001)
    for i in range(100):
        journal.observe_voice_exchange(
            f"new{i}", "new question", "new answer", timeline_order=1001 + i
        )
        result = await read(journal, order=1101, max_chars=1800)
        assert result["omitted"]
    workspace.session.get_session_state_dict.assert_awaited_once()
    view = journal.conversation_view()
    assert len(view._items) <= 256
    assert sum(len(item.text) for item in view._items.values()) <= 64000


@pytest.mark.asyncio
async def test_encoded_budget_includes_json_escaping_and_configured_turn_limit(
    tmp_path,
):
    journal, _, _ = build(tmp_path)
    for i in range(4):
        journal.observe_voice_exchange(
            str(i), '"\\\n' * 300, "answer", timeline_order=i + 1
        )
    raw = await journal.read_context(
        turn_id="current", order=5, max_turns=1, max_chars=800
    )
    assert len(raw) <= 800
    result = json.loads(raw)
    assert result["omitted"]
    assert all(r["input_ids"] == ["3"] for r in result["messages"])


@pytest.mark.asyncio
async def test_closed_view_rejects_late_updates_and_loader(tmp_path):
    journal, _, _ = build(tmp_path)
    view = journal.conversation_view()
    await view.close()
    view.observe(
        [ConversationItem("late", 1, "user", "no", ("late",), "user")]
    )
    assert not view._items
    assert (await read(journal))["available"] is False
