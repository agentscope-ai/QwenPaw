# -*- coding: utf-8 -*-
"""Integration tests for PawApp context module.

Covers src/qwenpaw/pawapp/context.py (367 uncovered lines):
AppStorage namespaced KV, ToolProxy, UIBridge, AppSettings,
PawAppContext dataclass, ChatReply text extraction.
"""

from __future__ import annotations

from typing import Any

import pytest


class FakeSession:
    """In-memory session stub for AppStorage tests."""

    def __init__(self) -> None:
        self.states: dict[str, dict[str, Any]] = {}
        self.deleted: list[str] = []

    async def get_session_state_dict(
        self,
        session_id: str,
        allow_not_exist: bool = False,
    ) -> dict[str, Any]:
        if session_id not in self.states:
            if allow_not_exist:
                return {}
            raise KeyError(session_id)
        return dict(self.states[session_id])

    async def update_session_state(
        self,
        session_id: str,
        key: str,
        value: Any,
        create_if_not_exist: bool = True,
    ) -> None:
        if create_if_not_exist:
            self.states.setdefault(session_id, {})[key] = value
        elif session_id in self.states:
            if value is None:
                self.states[session_id].pop(key, None)
            else:
                self.states[session_id][key] = value

    async def delete_session(self, session_id: str) -> None:
        self.deleted.append(session_id)
        self.states.pop(session_id, None)


@pytest.mark.integration
@pytest.mark.p1
def test_app_storage_set_get_roundtrip() -> None:
    """Storage namespaces writes and reads back values."""
    import asyncio

    from qwenpaw.pawapp.context import AppStorage

    session = FakeSession()
    storage = AppStorage(session, namespace="pawapp:demo")

    async def run() -> None:
        await storage.set("k1", {"n": 1})
        assert await storage.get("k1") == {"n": 1}
        assert await storage.get("missing") is None
        assert await storage.get("missing", default="d") == "d"

    asyncio.run(run())
    assert session.states["pawapp:demo"] == {"k1": {"n": 1}}


@pytest.mark.integration
@pytest.mark.p1
def test_app_storage_keys_and_delete() -> None:
    """keys lists namespace keys; delete removes a key."""
    import asyncio

    from qwenpaw.pawapp.context import AppStorage

    session = FakeSession()
    storage = AppStorage(session, namespace="ns")

    async def run() -> None:
        await storage.set("a", 1)
        await storage.set("b", 2)
        assert sorted(await storage.keys()) == ["a", "b"]
        await storage.delete("a")
        assert sorted(await storage.keys()) == ["b"]

    asyncio.run(run())


@pytest.mark.integration
@pytest.mark.p1
def test_app_storage_clear_namespace() -> None:
    """clear_namespace deletes the whole session namespace."""
    import asyncio

    from qwenpaw.pawapp.context import AppStorage

    session = FakeSession()
    storage = AppStorage(session, namespace="ns")

    async def run() -> None:
        await storage.set("x", 1)
        await storage.clear_namespace()

    asyncio.run(run())
    assert session.deleted == ["ns"]
    assert "ns" not in session.states


@pytest.mark.integration
@pytest.mark.p1
def test_app_storage_error_paths_return_defaults() -> None:
    """Session errors degrade to defaults instead of raising."""
    import asyncio

    from qwenpaw.pawapp.context import AppStorage

    class BrokenSession(FakeSession):
        async def get_session_state_dict(
            self,
            session_id: str,
            allow_not_exist: bool = False,
        ) -> dict[str, Any]:
            raise RuntimeError("boom")

    storage = AppStorage(BrokenSession(), namespace="ns")

    async def run() -> None:
        assert await storage.get("k", default="safe") == "safe"
        assert await storage.keys() == []

    asyncio.run(run())


@pytest.mark.integration
@pytest.mark.p1
def test_tool_proxy_requires_coordinator() -> None:
    """ToolProxy without a coordinator raises RuntimeError."""
    import asyncio

    from qwenpaw.pawapp.context import ToolProxy

    proxy = ToolProxy(tool_coordinator=None)

    async def run() -> None:
        with pytest.raises(RuntimeError, match="not available"):
            await proxy.invoke("any_tool", {})

    asyncio.run(run())


@pytest.mark.integration
@pytest.mark.p1
def test_tool_proxy_invokes_coordinator() -> None:
    """ToolProxy delegates name and params to the coordinator."""
    import asyncio

    from qwenpaw.pawapp.context import ToolProxy

    class FakeCoordinator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict]] = []

        async def execute(self, name: str, params: dict) -> str:
            self.calls.append((name, params))
            return f"ran:{name}"

    coordinator = FakeCoordinator()
    proxy = ToolProxy(tool_coordinator=coordinator)

    async def run() -> None:
        result = await proxy.invoke("shell", {"cmd": "ls"})
        assert result == "ran:shell"

    asyncio.run(run())
    assert coordinator.calls == [("shell", {"cmd": "ls"})]


