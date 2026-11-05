# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.agents.context.scroll.history import HistoryStore
from qwenpaw.config.config import AgentProfileConfig
from qwenpaw.app.chats.manager import ChatManager
from qwenpaw.app.chats.repo import JsonChatRepository
from qwenpaw.app.chats.session import DatabaseSession
from qwenpaw.app.chats.transcript_catalog import TranscriptCatalog
from qwenpaw.harnesses.events import HarnessHistoryItem, HarnessHistoryKind
from qwenpaw.harnesses.session import HarnessSessionBridge
from qwenpaw.portability.import_conversations import (
    ConversationState,
    import_conversations,
)
from qwenpaw.portability.import_support import _session_key
from qwenpaw.portability.models import ProviderInventory, SourceSession


def _workspace(tmp_path: Path) -> SimpleNamespace:
    root = tmp_path / "workspace"
    root.mkdir()
    return SimpleNamespace(
        workspace_dir=root,
        agent_id="test",
        config=AgentProfileConfig(id="test", name="Test"),
        session=DatabaseSession(
            catalog=TranscriptCatalog(root),
            legacy_save_dir=str(root / "sessions"),
        ),
        chat_manager=ChatManager(repo=JsonChatRepository(root / "chats.json")),
    )


def _session(source_id: str) -> SourceSession:
    return SourceSession(
        source_id=source_id,
        title=source_id,
        history=[
            HarnessHistoryItem(
                kind=HarnessHistoryKind.USER,
                text=f"{source_id} history",
            ),
        ],
    )


def _inventory(sessions: list[SourceSession]) -> ProviderInventory:
    return ProviderInventory(
        provider_id="codex",
        provider_name="Codex",
        detected=True,
        sessions=sessions,
    )


async def _import(
    workspace: SimpleNamespace,
    inventory: ProviderInventory,
    sessions: list[SourceSession],
    existing_by_source: dict[tuple[str, str], object] | None = None,
) -> ConversationState:
    state = ConversationState()
    await import_conversations(
        workspace,
        inventory,
        sessions,
        existing_by_source or {},
        datetime.now(timezone.utc),
        None,
        state,
    )
    return state


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["codex", "qoder"])
async def test_import_preserves_archive_state_without_overwriting_existing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source: str,
    request,
) -> None:
    workspace = _workspace(tmp_path)
    workspace.workspace_dir = tmp_path / "workspace"
    workspace.agent_id = "test"
    workspace.config = AgentProfileConfig(id="test", name="Test")
    sessions = [
        _session("active"),
        _session("archived").model_copy(update={"archived": True}),
        SourceSession(source_id="empty", archived=True),
    ]
    inventory = _inventory(sessions).model_copy(update={"provider_id": source})
    created_states = []
    original_create = workspace.chat_manager.create_chat

    async def create_chat(spec):
        created_states.append(spec.archived)
        return await original_create(spec)

    monkeypatch.setattr(workspace.chat_manager, "create_chat", create_chat)
    state = await _import(workspace, inventory, sessions)
    assert state.imported == ["active", "archived"]
    assert state.skipped == ["empty"]
    assert created_states == [False, True]
    chats = await workspace.chat_manager.list_chats(archived=None)
    assert {chat.name: chat.model_dump()["archived"] for chat in chats} == {
        "active": False,
        "archived": True,
    }
    assert len(await workspace.chat_manager.list_chats(archived=True)) == 1
    assert len(await workspace.chat_manager.list_chats(archived=False)) == 1

    # Local user choices take precedence over a repeated import.
    for chat in chats:
        if chat.archived:
            await workspace.chat_manager.unarchive_chat(chat.id)
        else:
            await workspace.chat_manager.archive_chat(chat.id)
    existing = await workspace.chat_manager.list_chats(archived=None)
    await _import(
        workspace,
        inventory,
        sessions,
        {(source, chat.name): chat for chat in existing},
    )
    assert await workspace.chat_manager.list_chats(archived=None) == existing
    assert created_states == [False, True]
    for chat in chats:
        path = (
            workspace.workspace_dir / "transcripts" / (chat.storage_id + ".db")
        )
        history = HistoryStore(path)
        try:
            assert history.count(chat.session_id) == 1
        finally:
            history.close()


