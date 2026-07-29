# -*- coding: utf-8 -*-
"""Integrated tests for crash-recoverable chat persistence deletion."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

import qwenpaw.app.chats.deletion as deletion_mod
from qwenpaw.agents.context.scroll.history import HistoryStore
from qwenpaw.agents.context.types import LogEntry
from qwenpaw.app.chats.deletion import (
    ChatDeletionCleanupError,
    ChatDeletionInProgressError,
    ChatDeletionService,
    execute_pending_deletion,
    recover_pending_chat_deletions,
)
from qwenpaw.app.chats.manager import (
    ChatDeletionPendingError,
    ChatManager,
)
from qwenpaw.app.chats.models import ChatSpec
from qwenpaw.app.chats.repo import JsonChatRepository
from qwenpaw.app.chats.session import (
    SafeJSONSession,
    session_relative_path,
)
from qwenpaw.app.task_tracker import TaskTracker


def _entry(content: str) -> LogEntry:
    return LogEntry(
        kind="model_turn",
        role="assistant",
        content=content,
    )


async def _seed_chat(
    manager: ChatManager,
    session: SafeJSONSession,
    history_path: Path,
    *,
    chat_id: str,
    session_id: str = "console:session",
    user_id: str = "user",
    channel: str = "console",
) -> ChatSpec:
    chat = ChatSpec(
        id=chat_id,
        session_id=session_id,
        user_id=user_id,
        channel=channel,
    )
    await manager.create_chat(chat)
    await session.update_session_state(
        session_id,
        "agent.value",
        chat_id,
        user_id,
        channel,
    )
    history = HistoryStore(history_path)
    history.append(
        session_id=session_id,
        dedup_key=chat_id,
        entry=_entry(chat_id),
    )
    history.close()
    return chat


def _service(
    manager: ChatManager,
    session: SafeJSONSession,
    tracker: TaskTracker,
    history_path: Path,
) -> ChatDeletionService:
    return ChatDeletionService(
        manager=manager,
        session=session,
        task_tracker=tracker,
        db_path=history_path,
    )


@pytest.mark.asyncio
async def test_delete_from_empty_registry_does_not_touch_orphan_data(
    tmp_path: Path,
):
    manager = ChatManager(repo=JsonChatRepository(tmp_path / "chats.json"))
    session = SafeJSONSession(str(tmp_path / "sessions"))
    orphan = (
        tmp_path
        / "sessions"
        / session_relative_path("orphan-session", "user", "console")
    )
    orphan.parent.mkdir(parents=True)
    orphan.write_text("{}", encoding="utf-8")

    assert not await _service(
        manager,
        session,
        TaskTracker(),
        tmp_path / "history.db",
    ).delete(["missing-chat"])

    assert orphan.exists()
    assert not (tmp_path / "chats.json").exists()
    assert not (tmp_path / "history.db").exists()


@pytest.mark.asyncio
async def test_delete_removes_unreferenced_state_history_and_tombstone(
    tmp_path: Path,
):
    manager = ChatManager(repo=JsonChatRepository(tmp_path / "chats.json"))
    session = SafeJSONSession(str(tmp_path / "sessions"))
    tracker = TaskTracker()
    history_path = tmp_path / "history.db"
    chat = await _seed_chat(
        manager,
        session,
        history_path,
        chat_id="delete-me",
    )
    legacy = (
        tmp_path
        / "sessions"
        / session_relative_path(chat.session_id, chat.user_id)
    )
    legacy.write_text("{}", encoding="utf-8")

    assert await _service(
        manager,
        session,
        tracker,
        history_path,
    ).delete([chat.id])

    assert await manager.get_chat(chat.id) is None
    assert await manager.list_pending_deletions() == []
    assert not legacy.exists()
    channel_path = (
        tmp_path
        / "sessions"
        / session_relative_path(
            chat.session_id,
            chat.user_id,
            chat.channel,
        )
    )
    assert not channel_path.exists()
    assert not (tmp_path / "sessions" / ".trash").exists()
    history = HistoryStore(history_path)
    try:
        assert history.count(chat.session_id) == 0
    finally:
        history.close()


@pytest.mark.asyncio
async def test_delete_preserves_state_and_history_referenced_by_alias(
    tmp_path: Path,
):
    manager = ChatManager(repo=JsonChatRepository(tmp_path / "chats.json"))
    session = SafeJSONSession(str(tmp_path / "sessions"))
    tracker = TaskTracker()
    history_path = tmp_path / "history.db"
    first = await _seed_chat(
        manager,
        session,
        history_path,
        chat_id="first",
    )
    second = ChatSpec(
        id="second",
        session_id=first.session_id,
        user_id=first.user_id,
        channel=first.channel,
    )
    await manager.create_chat(second)
    state_path = (
        tmp_path
        / "sessions"
        / session_relative_path(
            first.session_id,
            first.user_id,
            first.channel,
        )
    )

    assert await _service(
        manager,
        session,
        tracker,
        history_path,
    ).delete([first.id])

    assert state_path.exists()
    assert await manager.get_chat(second.id) is not None
    history = HistoryStore(history_path)
    try:
        assert history.count(first.session_id) == 1
    finally:
        history.close()


@pytest.mark.asyncio
async def test_delete_preserves_state_with_sanitized_path_collision(
    tmp_path: Path,
):
    manager = ChatManager(repo=JsonChatRepository(tmp_path / "chats.json"))
    session = SafeJSONSession(str(tmp_path / "sessions"))
    tracker = TaskTracker()
    history_path = tmp_path / "history.db"
    first = await _seed_chat(
        manager,
        session,
        history_path,
        chat_id="first",
        session_id="console:a:b",
    )
    colliding = ChatSpec(
        id="colliding",
        session_id="console:a/b",
        user_id=first.user_id,
        channel=first.channel,
    )
    await manager.create_chat(colliding)
    state_path = (
        tmp_path
        / "sessions"
        / session_relative_path(
            first.session_id,
            first.user_id,
            first.channel,
        )
    )
    assert state_path == (
        tmp_path
        / "sessions"
        / session_relative_path(
            colliding.session_id,
            colliding.user_id,
            colliding.channel,
        )
    )

    assert await _service(
        manager,
        session,
        tracker,
        history_path,
    ).delete([first.id])

    assert state_path.exists()
    assert await manager.get_chat(colliding.id) is not None


@pytest.mark.asyncio
async def test_running_chat_blocks_delete_without_mutation(tmp_path: Path):
    manager = ChatManager(repo=JsonChatRepository(tmp_path / "chats.json"))
    session = SafeJSONSession(str(tmp_path / "sessions"))
    tracker = TaskTracker()
    history_path = tmp_path / "history.db"
    chat = await _seed_chat(
        manager,
        session,
        history_path,
        chat_id="running",
    )
    started = asyncio.Event()
    finish = asyncio.Event()

    async def stream(_payload):
        started.set()
        await finish.wait()
        yield ""

    await tracker.attach_or_start(chat.id, None, stream)
    await started.wait()

    with pytest.raises(ChatDeletionInProgressError):
        await _service(
            manager,
            session,
            tracker,
            history_path,
        ).delete([chat.id])

    assert await manager.get_chat(chat.id) is not None
    assert await manager.list_pending_deletions() == []
    await tracker.request_stop(chat.id)


@pytest.mark.asyncio
async def test_failed_cleanup_leaves_retryable_tombstone(
    monkeypatch,
    tmp_path: Path,
):
    manager = ChatManager(repo=JsonChatRepository(tmp_path / "chats.json"))
    session = SafeJSONSession(str(tmp_path / "sessions"))
    tracker = TaskTracker()
    history_path = tmp_path / "history.db"
    chat = await _seed_chat(
        manager,
        session,
        history_path,
        chat_id="retry-me",
    )
    original_delete = deletion_mod.delete_history_sessions

    def fail_delete(_path, _watermarks):
        raise OSError("simulated cleanup outage")

    monkeypatch.setattr(
        deletion_mod,
        "delete_history_sessions",
        fail_delete,
    )
    with pytest.raises(ChatDeletionCleanupError) as exc_info:
        await _service(
            manager,
            session,
            tracker,
            history_path,
        ).delete([chat.id])
    assert isinstance(exc_info.value.__cause__, OSError)

    assert await manager.get_chat(chat.id) is None
    pending = await manager.list_pending_deletions()
    assert len(pending) == 1
    live_path = (
        tmp_path
        / "sessions"
        / session_relative_path(
            chat.session_id,
            chat.user_id,
            chat.channel,
        )
    )
    assert not live_path.exists()
    with pytest.raises(ChatDeletionPendingError):
        await manager.create_chat(
            ChatSpec(
                id="replacement",
                session_id=chat.session_id,
                user_id=chat.user_id,
                channel=chat.channel,
            ),
        )

    monkeypatch.setattr(
        deletion_mod,
        "delete_history_sessions",
        original_delete,
    )
    await execute_pending_deletion(
        manager,
        session,
        history_path,
        pending[0],
    )
    assert await manager.list_pending_deletions() == []
    history = HistoryStore(history_path)
    try:
        assert history.count(chat.session_id) == 0
    finally:
        history.close()


@pytest.mark.asyncio
async def test_startup_recovery_finishes_pending_deletion(
    monkeypatch,
    tmp_path: Path,
):
    workspace = tmp_path / "workspace"
    manager = ChatManager(
        repo=JsonChatRepository(workspace / "chats.json"),
    )
    session = SafeJSONSession(str(workspace / "sessions"))
    history_path = workspace / "history.db"
    chat = await _seed_chat(
        manager,
        session,
        history_path,
        chat_id="recover-me",
    )
    original_delete = deletion_mod.delete_history_sessions

    def fail_delete(_path, _watermarks):
        raise OSError("simulated cleanup outage")

    monkeypatch.setattr(
        deletion_mod,
        "delete_history_sessions",
        fail_delete,
    )
    with pytest.raises(ChatDeletionCleanupError):
        await _service(
            manager,
            session,
            TaskTracker(),
            history_path,
        ).delete([chat.id])

    config = SimpleNamespace(
        agents=SimpleNamespace(
            profiles={
                "agent": SimpleNamespace(workspace_dir=str(workspace)),
            },
        ),
    )
    agent_config = SimpleNamespace(
        running=SimpleNamespace(
            light_context_config=SimpleNamespace(
                scroll_config=SimpleNamespace(db_filename="history.db"),
            ),
        ),
    )
    import qwenpaw.config as config_module
    import qwenpaw.config.config as agent_config_module

    monkeypatch.setattr(config_module, "load_config", lambda: config)
    monkeypatch.setattr(
        agent_config_module,
        "load_agent_config",
        lambda _agent_id: agent_config,
    )
    monkeypatch.setattr(
        deletion_mod,
        "delete_history_sessions",
        original_delete,
    )

    assert await recover_pending_chat_deletions() == set()
    assert await manager.list_pending_deletions() == []
    history = HistoryStore(history_path)
    try:
        assert history.count(chat.session_id) == 0
    finally:
        history.close()
