# -*- coding: utf-8 -*-
"""API tests for durable transcript reads and cursor pagination."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from agentscope.message import Msg
from agentscope.state import AgentState
from fastapi import BackgroundTasks, HTTPException

from qwenpaw.app.chats.api import (
    _delete_chat_data,
    _history_fork_capabilities,
    ChatForkRequest,
    fork_chat_at_turn,
    batch_delete_chats,
    delete_chat,
    get_chat,
    get_chat_messages,
    get_chat_user_messages,
    get_chat_user_message_text,
    recover_pending_forks,
)
from qwenpaw.app.task_tracker import TaskTracker
from qwenpaw.app.task_tracker import RunUnavailableError
from qwenpaw.app.workspace.workspace import Workspace
from qwenpaw.app.chats.models import ChatSpec
from qwenpaw.app.chats.manager import ChatManager
from qwenpaw.app.chats.repo import JsonChatRepository
from qwenpaw.app.chats.session import (
    DatabaseSession,
    LegacyConversationSnapshot,
    SafeJSONSession,
    session_filename,
)
from qwenpaw.app.chats.transcript import TranscriptStore
from qwenpaw.app.chats.transcript_catalog import TranscriptCatalog
from qwenpaw.schemas import AgentRequest, Message, Role, RunStatus, TextContent
from qwenpaw.token_usage.turn_usage import TURN_USAGE_META_KEY


@pytest.mark.asyncio
async def test_migration_identity_does_not_hide_legacy_history(tmp_path):
    legacy = tmp_path / "sessions"
    legacy.mkdir()
    state = AgentState(
        context=[
            Msg(
                name="user",
                role="user",
                content=[
                    {"type": "text", "text": "old question"},
                ],
            ),
        ],
    )
    (legacy / session_filename("session-1", "user-1")).write_text(
        json.dumps({"agent": {"state": state.model_dump(mode="json")}}),
        encoding="utf-8",
    )
    store = TranscriptCatalog(tmp_path)
    identity = dict(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )
    store.record_legacy_migration(**identity)
    path = (
        tmp_path / "transcripts" / (store.storage_id_for(**identity) + ".db")
    )
    # Model the proposed marker/identity transaction before importing rows.
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT OR IGNORE INTO transcript_sessions "
            "(session_id, storage_id, user_id, channel) VALUES (?, ?, ?, ?)",
            ("session-1", path.stem, "user-1", "console"),
        )
    session = DatabaseSession(catalog=store, legacy_save_dir=str(legacy))
    workspace = _workspace(store)
    workspace.session = session
    try:
        history = await get_chat(
            chat_id="chat-1",
            background_tasks=BackgroundTasks(),
            include_app_owned=True,
            mgr=SimpleNamespace(get_chat=AsyncMock(return_value=_chat())),
            session=session,
            workspace=workspace,
        )
        assert [m.content[0].text for m in history.messages] == [
            "old question",
        ]
    finally:
        await session.ensure_legacy_migrated(**identity)
        store.close()


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
    tracker = TaskTracker()
    tracker.get_status = AsyncMock(return_value="running")
    return SimpleNamespace(
        agent_id="test-transcript-api",
        transcript_store=store,
        config=SimpleNamespace(backend="qwenpaw"),
        task_tracker=tracker,
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
    assert history.steer_scope == (
        "test-transcript-api:('session-1', 'user-1', 'console')"
    )
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
    assert complete.steer_scope == history.steer_scope
    store.start_turn(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        turn_id="cancel-before-output",
    )
    store.upsert_message(
        session_id="session-1",
        turn_id="cancel-before-output",
        ordinal=0,
        message=Message(
            id="initial",
            role="user",
            content=[
                TextContent(text="ordinary input"),
            ],
        ),
    )
    store.accept_steer(
        session_id="session-1",
        turn_id="cancel-before-output",
        client_message_id="failed-file",
        content=[
            {
                "type": "file",
                "file_url": "/media/probe.txt",
                "file_name": "probe.txt",
            },
        ],
    )
    store.fail_steers(
        session_id="session-1",
        turn_id="cancel-before-output",
        reason="cancelled",
    )
    store.finish_turn(
        session_id="session-1",
        turn_id="cancel-before-output",
        status="cancelled",
    )
    arguments = dict(
        chat_id="chat-1",
        before=None,
        after_message_id=None,
        before_message_id=None,
        limit=1,
        max_bytes=4096,
        include_app_owned=True,
        mgr=SimpleNamespace(get_chat=AsyncMock(return_value=_chat())),
        workspace=_workspace(store),
    )
    page = await get_chat_messages(**arguments)
    assert page.steer_scope == history.steer_scope
    assert page.turn_fork_capabilities == {"cancel-before-output": False}
    assert page.steer["needs_sync"] is False
    assert page.steer["active_turn_id"] is None
    page_receipts = page.steer["receipts_by_turn"]["cancel-before-output"]
    assert len(page_receipts) == 1
    assert page_receipts[0]["status"] == "failed"
    assert page_receipts[0]["content"][0]["file_name"] == "probe.txt"
    assert len(page.model_dump_json().encode()) <= 4096
    oversized = {
        **page_receipts[0],
        "content": [
            {"type": "text", "text": "x" * 8192},
        ],
    }
    with patch.object(
        store,
        "history_steers",
        return_value={
            "cancel-before-output": [oversized],
        },
    ):
        with pytest.raises(HTTPException) as budget:
            await get_chat_messages(**arguments)
        assert budget.value.status_code == 400
        assert budget.value.detail == "History page byte limit is too small"
    with patch.object(store, "history_steers", side_effect=OSError("bad")):
        with pytest.raises(HTTPException) as unavailable:
            await get_chat_messages(**arguments)
        assert unavailable.value.status_code == 503
    with patch.object(store, "can_fork_turn", return_value=True) as capability:
        available_page = await get_chat_messages(**arguments)
        assert available_page.turn_fork_capabilities == {
            "cancel-before-output": True,
        }
        assert capability.call_count == 1
    with patch.object(store, "can_fork_turn", side_effect=ValueError("bad")):
        unavailable_page = await get_chat_messages(**arguments)
        assert unavailable_page.messages == page.messages
        assert unavailable_page.turn_fork_capabilities == {
            "cancel-before-output": False,
        }
    assert [m.id for m in page.messages] == ["initial"]
    assert page.messages[0].metadata["qwenpaw_turn_state"]["status"] == (
        "canceled"
    )
    receipt = store.list_steers(session_id="session-1", latest=True)[0]
    assert receipt["status"] == "failed"
    assert receipt["content"][0]["file_name"] == "probe.txt"
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
    child_page = await get_chat_messages(
        chat_id=child.id,
        before=None,
        limit=5,
        include_app_owned=True,
        mgr=SimpleNamespace(get_chat=AsyncMock(return_value=child)),
        workspace=workspace,
    )
    assert child_page.steer_scope != projected.steer_scope
    assert child.session_id in child_page.steer_scope

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
@pytest.mark.parametrize("failure", ["checkpoint", "staged"])
async def test_delete_retry_finishes_original_storage(
    tmp_path,
    monkeypatch,
    failure,
):
    manager = ChatManager(repo=JsonChatRepository(tmp_path / "chats.json"))
    chat = await manager.create_chat(_chat())
    store = TranscriptCatalog(tmp_path)
    _append_turn(store, 1, "original")
    identity = dict(
        session_id=chat.session_id,
        user_id=chat.user_id,
        channel=chat.channel,
    )
    workspace = SimpleNamespace(
        transcript_store=store,
        chat_manager=manager,
        session=DatabaseSession(
            catalog=store,
            legacy_save_dir=str(tmp_path / "sessions"),
        ),
        task_tracker=TaskTracker(),
    )
    unlink = Path.unlink
    failed = False

    def fail_once(path, *args, **kwargs):
        nonlocal failed
        if (
            failure == "staged"
            and not failed
            and path.name.startswith(
                ".deleting-",
            )
        ):
            failed = True
            raise OSError("busy")
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_once)
    cleanup_entered = asyncio.Event()
    cleanup_release = asyncio.Event()
    checkpoint_calls = 0

    async def cleanup_checkpoint(*_args):
        nonlocal checkpoint_calls
        checkpoint_calls += 1
        if checkpoint_calls == 1:
            if failure == "checkpoint":
                raise OSError("busy")
        else:
            cleanup_entered.set()
            await cleanup_release.wait()

    checkpoint = AsyncMock(side_effect=cleanup_checkpoint)
    monkeypatch.setattr(
        "qwenpaw.app.chats.api.CHECKPOINT_RUNTIME."
        "delete_session_checkpoints",
        checkpoint,
    )
    try:
        assert await delete_chat(chat.id, manager, workspace) == {
            "deleted": True,
        }
        assert store.has_pending_session_deletion(**identity)
        pending = store.pending_deletion_operations()[0]
        assert pending["targets"][0]["storage_id"] == chat.storage_id
        replacement = await manager.get_or_create_chat(**identity)
        assert replacement.id != chat.id
        workspace._manager = None
        workspace._stream_query = Mock()
        stream = Workspace.stream_query.__wrapped__(
            workspace,
            AgentRequest(**identity, input=[]),
        )
        with pytest.raises(RunUnavailableError, match="deletion is pending"):
            await anext(stream)
        workspace._stream_query.assert_not_called()
        with pytest.raises(RuntimeError, match="deletion is pending"):
            store.ensure_empty_session_database(**identity)
        retry = asyncio.create_task(delete_chat(chat.id, manager, workspace))
        await asyncio.wait_for(cleanup_entered.wait(), 5)
        retry.cancel()
        try:
            with pytest.raises(RunUnavailableError):
                async with workspace.task_tracker.session_execution(
                    tuple(identity.values()),
                    owner="probe",
                    can_start=AsyncMock(return_value=True),
                ):
                    pytest.fail("Cleanup released its writer protection")
        finally:
            cleanup_release.set()
        with pytest.raises(asyncio.CancelledError):
            await retry
        assert not store.pending_deletion_operations()
        assert not list((tmp_path / "transcripts").glob(".deleting-*"))
        _append_turn(store, 2, "replacement")
        assert store.storage_id_for(**identity) == replacement.storage_id
        assert [
            m.content[0].text for m in store.get_page(**identity).messages
        ] == [
            "replacement",
        ]
    finally:
        store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ("copy", "registration"))
async def test_fork_cancellation_waits_for_consistent_finish(
    phase: str,
) -> None:
    parent = _chat().model_copy(
        update={"meta": {"deletion_pending": True, "keep": "value"}},
    )
    reached = asyncio.Event()
    release_thread = threading.Event()
    release_async = asyncio.Event()
    loop = asyncio.get_running_loop()

    def fork_at_turn(**_kwargs) -> int:
        if phase == "copy":
            loop.call_soon_threadsafe(reached.set)
            assert release_thread.wait(5)
        return 1

    async def create_chat(child: ChatSpec) -> ChatSpec:
        if phase == "registration":
            reached.set()
            await release_async.wait()
        return child

    store = SimpleNamespace(
        fork_at_turn=fork_at_turn,
        delete_session=Mock(),
    )
    manager = SimpleNamespace(
        get_chat=AsyncMock(return_value=parent),
        create_chat=AsyncMock(side_effect=create_chat),
    )
    workspace = SimpleNamespace(
        transcript_store=store,
        session=SimpleNamespace(ensure_legacy_migrated=AsyncMock()),
        config=SimpleNamespace(backend="qwenpaw"),
        task_tracker=TaskTracker(),
    )

    task = asyncio.create_task(
        fork_chat_at_turn(
            parent.id,
            ChatForkRequest(turn_id="turn-1"),
            manager,
            workspace,
        ),
    )
    await asyncio.wait_for(reached.wait(), 5)
    task.cancel()
    release_thread.set()
    release_async.set()

    with pytest.raises(asyncio.CancelledError):
        await task

    manager.create_chat.assert_awaited_once()
    created = manager.create_chat.await_args.args[0]
    assert created.meta == {"keep": "value"}
    store.delete_session.assert_not_called()


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
async def test_delete_cleanup_failure_keeps_durable_retry_owner() -> None:
    chat = _chat()
    store = Mock(spec=TranscriptCatalog)
    store.begin_deletion_operation.return_value = "delete-1"
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
    checkpoint_delete = AsyncMock(side_effect=OSError("disk error"))

    with patch(
        "qwenpaw.app.chats.api.CHECKPOINT_RUNTIME."
        "delete_session_checkpoints",
        checkpoint_delete,
    ):
        result = await delete_chat(
            chat_id=chat.id,
            mgr=manager,
            workspace=workspace,
        )

    assert result == {"deleted": True}
    manager.delete_chats.assert_awaited_once_with(chat_ids=[chat.id])
    store.mark_deletion_mapping_deleted.assert_called_once_with("delete-1")
    store.record_deletion_cleanup_failure.assert_called_once_with(
        "delete-1",
        "Failed to delete chat persistence",
    )
    store.finish_deletion_operation.assert_not_called()
    store.restore_staged_session_deletion.assert_not_called()
    store.delete_session.assert_not_called()


@pytest.mark.asyncio
async def test_native_fork_registration_failure_keeps_provider_owner() -> None:
    parent = _chat()
    store = SimpleNamespace(
        fork_at_turn=Mock(return_value=1),
        read_provider_state=Mock(
            return_value={
                "boundaries": {
                    "turn-1": {
                        "provider": "codex",
                        "provider_turn_id": "provider-turn-1",
                    },
                },
            },
        ),
        record_provider_fact=Mock(),
        delete_session=Mock(),
        pending_fork_for=Mock(return_value=None),
        begin_pending_fork=Mock(),
        mark_pending_fork_calling=Mock(),
        mark_pending_fork_bound=Mock(),
        finish_pending_fork=Mock(),
    )
    manager = SimpleNamespace(
        get_chat=AsyncMock(return_value=parent),
        create_chat=AsyncMock(side_effect=OSError("chats.json write failed")),
    )
    backend_call = AsyncMock(return_value="provider-child-1")
    workspace = SimpleNamespace(
        transcript_store=store,
        session=SimpleNamespace(ensure_legacy_migrated=AsyncMock()),
        config=SimpleNamespace(backend="codex", backend_settings={}),
        backend_runtime=SimpleNamespace(call=backend_call),
        task_tracker=TaskTracker(),
    )

    with patch(
        "qwenpaw.app.chats.api.get_fork_capability",
        new=AsyncMock(return_value={"can_fork": True, "reason": None}),
    ):
        with pytest.raises(HTTPException, match="Native fork failed"):
            await fork_chat_at_turn(
                parent.id,
                ChatForkRequest(turn_id="turn-1"),
                manager,
                workspace,
            )

    backend_call.assert_awaited_once()
    store.record_provider_fact.assert_called_once()
    assert (
        store.record_provider_fact.call_args.kwargs["data"][
            "external_session_id"
        ]
        == "provider-child-1"
    )
    store.begin_pending_fork.assert_called_once()
    store.mark_pending_fork_calling.assert_called_once()
    store.mark_pending_fork_bound.assert_called_once_with(
        store.begin_pending_fork.call_args.args[0].id,
        "provider-child-1",
    )
    store.finish_pending_fork.assert_not_called()
    store.delete_session.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_owner", [False, True])
async def test_concurrent_native_forks_keep_live_local_copy(
    tmp_path,
    cancel_owner,
):
    manager = ChatManager(repo=JsonChatRepository(tmp_path / "chats.json"))
    parent = await manager.create_chat(_chat())
    store = TranscriptCatalog(tmp_path)
    _append_turn(store, 1, "source")
    entered = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    begin = store.begin_pending_fork
    children = []

    def pause_first(child, provider):
        begin(child, provider)
        children.append(child)
        if len(children) == 1:
            loop.call_soon_threadsafe(entered.set)
            assert release.wait(5)

    call = AsyncMock(side_effect=["native-one", "native-two"])
    workspace = SimpleNamespace(
        transcript_store=store,
        chat_manager=manager,
        session=SimpleNamespace(ensure_legacy_migrated=AsyncMock()),
        config=SimpleNamespace(backend="codex", backend_settings={}),
        backend_runtime=SimpleNamespace(call=call),
        task_tracker=TaskTracker(),
    )
    tasks = []
    try:
        with patch.object(store, "begin_pending_fork", pause_first), patch(
            "qwenpaw.app.chats.api.get_fork_capability",
            AsyncMock(return_value={"can_fork": True}),
        ), patch.object(
            store,
            "read_provider_state",
            return_value={
                "boundaries": {"turn-1": {"provider": "codex"}},
            },
        ):
            tasks.append(
                asyncio.create_task(
                    fork_chat_at_turn(
                        parent.id,
                        ChatForkRequest(turn_id="turn-1"),
                        manager,
                        workspace,
                    ),
                ),
            )
            await asyncio.wait_for(entered.wait(), 5)
            if cancel_owner:
                tasks[0].cancel()
            tasks.append(
                asyncio.create_task(
                    fork_chat_at_turn(
                        parent.id,
                        ChatForkRequest(turn_id="turn-1"),
                        manager,
                        workspace,
                    ),
                ),
            )
            await asyncio.wait({tasks[1]}, timeout=0.2)
            assert workspace.task_tracker.native_fork_lock.locked()
            assert not tasks[1].done()
            live_copy = (
                tmp_path / "transcripts" / (children[0].storage_id + ".db")
            )
            assert live_copy.exists()
            release.set()
            results = await asyncio.gather(*tasks, return_exceptions=True)
            if cancel_owner:
                assert isinstance(results[0], asyncio.CancelledError)
            else:
                assert isinstance(results[0], ChatSpec)
            assert isinstance(results[1], ChatSpec)
            assert call.await_count == 2
            assert not store.pending_forks()
            for child in children:
                assert await manager.get_chat(child.id) is not None
                assert (
                    tmp_path / "transcripts" / (child.storage_id + ".db")
                ).exists()
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        store.close()


@pytest.mark.asyncio
async def test_history_recovers_unmatched_native_boundaries_once(tmp_path):
    store = TranscriptCatalog(tmp_path)
    identity = dict(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )
    store.import_legacy_messages(
        **identity,
        messages=[
            Message(
                id=f"old-{i}",
                role=role,
                content=[TextContent(text=str(i))],
            )
            for i in range(10)
            for role in ["user" if i % 2 == 0 else "assistant"]
        ],
    )
    store.record_provider_fact(
        **identity,
        kind="session_bound",
        data={
            "provider": "codex",
            "external_session_id": "native-parent",
        },
    )
    call = AsyncMock(return_value=[])
    workspace = SimpleNamespace(
        transcript_store=store,
        config=SimpleNamespace(backend="codex"),
        backend_runtime=SimpleNamespace(call=call),
    )
    descriptor = SimpleNamespace(
        status="available",
        capabilities=SimpleNamespace(fork_mode="any"),
    )
    try:
        with patch("qwenpaw.app.chats.api.PluginRegistry") as registry:
            registry.return_value.backend_registry.describe.return_value = (
                descriptor
            )
            page = store.get_page(**identity, limit=5)
            request_cache = {}
            result = await _history_fork_capabilities(
                page.messages,
                _chat(),
                SimpleNamespace(get_chat=AsyncMock(return_value=_chat())),
                workspace,
                native_capabilities=request_cache,
            )
            assert len(result) == 5
            assert not any(result.values())
            assert call.await_count == 1
            # Budget retries share this request's capability snapshot.
            assert (
                await _history_fork_capabilities(
                    page.messages,
                    _chat(),
                    None,
                    workspace,
                    native_capabilities=request_cache,
                )
                == result
            )
            assert call.await_count == 1
            for turn_id in result:
                store.record_provider_fact(
                    **identity,
                    kind="turn_boundary",
                    turn_id=turn_id,
                    data={
                        "provider": "codex",
                        "external_session_id": "native-parent",
                        "boundary_kind": "turn",
                        "boundary_id": turn_id,
                    },
                )
            descriptor.capabilities.fork_mode = "latest"
            refreshed = await _history_fork_capabilities(
                page.messages,
                _chat(),
                None,
                workspace,
            )
            assert sum(refreshed.values()) == 1
            assert refreshed[next(reversed(result))]
            assert call.await_count == 1
    finally:
        store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("already_registered", [False, True])
async def test_pending_native_fork_recovers_from_recorded_binding(
    tmp_path: Path,
    already_registered: bool,
) -> None:
    store = TranscriptCatalog(tmp_path)
    child = ChatSpec(
        id="child-chat",
        session_id="child-session",
        user_id="user",
        channel="console",
        parent_chat_id="parent-chat",
        fork_turn_id="turn-1",
    )
    store.start_turn(
        session_id=child.session_id,
        user_id=child.user_id,
        channel=child.channel,
        turn_id="child-turn",
    )
    store.finish_turn(
        session_id=child.session_id,
        turn_id="child-turn",
        status="completed",
    )
    store.begin_pending_fork(child, "codex")
    store.mark_pending_fork_calling(child.id)
    store.record_provider_fact(
        session_id=child.session_id,
        user_id=child.user_id,
        channel=child.channel,
        kind="session_bound",
        data={
            "provider": "codex",
            "external_session_id": "provider-child-1",
        },
    )
    manager = SimpleNamespace(
        get_chat=AsyncMock(return_value=child if already_registered else None),
        create_chat=AsyncMock(return_value=child),
    )
    workspace = SimpleNamespace(
        transcript_store=store,
        chat_manager=manager,
        task_tracker=TaskTracker(),
    )
    try:
        await recover_pending_forks(workspace)
        if already_registered:
            manager.create_chat.assert_not_awaited()
        else:
            manager.create_chat.assert_awaited_once_with(child)
        assert store.pending_forks() == []
    finally:
        store.close()


@pytest.mark.asyncio
async def test_delete_restores_transcript_when_mapping_commit_fails() -> None:
    chat = _chat()
    deletion = object()
    store = Mock(spec=TranscriptCatalog)
    store.begin_deletion_operation.return_value = "delete-1"
    store.stage_session_deletion.return_value = deletion
    manager = SimpleNamespace(
        get_chat=AsyncMock(return_value=chat),
        list_chats=AsyncMock(return_value=[chat]),
        delete_chats=AsyncMock(side_effect=OSError("catalog write failed")),
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

    with pytest.raises(HTTPException, match="Delete failed; please retry"):
        await delete_chat(chat.id, manager, workspace)

    store.restore_staged_session_deletion.assert_called_once_with(deletion)
    store.commit_staged_session_deletion.assert_not_called()
    store.finish_deletion_operation.assert_called_once_with("delete-1")


@pytest.mark.asyncio
async def test_delete_catalog_commit_failure_keeps_durable_owner() -> None:
    chat = _chat()
    deletion = object()
    mapping_present = True

    async def delete_mapping(*, chat_ids: list[str]) -> bool:
        nonlocal mapping_present
        assert chat_ids == [chat.id]
        mapping_present = False
        return True

    store = Mock(spec=TranscriptCatalog)
    store.begin_deletion_operation.return_value = "delete-1"
    store.stage_session_deletion.return_value = deletion
    store.commit_staged_session_deletion.return_value = False
    manager = SimpleNamespace(
        get_chat=AsyncMock(return_value=chat),
        list_chats=AsyncMock(return_value=[chat]),
        delete_chats=AsyncMock(side_effect=delete_mapping),
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

    with patch(
        "qwenpaw.app.chats.api.CHECKPOINT_RUNTIME."
        "delete_session_checkpoints",
        new=AsyncMock(),
    ):
        result = await delete_chat(chat.id, manager, workspace)

    assert result == {"deleted": True}
    assert not mapping_present
    store.mark_deletion_mapping_deleted.assert_called_once_with("delete-1")
    store.finish_deletion_operation.assert_not_called()


@pytest.mark.asyncio
async def test_delete_recovers_cleanup_after_mapping_was_committed() -> None:
    chat = _chat()
    deletion = object()
    store = Mock(spec=TranscriptCatalog)
    store.begin_deletion_operation.return_value = "delete-1"
    store.stage_session_deletion.return_value = deletion
    store.commit_staged_session_deletion.return_value = True
    manager = SimpleNamespace(
        get_chat=AsyncMock(return_value=chat),
        list_chats=AsyncMock(side_effect=[[chat], []]),
        delete_chats=AsyncMock(side_effect=OSError("shell cleanup failed")),
        cleanup_deleted_chat_targets=AsyncMock(),
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

    with patch(
        "qwenpaw.app.chats.api.CHECKPOINT_RUNTIME."
        "delete_session_checkpoints",
        new=AsyncMock(),
    ):
        result = await delete_chat(chat.id, manager, workspace)

    assert result == {"deleted": True}
    store.restore_staged_session_deletion.assert_not_called()
    store.mark_deletion_mapping_deleted.assert_called_once_with("delete-1")
    store.finish_deletion_operation.assert_called_once_with("delete-1")
    manager.cleanup_deleted_chat_targets.assert_awaited_once()


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
