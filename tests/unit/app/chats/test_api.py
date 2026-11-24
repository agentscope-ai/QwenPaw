# -*- coding: utf-8 -*-
"""Ownership-boundary tests for the global chat API."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from qwenpaw.app.agent_context import scoped_session_id
from qwenpaw.app.chats import api as chats_api
from qwenpaw.app.chats.api import get_chat, get_chat_status, list_chats
from qwenpaw.app.chats.manager import ChatManager
from qwenpaw.app.chats.models import ChatSpec
from qwenpaw.app.chats.repo.json_repo import JsonChatRepository
from qwenpaw.app.workspace.workspace import Workspace
from qwenpaw.config.config import AgentProfileConfig
from qwenpaw.modes.default.mode import DefaultMode
from qwenpaw.modes.goal.goal_mode import GoalMode
from qwenpaw.runtime.runtime import Runtime


def _chat(chat_id: str, *, app_id: str | None = None) -> ChatSpec:
    meta = (
        {
            "pawapp": {
                "app_id": app_id,
                "agent_id": "datapaw",
            },
        }
        if app_id
        else {}
    )
    return ChatSpec(
        id=chat_id,
        session_id=f"console:{chat_id}",
        user_id="default",
        channel="console",
        meta=meta,
    )


@pytest.mark.asyncio
async def test_list_chats_can_exclude_app_owned_dialogues():
    normal = _chat("normal")
    app_owned = _chat("app-owned", app_id="datapaw")
    manager = SimpleNamespace(
        list_chats=AsyncMock(return_value=[normal, app_owned]),
    )
    tracker = SimpleNamespace(get_status=AsyncMock(return_value="idle"))

    result = await list_chats(
        user_id=None,
        channel=None,
        archived=False,
        include_app_owned=False,
        mgr=manager,
        workspace=SimpleNamespace(task_tracker=tracker),
    )

    assert [chat.id for chat in result] == ["normal"]
    tracker.get_status.assert_awaited_once_with("normal")


@pytest.mark.asyncio
async def test_get_chat_hides_app_owned_dialogue_when_caller_opts_out():
    manager = SimpleNamespace(
        get_chat=AsyncMock(return_value=_chat("app-owned", app_id="datapaw")),
    )

    with pytest.raises(HTTPException) as raised:
        await get_chat(
            chat_id="app-owned",
            include_app_owned=False,
            mgr=manager,
            session=SimpleNamespace(),
            workspace=SimpleNamespace(),
        )

    assert raised.value.status_code == 404


@pytest.mark.asyncio
async def test_get_chat_status_uses_tracker_without_loading_chat_persistence():
    tracker = SimpleNamespace(get_status=AsyncMock(return_value="running"))
    workspace = SimpleNamespace(task_tracker=tracker)

    result = await get_chat_status(
        chat_id="chat-1",
        workspace=workspace,
    )

    assert result.status == "running"
    tracker.get_status.assert_awaited_once_with("chat-1")


@pytest.mark.asyncio
async def test_get_chat_status_treats_unknown_run_key_as_idle():
    tracker = SimpleNamespace(get_status=AsyncMock(return_value="idle"))

    result = await get_chat_status(
        chat_id="missing",
        workspace=SimpleNamespace(task_tracker=tracker),
    )

    assert result.status == "idle"
    tracker.get_status.assert_awaited_once_with("missing")


@pytest.mark.asyncio
async def test_delete_chat_stops_a_live_run(tmp_path):
    """Stop runs and release modes when the final chat mapping is deleted."""
    workspace = Workspace("default", str(tmp_path))
    tracker = workspace.task_tracker
    manager = ChatManager(repo=JsonChatRepository(tmp_path / "chats.json"))
    live = await manager.create_chat(_chat("chat-live"))
    alias = await manager.create_chat(
        _chat("chat-alias").model_copy(
            update={"session_id": live.session_id, "user_id": "peer"},
        ),
    )
    peer = await manager.create_chat(_chat("chat-peer"))
    modes = [DefaultMode(), GoalMode()]
    workspace.plugins.modes.extend(modes)
    runtime = Runtime(workspace=workspace, app_services=None)
    profile = AgentProfileConfig(id="default", name="Test")
    for session_id in (live.session_id, peer.session_id):
        with scoped_session_id(session_id):
            await runtime._start_modes(
                SimpleNamespace(session_id=session_id, agent_config=profile),
            )

    started = asyncio.Event()
    stopped = asyncio.Event()
    release = asyncio.Event()

    async def stream(_payload):
        started.set()
        try:
            await release.wait()
        finally:
            stopped.set()
        yield "data: done\n\n"

    await tracker.attach_or_start(live.id, None, stream)
    await asyncio.wait_for(started.wait(), timeout=1)
    assert (await tracker.get_global_status())["running_task_count"] == 1

    with patch.object(
        chats_api.CHECKPOINT_RUNTIME,
        "delete_session_checkpoints",
        new=AsyncMock(),
    ):
        result = await chats_api.delete_chat(
            chat_id=live.id,
            mgr=manager,
            workspace=workspace,
        )
        assert result == {"deleted": True}
        assert stopped.is_set()
        for mode in modes:
            assert live.session_id in mode._handlers

        result = await chats_api.batch_delete_chats(
            [alias.id],
            mgr=manager,
            workspace=workspace,
        )

    assert result == {"deleted": True}
    for mode in modes:
        assert set(mode._handlers) == {peer.session_id}
        assert set(mode._config_keys) == {peer.session_id}
    assert await tracker.list_active_tasks() == []
    assert (await tracker.get_global_status())["running_task_count"] == 0
