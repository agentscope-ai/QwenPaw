# -*- coding: utf-8 -*-
"""Unit tests for session and message lifecycle hooks."""
# pylint: disable=redefined-outer-name,unused-argument,protected-access
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Dict, List

import pytest

from qwenpaw.app.runner.manager import ChatManager
from qwenpaw.app.runner.models import ChatSpec
from qwenpaw.app.runner.repo.json_repo import JsonChatRepository
from qwenpaw.plugins.api import PluginApi
from qwenpaw.plugins.registry import PluginRegistry

_PID = "test-plugin"


@pytest.fixture(autouse=True)
def _reset_registry():
    """Reset the PluginRegistry singleton between tests."""
    PluginRegistry._instance = None
    yield
    PluginRegistry._instance = None


@pytest.fixture
def registry() -> PluginRegistry:
    """Return a fresh PluginRegistry."""
    return PluginRegistry()


@pytest.fixture
def api(registry: PluginRegistry) -> PluginApi:
    """Return a PluginApi wired to the fresh registry."""
    _api = PluginApi(plugin_id=_PID, config={})
    _api.set_registry(registry)
    return _api


@pytest.fixture
def chat_manager(tmp_path: Path) -> ChatManager:
    """Create a ChatManager backed by a temp file."""
    return ChatManager(
        repo=JsonChatRepository(tmp_path / "chats.json"),
        agent_id="default",
    )


# ---- Session hook registration ----


class TestSessionHookRegistration:
    def test_register_session_create_hook(
        self,
        api: PluginApi,
        registry: PluginRegistry,
    ):
        calls: List[Dict] = []

        def on_create(**kwargs):
            calls.append(kwargs)

        api.register_session_hook("session.create", "hook1", on_create)
        hooks = registry.get_session_hooks("session.create")
        assert len(hooks) == 1
        assert hooks[0].hook_name == "hook1"
        assert hooks[0].callback is on_create

    def test_register_session_reset_hook(
        self,
        api: PluginApi,
        registry: PluginRegistry,
    ):
        def on_reset(**kwargs):
            pass

        api.register_session_hook("session.reset", "hook_reset", on_reset)
        hooks = registry.get_session_hooks("session.reset")
        assert len(hooks) == 1

    def test_register_session_end_hook(
        self,
        api: PluginApi,
        registry: PluginRegistry,
    ):
        def on_end(**kwargs):
            pass

        api.register_session_hook("session.end", "hook_end", on_end)
        hooks = registry.get_session_hooks("session.end")
        assert len(hooks) == 1

    def test_invalid_session_event_raises(self, api: PluginApi):
        with pytest.raises(ValueError, match="Invalid session event"):
            api.register_session_hook("session.invalid", "h", lambda **k: None)

    def test_session_hooks_sorted_by_priority(self, registry: PluginRegistry):
        order: List[str] = []

        registry.register_session_hook(
            "session.create",
            _PID,
            "p2",
            lambda **k: order.append("p2"),
            priority=200,
        )
        registry.register_session_hook(
            "session.create",
            _PID,
            "p0",
            lambda **k: order.append("p0"),
            priority=0,
        )
        registry.register_session_hook(
            "session.create",
            _PID,
            "p1",
            lambda **k: order.append("p1"),
            priority=100,
        )

        hooks = registry.get_session_hooks("session.create")
        assert [h.hook_name for h in hooks] == ["p0", "p1", "p2"]


# ---- Message hook registration ----


class TestMessageHookRegistration:
    def test_register_message_before_hook(
        self,
        api: PluginApi,
        registry: PluginRegistry,
    ):
        def on_before(**kwargs):
            pass

        api.register_message_hook("message.before", "hook_before", on_before)
        hooks = registry.get_message_hooks("message.before")
        assert len(hooks) == 1

    def test_register_message_after_hook(
        self,
        api: PluginApi,
        registry: PluginRegistry,
    ):
        def on_after(**kwargs):
            pass

        api.register_message_hook("message.after", "hook_after", on_after)
        hooks = registry.get_message_hooks("message.after")
        assert len(hooks) == 1

    def test_invalid_message_event_raises(self, api: PluginApi):
        with pytest.raises(ValueError, match="Invalid message event"):
            api.register_message_hook("message.invalid", "h", lambda **k: None)


