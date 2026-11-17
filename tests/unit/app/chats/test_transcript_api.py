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
    ChatForkRequest,
    fork_chat_at_turn,
    batch_delete_chats,
    delete_chat,
    get_chat,
    get_chat_messages,
    get_chat_user_messages,
    get_chat_user_message_text,
)
from qwenpaw.app.task_tracker import TaskTracker
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


@pytest.fixture(autouse=True)
def chat_config_loader(monkeypatch):
    loader = AsyncMock(
        return_value=SimpleNamespace(backend="qwenpaw", backend_settings={}),
    )
    monkeypatch.setattr(
        "qwenpaw.app.workspace.workspace.load_agent_config_async",
        loader,
    )
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config_async",
        loader,
    )
    return loader


def _chat() -> ChatSpec:
    return ChatSpec(
        id="chat-1",
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )


def _workspace(store) -> SimpleNamespace:
    return SimpleNamespace(
        agent_id="test-transcript-api",
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
async def test_get_chat_returns_the_bounded_transcript_page(
    tmp_path: Path,
) -> None:
    store = TranscriptStore(tmp_path / "session.db")
    for number in range(1, 7):
        _append_turn(store, number, f"turn {number}")
    session = SimpleNamespace(get_session_state_dict=AsyncMock())

    history = await get_chat(
        chat_id="chat-1",
        full_history=False,
        background_tasks=BackgroundTasks(),
        include_app_owned=True,
        mgr=SimpleNamespace(get_chat=AsyncMock(return_value=_chat())),
        session=session,
        workspace=_workspace(store),
    )

    assert [item.content[0].text for item in history.messages] == [
        "turn 2",
        "turn 3",
        "turn 4",
        "turn 5",
        "turn 6",
    ]
    assert history.messages[0].metadata is not None
    assert history.messages[0].metadata["timestamp"]
    assert history.messages[0].metadata["qwenpaw_turn_state"] == {
        "status": "completed",
    }
    assert history.history is not None
    assert history.history.has_more is True
    session.get_session_state_dict.assert_not_awaited()
    complete = await get_chat(
        chat_id="chat-1",
        background_tasks=BackgroundTasks(),
        include_app_owned=True,
        mgr=SimpleNamespace(get_chat=AsyncMock(return_value=_chat())),
        session=SimpleNamespace(get_session_state_dict=AsyncMock()),
        workspace=_workspace(store),
    )
    assert [item.content[0].text for item in complete.messages] == [
        f"turn {number}" for number in range(1, 7)
    ]
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
@pytest.mark.parametrize("case", ["turns", "oversized-turn", "text"])
async def test_message_pages_follow_opaque_cursor_without_loss(
    tmp_path: Path,
    case: str,
) -> None:
    store = TranscriptStore(tmp_path / "session.db")
    limit = 2
    max_bytes = 2 * 1024 * 1024
    expected: str | list[str]
    if case == "turns":
        for number in range(1, 4):
            _append_turn(store, number, f"turn {number}")
        expected = [f"turn {number}" for number in range(1, 4)]
    elif case == "oversized-turn":
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
        limit = 20
        max_bytes = 3_500
        expected = ["message-1", "large-0", "large-1"]
    else:
        expected = "历史内容" * 3_000
        _append_turn(store, 1, expected)
        limit = 20
        max_bytes = 4_096
    manager = SimpleNamespace(get_chat=AsyncMock(return_value=_chat()))
    workspace = _workspace(store)

    pages = []
    before = None
    snapshot = None
    while True:
        page = await get_chat_messages(
            chat_id="chat-1",
            before=before,
            limit=limit,
            max_bytes=max_bytes,
            include_app_owned=True,
            mgr=manager,
            workspace=workspace,
        )
        assert len(page.model_dump_json().encode("utf-8")) <= max_bytes
        if snapshot is None:
            snapshot = page.snapshot
        assert page.snapshot == snapshot
        pages.append(page)
        if not page.has_more:
            break
        assert page.next_before
        assert ":" not in page.next_before
        before = page.next_before

    if case == "text":
        restored = "".join(
            page.messages[0].content[0].text for page in reversed(pages)
        )
    elif case == "turns":
        restored = [
            message.content[0].text
            for page in reversed(pages)
            for message in page.messages
        ]
    else:
        restored = [
            message.id for page in reversed(pages) for message in page.messages
        ]
    assert restored == expected
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
    chat_config_loader,
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
    chat_config_loader.return_value = workspace.config
    workspace.backend_runtime = SimpleNamespace(
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
    workspace.backend_runtime.hydrate_session.assert_not_awaited()
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
    projection_ready = asyncio.Event()
    allow_runtime = asyncio.Event()
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
        store.import_legacy_messages(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            messages=snapshot.messages,
        )
        projection_ready.set()
        await allow_runtime.wait()
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
    assert history.history.migration_pending
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

    prepared_page = asyncio.create_task(
        get_chat_messages(
            chat_id="chat-1",
            before=None,
            limit=100,
            max_bytes=2 * 1024 * 1024,
            include_app_owned=False,
            wait_for_migration=True,
            mgr=SimpleNamespace(get_chat=AsyncMock(return_value=_chat())),
            workspace=workspace,
        ),
    )
    allow_migration.set()
    await projection_ready.wait()
    identity = dict(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )
    assert store.get_page(**identity) is not None
    assert store.read_turn_context(**identity, turn_id="legacy:1") is None
    manager = SimpleNamespace(
        get_chat=AsyncMock(return_value=_chat()),
        create_chat=AsyncMock(side_effect=lambda chat: chat),
    )
    fork = asyncio.create_task(
        fork_chat_at_turn(
            chat_id="chat-1",
            payload=ChatForkRequest(turn_id="legacy:1"),
            mgr=manager,
            workspace=workspace,
        ),
    )
    try:
        await asyncio.wait({fork}, timeout=0.05)
        assert not fork.done()
        assert not prepared_page.done()
        manager.create_chat.assert_not_awaited()
    finally:
        allow_runtime.set()
    child = await asyncio.wait_for(fork, timeout=10)
    projected = await asyncio.wait_for(prepared_page, timeout=10)
    assert not projected.migration_pending
    assert (
        projected.messages[0].metadata["qwenpaw_transcript_position"][
            "turn_id"
        ]
        == "legacy:1"
    )
    assert child.fork_turn_seq == 1
    assert migration_count == 1
    inherited = store.get_page(
        session_id=child.session_id,
        user_id=child.user_id,
        channel=child.channel,
    )
    assert inherited.messages[0].content[0].text == "fallback"

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
@pytest.mark.parametrize("anonymous", [False, True])
async def test_delete_keeps_shared_session_data(anonymous: bool) -> None:
    first = _chat()
    if anonymous:
        first = first.model_copy(update={"user_id": ""})
    second = first.model_copy(
        update={
            "id": "chat-2",
            "user_id": first.session_id if anonymous else first.user_id,
        },
    )
    store = Mock(spec=TranscriptCatalog)
    manager = SimpleNamespace(
        get_chat=AsyncMock(return_value=first),
        list_chats=AsyncMock(return_value=[first, second]),
        delete_chats=AsyncMock(return_value=True),
        mark_deleting=AsyncMock(),
    )
    workspace = SimpleNamespace(
        transcript_store=store,
        session=None,
        task_tracker=SimpleNamespace(
            prevent_new_runs=TaskTracker().prevent_new_runs,
            stop_session_writers=TaskTracker().stop_session_writers,
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
        mark_deleting=AsyncMock(),
    )
    workspace = SimpleNamespace(
        transcript_store=store,
        session=None,
        task_tracker=SimpleNamespace(
            request_stop=AsyncMock(),
            prevent_new_runs=TaskTracker().prevent_new_runs,
            stop_session_writers=TaskTracker().stop_session_writers,
        ),
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
    assert store.delete_session.call_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("batch", [False, True])
async def test_delete_stops_running_chat(batch: bool) -> None:
    chat = _chat()
    shared = chat.model_copy(update={"id": "chat-2"})
    manager = SimpleNamespace(
        get_chat=AsyncMock(return_value=chat),
        list_chats=AsyncMock(return_value=[chat, shared]),
        delete_chats=AsyncMock(return_value=True),
        mark_deleting=AsyncMock(),
    )
    workspace = SimpleNamespace(
        task_tracker=SimpleNamespace(
            prevent_new_runs=TaskTracker().prevent_new_runs,
            stop_session_writers=TaskTracker().stop_session_writers,
            request_stop=AsyncMock(return_value=True),
        ),
    )

    if batch:
        result = await batch_delete_chats(
            chat_ids=[chat.id],
            mgr=manager,
            workspace=workspace,
        )
    else:
        result = await delete_chat(
            chat_id=chat.id,
            mgr=manager,
            workspace=workspace,
        )

    assert result == {"deleted": True}
    workspace.task_tracker.request_stop.assert_awaited_once_with(chat.id)
    if not batch:
        manager.list_chats.assert_awaited_once_with(archived=None)
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
