# -*- coding: utf-8 -*-
"""Console selection persistence is separate from request model resolution."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
import asyncio

import pytest

from qwenpaw.app.routers.console import _persist_console_model_selection
from qwenpaw.schemas import AgentRequest


@pytest.mark.asyncio
async def test_console_persistence_reset_and_temporary_override(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.app.chats.manager import ChatManager
    from qwenpaw.app.chats.repo import JsonChatRepository
    from qwenpaw.config.config import ModelSlotConfig
    from qwenpaw.services.model_selection import (
        prepare_model_context,
        clear_current_model_context,
    )

    manager = ChatManager(repo=JsonChatRepository(tmp_path / "chats.json"))
    default = ModelSlotConfig(provider_id="provider", model="default")
    workspace = SimpleNamespace(
        config=SimpleNamespace(active_model=default),
        chat_manager=manager,
    )
    monkeypatch.setattr(
        "qwenpaw.providers.provider_manager.ProviderManager.get_instance",
        lambda: SimpleNamespace(
            get_active_model=lambda: None,
            get_provider=lambda _id: SimpleNamespace(
                get_model_info=lambda _model: object(),
            ),
        ),
    )
    chat = await manager.get_or_create_chat("session", "user", "console")
    selected = {"provider_id": "provider", "model": "selected"}

    async def resolve(override=None):
        return await prepare_model_context(
            workspace=workspace,
            session_id="session",
            user_id="user",
            channel="console",
            request_override=override,
        )

    try:
        await _persist_console_model_selection(
            workspace,
            chat,
            {"model_slot_override": selected},
        )
        assert (await resolve(selected)).slot.model == "selected"
        assert (await resolve()).slot == default
        await _persist_console_model_selection(
            workspace,
            chat,
            {
                "model_slot_override": selected,
                "persist_model_slot_override": True,
            },
        )
        assert (await resolve()).slot.model == "selected"
        assert (await resolve("provider:temporary")).slot.model == "temporary"
        assert (await resolve()).slot.model == "selected"
        await _persist_console_model_selection(workspace, chat, {})
        assert (await resolve()).slot.model == "selected"
        await _persist_console_model_selection(
            workspace,
            chat,
            {"model_slot_override": None, "persist_model_slot_override": True},
        )
        assert (await resolve()).slot == default
        assert workspace.config.active_model == default
    finally:
        clear_current_model_context()


@pytest.mark.asyncio
@pytest.mark.parametrize("typed", [False, True])
@pytest.mark.parametrize(
    "body,expected",
    [
        ({}, "unchanged"),
        ({"model_slot_override": "invalid"}, "unchanged"),
        ({"model_slot_override": None}, "unchanged"),
        ({"model_slot_override": "provider:model"}, "unchanged"),
        (
            {
                "model_slot_override": "provider:model",
                "persist_model_slot_override": False,
            },
            "unchanged",
        ),
        (
            {
                "model_slot_override": "provider:model",
                "persist_model_slot_override": "true",
            },
            "unchanged",
        ),
        ({"persist_model_slot_override": True}, "unchanged"),
        (
            {"model_slot_override": None, "persist_model_slot_override": True},
            None,
        ),
        (
            {
                "persist_model_slot_override": True,
                "model_slot_override": {
                    "provider_id": "provider",
                    "model": "model",
                },
            },
            {"provider_id": "provider", "model": "model"},
        ),
    ],
)
async def test_explicit_console_selection(body, expected, typed):
    chat = SimpleNamespace(id="chat-1")
    setter = AsyncMock(return_value=chat)
    workspace = SimpleNamespace(
        chat_manager=SimpleNamespace(set_model_slot_override=setter),
    )
    request = AgentRequest(**body) if typed else body
    assert (
        await _persist_console_model_selection(workspace, chat, request)
        is chat
    )
    if expected == "unchanged":
        setter.assert_not_awaited()
    else:
        setter.assert_awaited_once_with("chat-1", expected)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "selection",
    [None, {"provider_id": "provider", "model": "selected"}],
)
async def test_only_accepted_run_persists_model(
    tmp_path,
    monkeypatch,
    selection,
):
    from fastapi import HTTPException
    from qwenpaw.app.chats.manager import ChatManager
    from qwenpaw.app.chats.repo import JsonChatRepository
    from qwenpaw.app.routers import console
    from qwenpaw.app.task_tracker import TaskTracker
    from qwenpaw.services.request_chat import get_request_chat

    manager = ChatManager(repo=JsonChatRepository(tmp_path / "chats.json"))
    chat = await manager.get_or_create_chat("session", "user", "console")
    await manager.set_model_slot_override(
        chat.id,
        {"provider_id": "provider", "model": "old"},
    )
    entered = asyncio.Event()
    release = asyncio.Event()
    observed = []

    async def stream(_payload):
        snapshot = get_request_chat(manager, "session", "user", "console")
        observed.append(
            snapshot.meta.get("runtime_context", {}).get(
                "model_slot_override",
            ),
        )
        entered.set()
        await release.wait()
        yield "data: done\n\n"

    channel = SimpleNamespace(
        resolve_session_id=lambda **_kw: "session",
        stream_one=stream,
    )
    workspace = SimpleNamespace(
        chat_manager=manager,
        task_tracker=TaskTracker(),
        channel_manager=SimpleNamespace(
            get_channel=AsyncMock(return_value=channel),
        ),
    )
    monkeypatch.setattr(
        console,
        "get_agent_for_request",
        AsyncMock(return_value=workspace),
    )
    monkeypatch.setattr(
        console,
        "_extract_placeholder_name",
        lambda _parts: ("name", ""),
    )
    body = {
        "session_id": "session",
        "user_id": "user",
        "channel": "console",
        "model_slot_override": selection,
        "persist_model_slot_override": True,
    }
    response = await console.post_console_chat(body, None)
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        assert observed == [selection]
        rejected = {
            **body,
            "model_slot_override": {
                "provider_id": "provider",
                "model": "rejected",
            },
        }
        with pytest.raises(HTTPException) as exc:
            await console.post_console_chat(rejected, None)
        assert exc.value.status_code == 409
        persisted = await manager.get_chat(chat.id)
        assert (
            persisted.meta.get("runtime_context", {}).get(
                "model_slot_override",
            )
            == selection
        )
    finally:
        release.set()

        async def drain():
            async for _event in response.body_iterator:
                pass

        await asyncio.wait_for(drain(), timeout=5)
