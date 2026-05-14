# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Regression tests for plugin session lifecycle hooks."""
from __future__ import annotations

from pathlib import Path

import pytest

from qwenpaw.app.runner.manager import ChatManager
from qwenpaw.app.runner.repo.json_repo import JsonChatRepository
from qwenpaw.plugins.api import PluginApi
from qwenpaw.plugins.registry import PluginRegistry


@pytest.fixture(autouse=True)
def reset_plugin_registry():
    """Isolate PluginRegistry singleton state between tests."""
    PluginRegistry._instance = None
    yield
    PluginRegistry._instance = None


async def test_session_hooks_run_in_priority_order_for_sync_and_async():
    """Session hooks should support sync/async callbacks in priority order."""
    registry = PluginRegistry()
    calls = []

    def sync_callback(*, session_id, agent_id, metadata):
        calls.append(("sync", session_id, agent_id, metadata["source"]))

    async def async_callback(*, session_id, agent_id, metadata):
        calls.append(("async", session_id, agent_id, metadata["source"]))

    registry.register_session_hook(
        "sync-plugin",
        "session.create",
        sync_callback,
        priority=20,
    )
    registry.register_session_hook(
        "async-plugin",
        "session.create",
        async_callback,
        priority=10,
    )

    await registry.emit_session_event(
        "session.create",
        session_id="console:user-1",
        agent_id="agent-a",
        metadata={"source": "unit-test"},
    )

    assert calls == [
        ("async", "console:user-1", "agent-a", "unit-test"),
        ("sync", "console:user-1", "agent-a", "unit-test"),
    ]


async def test_plugin_api_registers_session_hook():
    """PluginApi should expose session hook registration to plugins."""
    registry = PluginRegistry()
    api = PluginApi("session-plugin", {})
    api.set_registry(registry)
    calls = []

    async def on_session_create(*, session_id, agent_id, metadata):
        calls.append((session_id, agent_id, metadata["chat_id"]))

    api.register_session_hook(
        hook_name="session.create",
        callback=on_session_create,
        priority=50,
    )

    hooks = registry.get_session_hooks("session.create")
    assert len(hooks) == 1
    assert hooks[0].plugin_id == "session-plugin"

    await registry.emit_session_event(
        "session.create",
        session_id="console:user-2",
        agent_id="agent-b",
        metadata={"chat_id": "chat-2"},
    )

    assert calls == [("console:user-2", "agent-b", "chat-2")]


async def test_chat_manager_emits_session_create_once_for_new_chat(
    tmp_path: Path,
):
    """Auto-registration should emit session.create only for new chats."""
    registry = PluginRegistry()
    calls = []

    def on_session_create(**payload):
        calls.append(payload)

    registry.register_session_hook(
        "audit-plugin",
        "session.create",
        on_session_create,
        priority=100,
    )
    chat_manager = ChatManager(
        repo=JsonChatRepository(tmp_path / "chats.json"),
        agent_id="agent-c",
    )

    chat = await chat_manager.get_or_create_chat(
        session_id="console:user-3",
        user_id="user-3",
        channel="console",
        name="New Chat",
    )
    existing = await chat_manager.get_or_create_chat(
        session_id="console:user-3",
        user_id="user-3",
        channel="console",
        name="New Chat",
    )

    assert existing.id == chat.id
    assert len(calls) == 1
    assert calls[0]["session_id"] == "console:user-3"
    assert calls[0]["agent_id"] == "agent-c"
    assert calls[0]["metadata"]["chat_id"] == chat.id
    assert calls[0]["metadata"]["chat_name"] == "New Chat"