# ---- fire_hooks execution ----


class TestFireHooks:
    @pytest.mark.asyncio
    async def test_fire_sync_session_hook(self, registry: PluginRegistry):
        calls: List[Dict] = []

        def on_create(**kwargs):
            calls.append(kwargs)

        registry.register_session_hook(
            "session.create",
            "p1",
            _PID,
            on_create,
        )
        await registry.fire_hooks(
            "session",
            "session.create",
            session_id="s1",
            chat_id="c1",
            user_id="u1",
            channel="console",
            agent_id="default",
        )
        assert len(calls) == 1
        assert calls[0]["session_id"] == "s1"
        assert calls[0]["chat_id"] == "c1"

    @pytest.mark.asyncio
    async def test_fire_async_session_hook(self, registry: PluginRegistry):
        calls: List[Dict] = []

        async def on_create(**kwargs):
            calls.append(kwargs)

        registry.register_session_hook(
            "session.create",
            "p1",
            _PID,
            on_create,
        )
        await registry.fire_hooks(
            "session",
            "session.create",
            session_id="s1",
            chat_id="c1",
            user_id="u1",
            channel="console",
            agent_id="default",
        )
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_fire_message_hook(self, registry: PluginRegistry):
        calls: List[Dict] = []

        async def on_before(**kwargs):
            calls.append(kwargs)

        registry.register_message_hook(
            "message.before",
            "p1",
            _PID,
            on_before,
        )
        await registry.fire_hooks(
            "message",
            "message.before",
            session_id="s1",
            user_id="u1",
            channel="console",
            agent_id="default",
        )
        assert len(calls) == 1
        assert calls[0]["session_id"] == "s1"

    @pytest.mark.asyncio
    async def test_hooks_fire_in_priority_order(
        self,
        registry: PluginRegistry,
    ):
        order: List[str] = []

        def p2(**kwargs):
            order.append("p2")

        def p0(**kwargs):
            order.append("p0")

        def p1(**kwargs):
            order.append("p1")

        registry.register_session_hook(
            "session.create",
            "p2",
            _PID,
            p2,
            priority=200,
        )
        registry.register_session_hook(
            "session.create",
            "p0",
            _PID,
            p0,
            priority=0,
        )
        registry.register_session_hook(
            "session.create",
            "p1",
            _PID,
            p1,
            priority=100,
        )

        await registry.fire_hooks(
            "session",
            "session.create",
            session_id="s1",
        )
        assert order == ["p0", "p1", "p2"]

    @pytest.mark.asyncio
    async def test_hook_failure_does_not_stop_others(
        self,
        registry: PluginRegistry,
    ):
        order: List[str] = []

        def bad(**kwargs):
            raise RuntimeError("boom")

        def good(**kwargs):
            order.append("good")

        registry.register_session_hook(
            "session.create",
            "bad",
            _PID,
            bad,
            priority=0,
        )
        registry.register_session_hook(
            "session.create",
            "good",
            _PID,
            good,
            priority=100,
        )

        await registry.fire_hooks(
            "session",
            "session.create",
            session_id="s1",
        )
        assert order == ["good"]

    @pytest.mark.asyncio
    async def test_hook_timeout(self, registry: PluginRegistry):
        called: List[str] = []

        async def slow(**kwargs):
            called.append("started")
            await asyncio.sleep(10)

        registry.register_session_hook("session.create", "slow", _PID, slow)

        await registry.fire_hooks(
            "session",
            "session.create",
            timeout=0.1,
            session_id="s1",
        )
        # Should have started but not completed
        assert called == ["started"]

    @pytest.mark.asyncio
    async def test_fire_unknown_hook_type_is_noop(
        self,
        registry: PluginRegistry,
    ):
        # Should not raise
        await registry.fire_hooks("unknown", "session.create", session_id="s1")

    @pytest.mark.asyncio
    async def test_fire_with_no_registered_hooks(
        self,
        registry: PluginRegistry,
    ):
        # Should not raise
        await registry.fire_hooks("session", "session.create", session_id="s1")


# ---- ChatManager integration ----


