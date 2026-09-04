# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.app.chats.manager import ChatManager
from qwenpaw.app.chats.repo import JsonChatRepository
from qwenpaw.app.chats.session import SafeJSONSession
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
        session=SafeJSONSession(str(root / "sessions")),
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