@pytest.mark.integration
@pytest.mark.p1
def test_ui_bridge_push_without_channel_noop() -> None:
    """UIBridge.push with no SSE channel is a safe no-op."""
    import asyncio

    from qwenpaw.pawapp.context import UIBridge

    bridge = UIBridge(sse_channel=None)

    async def run() -> None:
        await bridge.push("event_type", {"k": 1})  # must not raise

    asyncio.run(run())


@pytest.mark.integration
@pytest.mark.p1
def test_ui_bridge_push_with_channel() -> None:
    """UIBridge.push forwards typed events over the SSE channel."""
    import asyncio

    from qwenpaw.pawapp.context import UIBridge

    class FakeChannel:
        def __init__(self) -> None:
            self.sent: list[dict] = []

        async def send_event(self, payload: dict) -> None:
            self.sent.append(payload)

    channel = FakeChannel()
    bridge = UIBridge(sse_channel=channel)

    async def run() -> None:
        await bridge.push("progress", {"pct": 50})

    asyncio.run(run())
    assert len(channel.sent) == 1
    event = channel.sent[0]
    assert event["type"] == "pawapp:ui_event"
    assert event["event"] == "progress"
    assert event["data"] == {"pct": 50}


@pytest.mark.integration
@pytest.mark.p1
def test_ui_bridge_confirm_requires_connection() -> None:
    """UIBridge.confirm without channel/approval raises RuntimeError."""
    import asyncio

    from qwenpaw.pawapp.context import UIBridge

    bridge = UIBridge(sse_channel=None, approval_coordinator=None)

    async def run() -> None:
        with pytest.raises(RuntimeError, match="not connected"):
            await bridge.confirm("proceed?")

    asyncio.run(run())


@pytest.mark.integration
@pytest.mark.p1
def test_app_settings_default_when_no_registry() -> None:
    """AppSettings.get returns default without a registry."""
    from qwenpaw.pawapp.context import AppSettings

    settings = AppSettings(plugin_registry=None, app_id="app1")
    assert settings.get("key") is None
    assert settings.get("key", default=42) == 42


@pytest.mark.integration
@pytest.mark.p1
def test_app_settings_reads_tool_config() -> None:
    """AppSettings reads values from plugin tool config."""
    from qwenpaw.pawapp.context import AppSettings

    class FakeRegistry:
        def get_tool_config(self, app_id: str, agent_id: str) -> dict:
            # pylint: disable=unused-argument
            return {"theme": "dark"}

    settings = AppSettings(
        plugin_registry=FakeRegistry(),
        app_id="app1",
        agent_id="agent-x",
    )
    assert settings.get("theme") == "dark"
    assert settings.get("absent", default="d") == "d"


@pytest.mark.integration
@pytest.mark.p1
def test_app_settings_empty_config_returns_default() -> None:
    """Empty tool config falls back to defaults."""
    from qwenpaw.pawapp.context import AppSettings

    class EmptyRegistry:
        def get_tool_config(self, app_id: str, agent_id: str) -> dict:
            # pylint: disable=unused-argument
            return {}

    settings = AppSettings(plugin_registry=EmptyRegistry(), app_id="app1")
    assert settings.get("any", default="d") == "d"


@pytest.mark.integration
@pytest.mark.p1
def test_paw_app_context_defaults() -> None:
    """PawAppContext dataclass has sensible defaults."""
    from qwenpaw.pawapp.context import PawAppContext

    ctx = PawAppContext(app_id="app1")
    assert ctx.app_id == "app1"
    assert ctx.agent_id == "default"
    assert ctx.channel == "console"
    assert ctx.user_id == "default"


@pytest.mark.integration
@pytest.mark.p1
def test_chat_reply_text_from_plain_strings() -> None:
    """ChatReply.text concatenates legacy plain-string chunks."""
    from qwenpaw.pawapp.context import ChatReply

    reply = ChatReply(chunks=["hello ", "world"])
    assert reply.text == "hello world"


@pytest.mark.integration
@pytest.mark.p1
def test_chat_reply_text_from_dicts() -> None:
    """ChatReply.text handles legacy dict chunks with text deltas."""
    from qwenpaw.pawapp.context import ChatReply

    chunks = [
        {"delta": "part1 "},
        {"delta": "part2"},
    ]
    reply = ChatReply(chunks=chunks)
    text = reply.text
    assert isinstance(text, str)
