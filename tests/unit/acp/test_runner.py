# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from agentscope.memory import InMemoryMemory
from agentscope.message import Msg, TextBlock

from copaw.app.runner.runner import AgentRunner


class _FakeAgent:
    def __init__(self, *args, **kwargs):
        _ = args, kwargs

    async def register_mcp_clients(self) -> None:
        return None

    def set_console_output_enabled(self, *, enabled: bool) -> None:
        _ = enabled


class _FakeChatManager:
    def __init__(self) -> None:
        self.chat = SimpleNamespace(id="chat-1", meta={})

    async def get_or_create_chat(self, *args, **kwargs):
        _ = args, kwargs
        return self.chat

    async def update_chat(self, chat):
        return chat


class _FakeSessionStore:
    def __init__(self) -> None:
        self.state: dict[tuple[str, str], dict] = {}

    async def get_session_state_dict(
        self,
        session_id: str,
        user_id: str = "",
        allow_not_exist: bool = True,
    ) -> dict:
        _ = allow_not_exist
        return self.state.get((session_id, user_id), {})

    async def update_session_state(
        self,
        session_id: str,
        key,
        value,
        user_id: str = "",
        create_if_not_exist: bool = True,
    ) -> None:
        _ = create_if_not_exist
        state = self.state.setdefault((session_id, user_id), {})
        path = key.split(".") if isinstance(key, str) else list(key)
        cursor = state
        for part in path[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[path[-1]] = value


@pytest.mark.asyncio
async def test_external_agent_defaults_to_process_cwd(monkeypatch) -> None:
    runner = AgentRunner()
    runner.set_chat_manager(_FakeChatManager())
    runner.session = _FakeSessionStore()

    captured: dict[str, str] = {}

    class _FakeACPService:
        async def run_turn(self, **kwargs):
            captured["cwd"] = kwargs["cwd"]
            await kwargs["on_message"](
                Msg(
                    name="Friday",
                    role="assistant",
                    content=[TextBlock(type="text", text="ok")],
                ),
                True,
            )
            return SimpleNamespace(
                session_id="acp-session-1",
                cwd=kwargs["cwd"],
            )

    fake_config = SimpleNamespace(
        agents=SimpleNamespace(
            running=SimpleNamespace(
                max_iters=4,
                max_input_length=4000,
            )
        ),
        acp=SimpleNamespace(),
    )

    monkeypatch.setattr("copaw.app.runner.runner.load_config", lambda: fake_config)
    monkeypatch.setattr("copaw.app.runner.runner.CoPawAgent", _FakeAgent)
    monkeypatch.setattr(runner, "_get_acp_service", lambda: _FakeACPService())

    request = SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        external_agent={
            "enabled": True,
            "harness": "opencode",
            "keep_session": False,
        },
    )
    msgs = [
        Msg(
            name="user",
            role="user",
            content=[TextBlock(type="text", text="inspect this repo")],
        )
    ]

    outputs = []
    async for item in runner.query_handler(msgs, request=request):
        outputs.append(item)

    assert outputs
    assert captured["cwd"] == str(Path.cwd())


@pytest.mark.asyncio
async def test_external_agent_reuses_previous_session_from_chat_meta(monkeypatch) -> None:
    runner = AgentRunner()
    chat_manager = _FakeChatManager()
    chat_manager.chat.meta = {
        "external_agent": {
            "harness": "opencode",
            "keep_session": False,
            "acp_session_id": "prev-session-1",
            "cwd": str(Path.cwd()),
        }
    }
    runner.set_chat_manager(chat_manager)
    runner.session = _FakeSessionStore()

    captured: dict[str, object] = {}

    class _FakeACPService:
        async def run_turn(self, **kwargs):
            captured["existing_session_id"] = kwargs["existing_session_id"]
            captured["keep_session"] = kwargs["keep_session"]
            await kwargs["on_message"](
                Msg(
                    name="Friday",
                    role="assistant",
                    content=[TextBlock(type="text", text="ok")],
                ),
                True,
            )
            return SimpleNamespace(
                session_id="prev-session-1",
                cwd=kwargs["cwd"],
            )

    fake_config = SimpleNamespace(
        agents=SimpleNamespace(
            running=SimpleNamespace(
                max_iters=4,
                max_input_length=4000,
            )
        ),
        acp=SimpleNamespace(),
    )

    monkeypatch.setattr("copaw.app.runner.runner.load_config", lambda: fake_config)
    monkeypatch.setattr("copaw.app.runner.runner.CoPawAgent", _FakeAgent)
    monkeypatch.setattr(runner, "_get_acp_service", lambda: _FakeACPService())

    request = SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )
    msgs = [
        Msg(
            name="user",
            role="user",
            content=[
                TextBlock(
                    type="text",
                    text="/acp opencode 请使用之前的 session 当前代码量",
                )
            ],
        )
    ]

    outputs = []
    async for item in runner.query_handler(msgs, request=request):
        outputs.append(item)

    assert outputs
    assert captured["existing_session_id"] == "prev-session-1"
    assert captured["keep_session"] is True


