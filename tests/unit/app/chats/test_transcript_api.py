# -*- coding: utf-8 -*-
"""API tests for durable transcript reads and cursor pagination."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from agentscope.message import Msg
from agentscope.state import AgentState
from fastapi import BackgroundTasks, HTTPException

from qwenpaw.app.chats.api import (
    _delete_chat_data,
    batch_delete_chats,
    delete_chat,
    get_chat,
    get_chat_messages,
    get_chat_user_messages,
    get_chat_user_message_text,
)
from qwenpaw.app.chats.models import ChatSpec
from qwenpaw.app.chats.session import (
    DatabaseSession,
    LegacyConversationSnapshot,
    SafeJSONSession,
    session_filename,
)
from qwenpaw.app.chats.transcript import TranscriptStore
from qwenpaw.app.chats.transcript_catalog import TranscriptCatalog
from qwenpaw.schemas import Message, Role, RunStatus, TextContent
from qwenpaw.token_usage.turn_usage import TURN_USAGE_META_KEY


def _chat() -> ChatSpec:
    return ChatSpec(
        id="chat-1",
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )


def _workspace(store) -> SimpleNamespace:
    return SimpleNamespace(
        transcript_store=store,
        config=SimpleNamespace(backend="qwenpaw"),
        task_tracker=SimpleNamespace(
            get_status=AsyncMock(return_value="running"),
        ),
    )


def _append_turn(
    store: TranscriptStore,
    number: int,
    text: str,
) -> None:
    turn_id = f"turn-{number}"
    store.start_turn(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        turn_id=turn_id,
    )
    store.upsert_message(
        session_id="session-1",
        turn_id=turn_id,
        message=Message(
            id=f"message-{number}",
            role=Role.USER,
            content=[TextContent(text=text)],
            status=RunStatus.Completed,
        ),
        ordinal=0,
    )
    store.finish_turn(
        session_id="session-1",
        turn_id=turn_id,
        status="completed",
    )


@pytest.mark.asyncio
async def test_get_chat_prefers_transcript_page(tmp_path: Path) -> None:
    store = TranscriptStore(tmp_path / "session.db")
    _append_turn(store, 1, "durable")
    session = SimpleNamespace(get_session_state_dict=AsyncMock())

    history = await get_chat(
        chat_id="chat-1",
        background_tasks=BackgroundTasks(),
        include_app_owned=True,
        mgr=SimpleNamespace(get_chat=AsyncMock(return_value=_chat())),
        session=session,
        workspace=_workspace(store),
    )

    assert history.messages[0].content[0].text == "durable"
    assert history.messages[0].metadata is not None
    assert history.messages[0].metadata["timestamp"]
    assert history.messages[0].metadata["qwenpaw_turn_state"] == {
        "status": "completed",
    }
    assert history.history is not None
    assert history.history.has_more is False
    session.get_session_state_dict.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_chat_returns_at_most_five_turns(tmp_path: Path) -> None:
    store = TranscriptStore(tmp_path / "session.db")
    for number in range(1, 7):
        _append_turn(store, number, f"turn {number}")

    history = await get_chat(
        chat_id="chat-1",
        background_tasks=BackgroundTasks(),
        include_app_owned=True,
        mgr=SimpleNamespace(get_chat=AsyncMock(return_value=_chat())),
        session=SimpleNamespace(get_session_state_dict=AsyncMock()),
        workspace=_workspace(store),
    )

    assert [item.content[0].text for item in history.messages] == [
        "turn 2",
        "turn 3",
        "turn 4",
        "turn 5",
        "turn 6",
    ]
    assert history.history is not None
    assert history.history.has_more is True
    store.close()


@pytest.mark.asyncio
async def test_history_page_budget_error_is_not_a_cursor_error(
    tmp_path: Path,
) -> None:
    store = TranscriptStore(tmp_path / "session.db")
    _append_turn(store, 1, "short input")
    arguments = {
        "chat_id": "chat-1",
        "before": None,
        "after_message_id": None,
        "limit": 5,
        "include_app_owned": True,
        "mgr": SimpleNamespace(get_chat=AsyncMock(return_value=_chat())),
        "workspace": _workspace(store),
    }
    page = await get_chat_messages(max_bytes=2048, **arguments)
    assert [message.id for message in page.messages] == ["message-1"]

    with pytest.raises(HTTPException) as error:
        await get_chat_messages(max_bytes=1, **arguments)
    assert error.value.status_code == 400
    assert error.value.detail == "History page byte limit is too small"
    store.close()


@pytest.mark.asyncio
async def test_user_message_index_anchor_locates_unloaded_turn(
    tmp_path: Path,
) -> None:
    store = TranscriptStore(tmp_path / "session.db")
    for number in range(1, 8):
        _append_turn(store, number, f"turn {number}")
    manager = SimpleNamespace(get_chat=AsyncMock(return_value=_chat()))
    workspace = _workspace(store)

    index = await get_chat_user_messages(
        chat_id="chat-1",
        before=None,
        limit=200,
        include_app_owned=True,
        mgr=manager,
        workspace=workspace,
    )
    target = next(
        item for item in index.items if item.message_id == "message-2"
    )
    page = await get_chat_messages(
        chat_id="chat-1",
        before=target.anchor,
        limit=5,
        max_bytes=2 * 1024 * 1024,
        include_app_owned=True,
        mgr=manager,
        workspace=workspace,
    )

    assert [message.id for message in page.messages] == [
        "message-1",
        "message-2",
    ]

    newest = index.items[-1]
    newest_page = await get_chat_messages(
        chat_id="chat-1",
        before=newest.anchor,
        limit=5,
        max_bytes=2 * 1024 * 1024,
        include_app_owned=True,
        mgr=manager,
        workspace=workspace,
    )

    assert [message.id for message in newest_page.messages][-1] == "message-7"
    store.close()


@pytest.mark.asyncio
async def test_get_chat_restores_durable_turn_usage(tmp_path: Path) -> None:
    store = TranscriptStore(tmp_path / "session.db")
    store.start_turn(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        turn_id="turn-1",
    )
    store.upsert_message(
        session_id="session-1",
        turn_id="turn-1",
        message=Message(
            id="assistant-1",
            role=Role.ASSISTANT,
            content=[TextContent(text="answer")],
        ).completed(),
        ordinal=0,
    )
    store.finish_turn(
        session_id="session-1",
        turn_id="turn-1",
        status="completed",
    )
    usage = {
        "provider_id": "dashscope",
        "model_name": "qwen3.8-max",
        "total_tokens": 461440,
        "cache_hit_rate": 87.2869,
    }
    context_usage = {
        "estimated_tokens": 14467,
        "max_input_length": 1000000,
        "context_usage_ratio": 1.4467,
    }
    store.attach_turn_usage(
        session_id="session-1",
        turn_id="turn-1",
        usage=usage,
        context_usage=context_usage,
    )

    history = await get_chat(
        chat_id="chat-1",
        background_tasks=BackgroundTasks(),
        include_app_owned=True,
        mgr=SimpleNamespace(get_chat=AsyncMock(return_value=_chat())),
        session=SimpleNamespace(get_session_state_dict=AsyncMock()),
        workspace=_workspace(store),
    )

    assert history.messages[0].metadata[TURN_USAGE_META_KEY] == {
        "usage": usage,
        "context_usage": context_usage,
    }
    store.close()


@pytest.mark.asyncio
async def test_message_pages_use_opaque_item_cursor(tmp_path: Path) -> None:
    store = TranscriptStore(tmp_path / "session.db")
    for number in range(1, 4):
        _append_turn(store, number, f"turn {number}")
    manager = SimpleNamespace(get_chat=AsyncMock(return_value=_chat()))
    workspace = _workspace(store)

    newest = await get_chat_messages(
        chat_id="chat-1",
        before=None,
        limit=2,
        include_app_owned=True,
        mgr=manager,
        workspace=workspace,
    )
    older = await get_chat_messages(
        chat_id="chat-1",
        before=newest.next_before,
        limit=2,
        include_app_owned=True,
        mgr=manager,
        workspace=workspace,
    )

    assert [item.content[0].text for item in newest.messages] == [
        "turn 2",
        "turn 3",
    ]
    assert newest.next_before
    assert ":" not in newest.next_before
    assert newest.snapshot
    assert newest.has_more is True
    assert [item.content[0].text for item in older.messages] == ["turn 1"]
    assert older.snapshot == newest.snapshot
    assert older.next_before is None
    assert older.has_more is False


@pytest.mark.asyncio
async def test_message_pages_continue_within_oversized_turn(
    tmp_path: Path,
) -> None:
    store = TranscriptStore(tmp_path / "session.db")
    _append_turn(store, 1, "older")
    store.start_turn(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        turn_id="turn-2",
    )
    for ordinal, role in enumerate((Role.USER, Role.ASSISTANT)):
        store.upsert_message(
            session_id="session-1",
            turn_id="turn-2",
            message=Message(
                id=f"large-{ordinal}",
                role=role,
                content=[TextContent(text="x" * 2_000)],
                status=RunStatus.Completed,
            ),
            ordinal=ordinal,
        )
    store.finish_turn(
        session_id="session-1",
        turn_id="turn-2",
        status="completed",
    )
    manager = SimpleNamespace(get_chat=AsyncMock(return_value=_chat()))
    workspace = _workspace(store)

    newest = await get_chat_messages(
        chat_id="chat-1",
        before=None,
        limit=20,
        max_bytes=3_500,
        include_app_owned=True,
        mgr=manager,
        workspace=workspace,
    )
    middle = await get_chat_messages(
        chat_id="chat-1",
        before=newest.next_before,
        limit=20,
        max_bytes=3_500,
        include_app_owned=True,
        mgr=manager,
        workspace=workspace,
    )
    older = await get_chat_messages(
        chat_id="chat-1",
        before=middle.next_before,
        limit=20,
        max_bytes=3_500,
        include_app_owned=True,
        mgr=manager,
        workspace=workspace,
    )

    assert [item.id for item in newest.messages] == ["large-1"]
    assert newest.next_before
    assert [item.id for item in middle.messages] == ["large-0"]
    assert middle.next_before
    assert middle.next_before != newest.next_before
    assert middle.snapshot == newest.snapshot
    assert [item.id for item in older.messages] == ["message-1"]
    assert older.snapshot == newest.snapshot
    assert older.has_more is False
    store.close()


@pytest.mark.asyncio
async def test_message_pages_restore_one_oversized_text_block(
    tmp_path: Path,
) -> None:
    store = TranscriptStore(tmp_path / "session.db")
    text = "历史内容" * 3_000
    _append_turn(store, 1, text)
    manager = SimpleNamespace(get_chat=AsyncMock(return_value=_chat()))
    workspace = _workspace(store)

    fragments = []
    before = None
    snapshot = None
    while True:
        page = await get_chat_messages(
            chat_id="chat-1",
            before=before,
            limit=20,
            max_bytes=4_096,
            include_app_owned=True,
            mgr=manager,
            workspace=workspace,
        )
        assert len(page.messages) == 1
        assert len(page.model_dump_json().encode("utf-8")) <= 4_096
        if snapshot is None:
            snapshot = page.snapshot
        assert page.snapshot == snapshot
        fragments.append(page.messages[0].content[0].text)
        if not page.has_more:
            break
        assert page.next_before
        assert ":" not in page.next_before
        before = page.next_before

    assert len(fragments) > 1
    assert "".join(reversed(fragments)) == text
    store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cursor",
    ("turn:2", "1:2:3", "2", "0:0", "2:-1"),
)
async def test_message_page_rejects_invalid_cursor(
    cursor: str,
    tmp_path: Path,
) -> None:
    store = TranscriptStore(tmp_path / "session.db")
    with pytest.raises(HTTPException) as raised:
        await get_chat_messages(
            chat_id="chat-1",
            before=cursor,
            limit=50,
            include_app_owned=True,
            mgr=SimpleNamespace(get_chat=AsyncMock(return_value=_chat())),
            workspace=_workspace(store),
        )

    assert raised.value.status_code == 400
    store.close()


@pytest.mark.asyncio
async def test_message_pages_keep_a_stable_turn_snapshot(
    tmp_path: Path,
) -> None:
    store = TranscriptStore(tmp_path / "session.db")
    for number in range(1, 4):
        _append_turn(store, number, f"turn {number}")
    manager = SimpleNamespace(get_chat=AsyncMock(return_value=_chat()))
    workspace = _workspace(store)

    newest = await get_chat_messages(
        chat_id="chat-1",
        before=None,
        limit=1,
        include_app_owned=True,
        mgr=manager,
        workspace=workspace,
    )
    _append_turn(store, 4, "turn 4")
    older = await get_chat_messages(
        chat_id="chat-1",
        before=newest.next_before,
        limit=1,
        include_app_owned=True,
        mgr=manager,
        workspace=workspace,
    )
    refreshed = await get_chat_messages(
        chat_id="chat-1",
        before=None,
        limit=1,
        include_app_owned=True,
        mgr=manager,
        workspace=workspace,
    )

    assert [item.content[0].text for item in newest.messages] == ["turn 3"]
    assert [item.content[0].text for item in older.messages] == ["turn 2"]
    assert older.snapshot == newest.snapshot
    assert [item.content[0].text for item in refreshed.messages] == ["turn 4"]
    assert refreshed.snapshot != newest.snapshot
    store.close()


@pytest.mark.asyncio
async def test_message_page_hides_app_owned_chat() -> None:
    chat = _chat().model_copy(
        update={"meta": {"pawapp": {"app_id": "app-1"}}},
    )

    with pytest.raises(HTTPException) as raised:
        await get_chat_messages(
            chat_id=chat.id,
            before=None,
            limit=20,
            include_app_owned=False,
            mgr=SimpleNamespace(get_chat=AsyncMock(return_value=chat)),
            workspace=_workspace(None),
        )

    assert raised.value.status_code == 404


@pytest.mark.asyncio
async def test_get_chat_falls_back_without_transcript() -> None:
    fallback = Msg(
        name="user",
        role="user",
        content=[{"type": "text", "text": "fallback"}],
    )
    state = AgentState(context=[fallback]).model_dump(mode="json")
    session = SimpleNamespace(
        get_session_state_dict=AsyncMock(
            return_value={"agent": {"state": state}},
        ),
    )

    history = await get_chat(
        chat_id="chat-1",
        background_tasks=BackgroundTasks(),
        include_app_owned=True,
        mgr=SimpleNamespace(get_chat=AsyncMock(return_value=_chat())),
        session=session,
        workspace=_workspace(None),
    )

    assert history.messages[0].content[0].text == "fallback"
    assert history.history is not None
    assert history.history.has_more is False


@pytest.mark.asyncio
async def test_get_chat_reads_harness_runtime_instead_of_empty_transcript(
    tmp_path: Path,
) -> None:
    fallback = Msg(
        name="assistant",
        role="assistant",
        content=[{"type": "text", "text": "harness reply"}],
    )
    state = AgentState(context=[fallback]).model_dump(mode="json")
    store = TranscriptCatalog(tmp_path)
    store.write_runtime_state(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        state={"agent": {"state": state}},
    )
    session = DatabaseSession(
        catalog=store,
        legacy_save_dir=str(tmp_path / "sessions"),
    )
    workspace = _workspace(store)
    workspace.config = SimpleNamespace(
        backend="codex",
        backend_settings={},
    )
    workspace.harness_runtime = SimpleNamespace(
        hydrate_session=AsyncMock(),
    )
    tasks = BackgroundTasks()

    history = await get_chat(
        chat_id="chat-1",
        background_tasks=tasks,
        include_app_owned=True,
        mgr=SimpleNamespace(get_chat=AsyncMock(return_value=_chat())),
        session=session,
        workspace=workspace,
    )

    assert [message.content[0].text for message in history.messages] == [
        "harness reply",
    ]
    assert history.history is not None
    assert history.history.has_more is False
    assert not tasks.tasks
    workspace.harness_runtime.hydrate_session.assert_not_awaited()
    store.close()


@pytest.mark.asyncio
async def test_legacy_reads_return_before_shared_migration_finishes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fallback = Msg(
        name="user",
        role="user",
        content=[{"type": "text", "text": "fallback"}],
    )
    state = AgentState(context=[fallback]).model_dump(mode="json")
    legacy_dir = tmp_path / "sessions"
    legacy_dir.mkdir()
    (legacy_dir / session_filename("session-1", "user-1")).write_text(
        json.dumps({"agent": {"state": state}}),
        encoding="utf-8",
    )
    store = TranscriptCatalog(tmp_path)
    session = DatabaseSession(
        catalog=store,
        legacy_save_dir=str(legacy_dir),
    )
    migration_started = asyncio.Event()
    allow_migration = asyncio.Event()
    migrate = getattr(session, "_migrate_legacy_snapshot")
    migration_count = 0

    async def delayed_migration(
        *,
        session_id: str,
        user_id: str,
        channel: str,
        snapshot: LegacyConversationSnapshot,
    ) -> bool:
        nonlocal migration_count
        migration_count += 1
        migration_started.set()
        await allow_migration.wait()
        return await migrate(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            snapshot=snapshot,
        )

    monkeypatch.setattr(
        session,
        "_migrate_legacy_snapshot",
        delayed_migration,
    )
    workspace = _workspace(store)
    workspace.session = session

    history = await get_chat(
        chat_id="chat-1",
        background_tasks=BackgroundTasks(),
        include_app_owned=True,
        mgr=SimpleNamespace(get_chat=AsyncMock(return_value=_chat())),
        session=session,
        workspace=workspace,
    )
    await migration_started.wait()

    assert history.messages[0].content[0].text == "fallback"
    assert (
        store.get_page(
            session_id="session-1",
            user_id="user-1",
            channel="console",
        )
        is None
    )
    page_before_migration = await get_chat_messages(
        chat_id="chat-1",
        before=None,
        after_message_id=None,
        limit=5,
        max_bytes=2 * 1024 * 1024,
        include_app_owned=True,
        mgr=SimpleNamespace(get_chat=AsyncMock(return_value=_chat())),
        workspace=workspace,
    )
    assert page_before_migration.messages[0].content[0].text == "fallback"
    index = await get_chat_user_messages(
        chat_id="chat-1",
        before=None,
        limit=200,
        include_app_owned=True,
        mgr=SimpleNamespace(get_chat=AsyncMock(return_value=_chat())),
        workspace=workspace,
    )
    assert index.items[0].preview == "fallback"
    full = await get_chat_user_message_text(
        chat_id="chat-1",
        message_id=history.messages[0].id,
        mgr=SimpleNamespace(get_chat=AsyncMock(return_value=_chat())),
        workspace=workspace,
    )
    assert full == {"text": "fallback"}
    assert migration_count == 1

    allow_migration.set()
    await session.ensure_legacy_migrated(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )

    page = store.get_page(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )
    assert page is not None
    assert page.messages[0].content[0].text == "fallback"
    store.close()


@pytest.mark.asyncio
async def test_delete_chat_data_removes_all_persistence(
    tmp_path: Path,
) -> None:
    store = TranscriptCatalog(tmp_path)
    _append_turn(store, 1, "durable")
    session = SafeJSONSession(save_dir=str(tmp_path / "sessions"))
    await session.update_session_state(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        key="agent.value",
        value=1,
    )
    checkpoint_delete = AsyncMock()
    workspace = SimpleNamespace(
        transcript_store=store,
        session=session,
    )

    with patch(
        "qwenpaw.app.chats.api.CHECKPOINT_RUNTIME."
        "delete_session_checkpoints",
        checkpoint_delete,
    ):
        await _delete_chat_data(workspace, [_chat()])

    assert (
        store.get_page(
            session_id="session-1",
            user_id="user-1",
            channel="console",
        )
        is None
    )
    assert (
        await session.get_session_state_dict(
            "session-1",
            "user-1",
            "console",
        )
        == {}
    )
    checkpoint_delete.assert_awaited_once_with(
        workspace,
        [("session-1", "user-1", "console")],
    )
    store.close()


@pytest.mark.asyncio
async def test_delete_keeps_shared_session_data() -> None:
    first = _chat()
    second = first.model_copy(update={"id": "chat-2"})
    store = Mock(spec=TranscriptCatalog)
    manager = SimpleNamespace(
        get_chat=AsyncMock(return_value=first),
        list_chats=AsyncMock(return_value=[first, second]),
        delete_chats=AsyncMock(return_value=True),
    )
    workspace = SimpleNamespace(
        transcript_store=store,
        session=None,
        task_tracker=SimpleNamespace(
            request_stop=AsyncMock(return_value=False),
        ),
    )

    result = await delete_chat(
        chat_id=first.id,
        mgr=manager,
        workspace=workspace,
    )

    assert result == {"deleted": True}
    store.delete_session.assert_not_called()
    workspace.task_tracker.request_stop.assert_awaited_once_with(first.id)
    manager.delete_chats.assert_awaited_once_with(chat_ids=[first.id])


@pytest.mark.asyncio
async def test_delete_keeps_mapping_when_data_cleanup_fails() -> None:
    chat = _chat()
    store = Mock(spec=TranscriptCatalog)
    manager = SimpleNamespace(
        get_chat=AsyncMock(return_value=chat),
        list_chats=AsyncMock(return_value=[chat]),
        delete_chats=AsyncMock(return_value=True),
    )
    workspace = SimpleNamespace(
        transcript_store=store,
        session=None,
        task_tracker=SimpleNamespace(request_stop=AsyncMock()),
    )
    checkpoint_delete = AsyncMock(side_effect=[OSError("disk error"), None])

    with patch(
        "qwenpaw.app.chats.api.CHECKPOINT_RUNTIME."
        "delete_session_checkpoints",
        checkpoint_delete,
    ):
        with pytest.raises(HTTPException, match="Failed to delete"):
            await delete_chat(
                chat_id=chat.id,
                mgr=manager,
                workspace=workspace,
            )
        manager.delete_chats.assert_not_awaited()
        result = await delete_chat(
            chat_id=chat.id,
            mgr=manager,
            workspace=workspace,
        )

    assert result == {"deleted": True}
    manager.delete_chats.assert_awaited_once_with(chat_ids=[chat.id])
    assert store.delete_session.call_count == 2


@pytest.mark.asyncio
async def test_delete_stops_running_chat() -> None:
    chat = _chat()
    shared = chat.model_copy(update={"id": "chat-2"})
    manager = SimpleNamespace(
        get_chat=AsyncMock(return_value=chat),
        list_chats=AsyncMock(return_value=[chat, shared]),
        delete_chats=AsyncMock(return_value=True),
    )
    workspace = SimpleNamespace(
        task_tracker=SimpleNamespace(
            request_stop=AsyncMock(return_value=True),
        ),
    )

    result = await delete_chat(
        chat_id=chat.id,
        mgr=manager,
        workspace=workspace,
    )

    assert result == {"deleted": True}
    workspace.task_tracker.request_stop.assert_awaited_once_with(chat.id)
    manager.list_chats.assert_awaited_once_with(archived=None)
    manager.delete_chats.assert_awaited_once_with(chat_ids=[chat.id])


@pytest.mark.asyncio
async def test_batch_delete_stops_running_chat() -> None:
    chat = _chat()
    shared = chat.model_copy(update={"id": "chat-2"})
    manager = SimpleNamespace(
        list_chats=AsyncMock(return_value=[chat, shared]),
        delete_chats=AsyncMock(return_value=True),
    )
    workspace = SimpleNamespace(
        task_tracker=SimpleNamespace(
            request_stop=AsyncMock(return_value=True),
        ),
    )

    result = await batch_delete_chats(
        chat_ids=[chat.id],
        mgr=manager,
        workspace=workspace,
    )

    assert result == {"deleted": True}
    workspace.task_tracker.request_stop.assert_awaited_once_with(chat.id)
    manager.delete_chats.assert_awaited_once_with(chat_ids=[chat.id])


@pytest.mark.asyncio
async def test_user_recall_index_and_full_text(tmp_path):
    store = TranscriptCatalog(tmp_path)
    _append_turn(store, 1, "short")
    original = "first\n  second " + "x" * 200
    _append_turn(store, 2, original)
    manager = SimpleNamespace(get_chat=AsyncMock(return_value=_chat()))
    workspace = _workspace(store)
    page = await get_chat_user_messages(
        chat_id="chat-1",
        before=None,
        limit=50,
        include_app_owned=False,
        mgr=manager,
        workspace=workspace,
    )
    assert [item.preview for item in page.items] == [
        "short",
        " ".join(original.split())[:160],
    ]
    result = await get_chat_user_message_text(
        chat_id="chat-1",
        message_id="message-2",
        mgr=manager,
        workspace=workspace,
    )
    assert result == {"text": original}
    with pytest.raises(HTTPException) as error:
        await get_chat_user_message_text(
            chat_id="chat-1",
            message_id="missing",
            mgr=manager,
            workspace=workspace,
        )
    assert error.value.status_code == 404
    store.close()