@pytest.mark.asyncio
async def test_cancelled_hydration_stops_before_later_sessions_and_retries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    sessions = [_session("first"), _session("second")]
    inventory = _inventory(sessions)
    original_hydrate = HarnessSessionBridge.hydrate
    hydrated = asyncio.Event()
    hold = True
    calls: list[str] = []
    first_session_id = _session_key("codex", "first")

    async def hydrate(self, **kwargs) -> None:
        nonlocal hold
        calls.append(kwargs["session_id"])
        await original_hydrate(self, **kwargs)  # pylint: disable=missing-kwoa
        if hold and kwargs["session_id"] == first_session_id:
            hydrated.set()
            await asyncio.Event().wait()

    monkeypatch.setattr(HarnessSessionBridge, "hydrate", hydrate)
    task = asyncio.create_task(_import(workspace, inventory, sessions))
    await hydrated.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert calls == [first_session_id]
    assert await workspace.chat_manager.list_chats(archived=None) == []
    state = await workspace.session.get_session_state_dict(
        first_session_id,
        first_session_id,
        "console",
    )
    context = state["agent"]["state"]["context"]
    assert context[0]["content"][0]["text"] == "first history"

    hold = False
    retry = await _import(workspace, inventory, sessions)

    assert retry.imported == ["first", "second"]
    assert len(await workspace.chat_manager.list_chats(archived=None)) == 2


@pytest.mark.asyncio
async def test_cancel_after_chat_commit_preserves_history_for_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    session = _session("committed")
    inventory = _inventory([session])
    original_create = workspace.chat_manager.create_chat
    committed = asyncio.Event()

    async def create_chat(spec) -> None:
        await original_create(spec)
        committed.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(workspace.chat_manager, "create_chat", create_chat)
    task = asyncio.create_task(_import(workspace, inventory, [session]))
    await committed.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    chats = await workspace.chat_manager.list_chats(archived=None)
    assert len(chats) == 1
    state = await workspace.session.get_session_state_dict(
        chats[0].session_id,
        chats[0].user_id,
        chats[0].channel,
    )
    context = state["agent"]["state"]["context"]
    assert context[0]["content"][0]["text"] == "committed history"

    monkeypatch.setattr(workspace.chat_manager, "create_chat", original_create)
    retry = await _import(
        workspace,
        inventory,
        [session],
        {("codex", "committed"): chats[0]},
    )

    assert retry.skipped == ["committed"]
    assert len(await workspace.chat_manager.list_chats(archived=None)) == 1


@pytest.mark.asyncio
async def test_imported_turns_fork_with_matching_context(tmp_path):
    workspace = _workspace(tmp_path)
    history = []
    for index in range(1, 6):
        history.extend(
            [
                HarnessHistoryItem(
                    kind=HarnessHistoryKind.USER,
                    text=f"question {index}",
                ),
                HarnessHistoryItem(
                    kind=HarnessHistoryKind.MESSAGE,
                    text=f"answer {index}",
                    item_id=f"answer-{index}",
                ),
            ],
        )
    source = SourceSession(source_id="five", history=history)
    result = await _import(workspace, _inventory([source]), [source])
    assert result.imported == ["five"]
    session_id = _session_key("codex", "five")
    catalog = workspace.session._catalog
    identity = dict(
        session_id=session_id,
        user_id=session_id,
        channel="console",
    )
    full = await workspace.session.get_session_state_dict(**identity)
    for index in range(1, 6):
        child = f"child-{index}"
        catalog.fork_at_turn(
            source_session_id=session_id,
            source_user_id=session_id,
            source_channel="console",
            source_chat_id="source",
            turn_id=f"legacy:{index}",
            target_session_id=child,
            target_user_id=child,
            target_channel="console",
            target_storage_id=child,
        )
        state = await workspace.session.get_session_state_dict(
            child,
            child,
            "console",
        )
        assert state["agent"]["state"]["context"] == (
            full["agent"]["state"]["context"][: index * 2]
        )
    assert not list((tmp_path / "workspace" / "sessions").rglob("*.json"))
    catalog.close()