@pytest.mark.asyncio
async def test_external_agent_reuses_current_session_phrase_from_chat_meta(monkeypatch) -> None:
    runner = AgentRunner()
    chat_manager = _FakeChatManager()
    chat_manager.chat.meta = {
        "external_agent": {
            "harness": "opencode",
            "keep_session": False,
            "acp_session_id": "current-session-1",
            "cwd": str(Path.cwd()),
        }
    }
    runner.set_chat_manager(chat_manager)
    runner.session = _FakeSessionStore()

    captured: dict[str, object] = {}

    class _FakeACPService:
        async def run_turn(self, **kwargs):
            captured["existing_session_id"] = kwargs["existing_session_id"]
            captured["keep_session"] = kwargs["keep_session"]
            await kwargs["on_message"](
                Msg(
                    name="Friday",
                    role="assistant",
                    content=[TextBlock(type="text", text="ok")],
                ),
                True,
            )
            return SimpleNamespace(
                session_id="current-session-1",
                cwd=kwargs["cwd"],
            )

    fake_config = SimpleNamespace(
        agents=SimpleNamespace(
            running=SimpleNamespace(
                max_iters=4,
                max_input_length=4000,
            )
        ),
        acp=SimpleNamespace(),
    )

    monkeypatch.setattr("copaw.app.runner.runner.load_config", lambda: fake_config)
    monkeypatch.setattr("copaw.app.runner.runner.CoPawAgent", _FakeAgent)
    monkeypatch.setattr(runner, "_get_acp_service", lambda: _FakeACPService())

    request = SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )
    msgs = [
        Msg(
            name="user",
            role="user",
            content=[
                TextBlock(
                    type="text",
                    text="/acp opencode 在当前 session 简单分析CONTRIBUTING_zh.md",
                )
            ],
        )
    ]

    outputs = []
    async for item in runner.query_handler(msgs, request=request):
        outputs.append(item)

    assert outputs
    assert captured["existing_session_id"] == "current-session-1"
    assert captured["keep_session"] is True


@pytest.mark.asyncio
async def test_external_agent_persists_history_for_chat_reload(
    monkeypatch,
) -> None:
    runner = AgentRunner()
    runner.set_chat_manager(_FakeChatManager())
    runner.session = _FakeSessionStore()

    class _FakeACPService:
        async def run_turn(self, **kwargs):
            await kwargs["on_message"](
                Msg(
                    name="Friday",
                    role="assistant",
                    content=[TextBlock(type="text", text="partial")],
                ),
                False,
            )
            await kwargs["on_message"](
                Msg(
                    name="Friday",
                    role="assistant",
                    content=[TextBlock(type="text", text="final answer")],
                ),
                True,
            )
            return SimpleNamespace(
                session_id="acp-session-1",
                cwd=kwargs["cwd"],
            )

    fake_config = SimpleNamespace(
        agents=SimpleNamespace(
            running=SimpleNamespace(
                max_iters=4,
                max_input_length=4000,
            )
        ),
        acp=SimpleNamespace(),
    )

    monkeypatch.setattr("copaw.app.runner.runner.load_config", lambda: fake_config)
    monkeypatch.setattr("copaw.app.runner.runner.CoPawAgent", _FakeAgent)
    monkeypatch.setattr(runner, "_get_acp_service", lambda: _FakeACPService())

    request = SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        external_agent={
            "enabled": True,
            "harness": "opencode",
            "keep_session": False,
        },
    )
    msgs = [
        Msg(
            name="user",
            role="user",
            content=[TextBlock(type="text", text="inspect this repo")],
        )
    ]

    outputs = []
    async for item in runner.query_handler(msgs, request=request):
        outputs.append(item)

    assert outputs

    persisted = await runner.session.get_session_state_dict("session-1", "user-1")
    memory = InMemoryMemory()
    memory.load_state_dict(persisted["external_agent_memory"])
    history = await memory.get_memory()

    # ACP may produce multiple assistant messages (e.g., before and after tool calls)
    # Check that we have user message and at least one assistant message
    assert history[0].role == "user"
    assert all(msg.role == "assistant" for msg in history[1:])
    assert history[-1].content[0]["text"] == "final answer"
