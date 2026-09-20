# -*- coding: utf-8 -*-
"""Session reasoning persists independently from agent and workspace state."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from qwenpaw.app.chats.api import set_chat_thinking
from qwenpaw.app.routers.console import _persist_pending_project_dirs

from qwenpaw.app.chats.manager import ChatManager
from qwenpaw.app.chats.models import ChatSpec
from qwenpaw.app.chats.repo import JsonChatRepository
from qwenpaw.config.config import AgentProfileConfig
from qwenpaw.providers.thinking import ThinkingControl, ThinkingPreference
from qwenpaw.services.session_thinking import (
    apply_session_thinking,
    session_preference,
    thinking_view,
)


@pytest.mark.asyncio
async def test_session_isolation_reload_and_reset(tmp_path):
    path = tmp_path / f"chats.json"
    manager = ChatManager(repo=JsonChatRepository(path))
    first = await manager.create_chat(
        ChatSpec(
            session_id=f"one",
            user_id=f"u",
            channel=f"console",
        ),
    )
    second = await manager.create_chat(
        ChatSpec(
            session_id=f"two",
            user_id=f"u",
            channel=f"console",
        ),
    )
    preference = ThinkingPreference(level=f"budget", budget_tokens=2345)
    await asyncio.gather(
        manager.set_session_thinking(first.id, preference),
        manager.set_session_project_dirs(
            first.id,
            [
                {f"path": str(tmp_path), f"label": f"Project"},
            ],
        ),
    )
    loaded = await manager.get_chat(first.id)
    assert session_preference(loaded.meta) == preference
    assert loaded.meta[f"runtime_context"][f"project_dirs"]
    manager = ChatManager(repo=JsonChatRepository(path))
    config = AgentProfileConfig(id=f"agent", name=f"Agent")
    ctx = SimpleNamespace(
        workspace=SimpleNamespace(chat_manager=manager),
        session_id=f"one",
        request=SimpleNamespace(channel=f"console", user_id=f"u"),
    )
    snapshot = await apply_session_thinking(ctx, config)
    assert snapshot.thinking_budget == 2345
    assert config.thinking_level == f"inherit"
    ctx.session_id = f"two"
    assert await apply_session_thinking(ctx, config) is config
    assert session_preference((await manager.get_chat(second.id)).meta) is None
    await manager.set_session_thinking(first.id, ThinkingPreference())
    loaded = await manager.get_chat(first.id)
    assert session_preference(loaded.meta) is None
    assert loaded.meta[f"runtime_context"][f"project_dirs"]


@pytest.mark.asyncio
async def test_inherit_uses_agent_preference():
    config = AgentProfileConfig(
        id=f"agent",
        name=f"Agent",
        thinking_level=f"high",
    )
    with (
        patch(
            f"qwenpaw.services.session_thinking.load_agent_config",
            return_value=config,
        ),
        patch(
            f"qwenpaw.services.session_thinking.ProviderManager.get_instance",
        ) as factory,
    ):
        manager = factory.return_value
        manager.get_active_model.return_value = SimpleNamespace(
            provider_id=f"p",
            model=f"m",
        )
        manager.get_provider.return_value.thinking_control.return_value = (
            ThinkingControl(kind=f"effort", efforts=[f"low", f"high"])
        )
        view = await thinking_view(
            SimpleNamespace(agent_id=f"agent"),
            ThinkingPreference(),
        )
    assert view[f"effective"][f"level"] == f"high"
    assert view[f"source"] == f"agent"


@pytest.mark.asyncio
async def test_first_message_persists_thinking_without_project_dirs(tmp_path):
    manager = ChatManager(repo=JsonChatRepository(tmp_path / f"chats.json"))
    chat = await manager.create_chat(ChatSpec(session_id=f"new", user_id=f"u"))
    workspace = SimpleNamespace(chat_manager=manager)
    body = {
        f"meta": {
            f"request_context": {
                f"session_thinking": {f"level": f"high"},
            },
        },
    }
    with patch(
        f"qwenpaw.app.routers.console.thinking_view",
        return_value={f"reason": None},
    ):
        updated = await _persist_pending_project_dirs(workspace, chat, body)
    assert session_preference(updated.meta).level == f"high"
    assert f"session_thinking" not in body[f"meta"][f"request_context"]


@pytest.mark.asyncio
async def test_invalid_setting_is_not_persisted():
    manager = SimpleNamespace(set_session_thinking=AsyncMock())
    with patch(
        f"qwenpaw.app.chats.api.thinking_view",
        return_value={f"reason": f"cannot_disable"},
    ):
        with pytest.raises(HTTPException) as raised:
            await set_chat_thinking(
                f"id",
                ThinkingPreference(level=f"off"),
                manager,
                None,
            )
    assert raised.value.status_code == 422
    manager.set_session_thinking.assert_not_awaited()
