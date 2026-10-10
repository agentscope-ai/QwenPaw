# -*- coding: utf-8 -*-
"""Ownership-boundary tests for the global chat API."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from qwenpaw.app.chats import api as chats_api
from qwenpaw.app.chats.api import get_chat, get_chat_status, list_chats
from qwenpaw.app.chats.models import ChatSpec


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
async def test_delete_chat_stops_a_live_run():
    """Deleting a running chat must not leave its run in the tracker.

    A live run whose chat is deleted would otherwise stay in ``_runs``
    for good, so ``get_global_status()['running_task_count']`` stays
    inflated while the chat list can no longer show that chat (#7991).
    """
    from qwenpaw.app.task_tracker import TaskTracker

    tracker = TaskTracker()
    release = asyncio.Event()

    async def stream(_payload):
        await release.wait()
        yield "data: done\n\n"

    await tracker.attach_or_start("chat-live", None, stream)
    assert (await tracker.get_global_status())["running_task_count"] == 1

    manager = SimpleNamespace(
        get_chat=AsyncMock(return_value=_chat("chat-live")),
        delete_chats=AsyncMock(return_value=True),
    )
    workspace = SimpleNamespace(task_tracker=tracker)

    with patch.object(
        chats_api.CHECKPOINT_RUNTIME,
        "delete_session_checkpoints",
        new=AsyncMock(),
    ):
        result = await chats_api.delete_chat(
            chat_id="chat-live",
            mgr=manager,
            workspace=workspace,
        )

    assert result == {"deleted": True}
    assert await tracker.list_active_tasks() == []
    assert (await tracker.get_global_status())["running_task_count"] == 0