class TestChatManagerHooks:
    @pytest.mark.asyncio
    async def test_get_or_create_chat_fires_session_create(
        self,
        chat_manager: ChatManager,
        registry: PluginRegistry,
    ):
        calls: List[Dict] = []

        def on_create(**kwargs):
            calls.append(kwargs)

        registry.register_session_hook("session.create", "h1", _PID, on_create)

        spec = await chat_manager.get_or_create_chat(
            session_id="console:user1",
            user_id="user1",
            channel="console",
            name="Test",
        )
        assert len(calls) == 1
        assert calls[0]["session_id"] == "console:user1"
        assert calls[0]["chat_id"] == spec.id
        assert calls[0]["agent_id"] == "default"

    @pytest.mark.asyncio
    async def test_get_existing_chat_does_not_fire_create(
        self,
        chat_manager: ChatManager,
        registry: PluginRegistry,
    ):
        calls: List[Dict] = []

        def on_create(**kwargs):
            calls.append(kwargs)

        registry.register_session_hook("session.create", "h1", _PID, on_create)

        # First call creates
        await chat_manager.get_or_create_chat(
            session_id="console:user1",
            user_id="user1",
            channel="console",
        )
        # Second call returns existing
        await chat_manager.get_or_create_chat(
            session_id="console:user1",
            user_id="user1",
            channel="console",
        )
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_create_chat_fires_session_create(
        self,
        chat_manager: ChatManager,
        registry: PluginRegistry,
    ):
        calls: List[Dict] = []

        def on_create(**kwargs):
            calls.append(kwargs)

        registry.register_session_hook("session.create", "h1", _PID, on_create)

        spec = ChatSpec(
            session_id="console:user1",
            user_id="user1",
            channel="console",
            name="Test",
        )
        await chat_manager.create_chat(spec)
        assert len(calls) == 1
        assert calls[0]["chat_id"] == spec.id

    @pytest.mark.asyncio
    async def test_delete_chats_fires_session_end(
        self,
        chat_manager: ChatManager,
        registry: PluginRegistry,
    ):
        calls: List[Dict] = []

        def on_end(**kwargs):
            calls.append(kwargs)

        registry.register_session_hook("session.end", "h1", _PID, on_end)

        spec = await chat_manager.get_or_create_chat(
            session_id="console:user1",
            user_id="user1",
            channel="console",
        )
        # Reset create calls
        calls.clear()

        await chat_manager.delete_chats([spec.id])
        assert len(calls) == 1
        assert calls[0]["chat_id"] == spec.id

    @pytest.mark.asyncio
    async def test_fire_session_reset_hook(
        self,
        chat_manager: ChatManager,
        registry: PluginRegistry,
    ):
        calls: List[Dict] = []

        def on_reset(**kwargs):
            calls.append(kwargs)

        registry.register_session_hook("session.reset", "h1", _PID, on_reset)

        await chat_manager.fire_session_reset_hook(
            session_id="s1",
            user_id="u1",
            channel="console",
        )
        assert len(calls) == 1
        assert calls[0]["session_id"] == "s1"


# ---- unregister_plugin cleanup ----


class TestUnregisterCleanup:
    def test_unregister_removes_session_hooks(self, registry: PluginRegistry):
        registry.register_session_hook(
            "session.create",
            "plugin-a",
            "p1",
            lambda **k: None,
        )
        registry.register_message_hook(
            "message.before",
            "plugin-a",
            "p2",
            lambda **k: None,
        )
        assert len(registry.get_session_hooks("session.create")) == 1
        assert len(registry.get_message_hooks("message.before")) == 1

        registry.unregister_plugin("plugin-a")
        assert len(registry.get_session_hooks("session.create")) == 0
        assert len(registry.get_message_hooks("message.before")) == 0

    def test_unregister_only_removes_target_plugin(
        self,
        registry: PluginRegistry,
    ):
        registry.register_session_hook(
            "session.create",
            "plugin-a",
            "a1",
            lambda **k: None,
        )
        registry.register_session_hook(
            "session.create",
            "plugin-b",
            "b1",
            lambda **k: None,
        )

        registry.unregister_plugin("plugin-a")
        hooks = registry.get_session_hooks("session.create")
        assert len(hooks) == 1
        assert hooks[0].plugin_id == "plugin-b"
