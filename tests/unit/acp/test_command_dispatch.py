# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from agentscope.message import Msg, TextBlock

from copaw.acp.types import parse_external_agent_text
from copaw.agents.command_handler import CommandHandler
from copaw.app.runner.command_dispatch import run_command_path
from copaw.app.runner.command_dispatch import _is_command


class _FakeMemory:
    def __init__(self, *args, **kwargs):
        _ = args, kwargs
        self.added = []

    def load_state_dict(self, state):
        _ = state

    async def add(self, memories, *args, **kwargs):
        _ = args, kwargs
        self.added.append(memories)

    def state_dict(self):
        return {"content": []}

    async def get_memory(self, *args, **kwargs):
        _ = args, kwargs
        return []


class _FakeHandler:
    def __init__(self, *args, **kwargs):
        _ = args, kwargs

    async def handle_conversation_command(self, query):
        _ = query
        return [
            Msg(
                name="Friday",
                role="assistant",
                content=[
                    {
                        "type": "tool_use",
                        "id": "tool-1",
                        "name": "sessions_spawn",
                        "input": {"task": "demo"},
                        "raw_input": "",
                    }
                ],
            ),
            Msg(
                name="system",
                role="system",
                content=[
                    {
                        "type": "tool_result",
                        "id": "tool-1",
                        "name": "sessions_spawn",
                        "output": "demo result",
                    }
                ],
            ),
            Msg(
                name="Friday",
                role="assistant",
                content=[TextBlock(type="text", text="summary")],
            ),
        ]


async def test_run_command_path_persists_multi_messages(monkeypatch) -> None:
    created = {}

    def fake_memory_factory(*args, **kwargs):
        mem = _FakeMemory(*args, **kwargs)
        created["memory"] = mem
        return mem

    monkeypatch.setattr(
        "copaw.app.runner.command_dispatch.ReMeInMemoryMemory",
        fake_memory_factory,
    )
    monkeypatch.setattr(
        "copaw.app.runner.command_dispatch.CommandHandler",
        _FakeHandler,
    )

    runner = SimpleNamespace(
        memory_manager=None,
        session=SimpleNamespace(
            get_session_state_dict=lambda *args, **kwargs: {},
            update_session_state=lambda *args, **kwargs: None,
        ),
    )

    async def fake_get_session_state_dict(*args, **kwargs):
        _ = args, kwargs
        return {}

    async def fake_update_session_state(*args, **kwargs):
        _ = args, kwargs
        return None

    runner.session.get_session_state_dict = fake_get_session_state_dict
    runner.session.update_session_state = fake_update_session_state

    request = SimpleNamespace(session_id="s1", user_id="u1")
    msgs = [Msg(name="user", role="user", content=[TextBlock(type="text", text="/acp qwen demo")])]

    outputs = []
    async for msg, last in run_command_path(request, msgs, runner):
        outputs.append((msg, last))

    assert len(outputs) == 3
    assert outputs[-1][1] is True
    assert len(created["memory"].added) == 1
    assert len(created["memory"].added[0]) == 3


def test_acp_command_compat_invocation_skips_command_path() -> None:
    assert _is_command("/acp qwen demo") is False


async def test_command_handler_returns_guidance_for_direct_acp_invocation() -> None:
    handler = CommandHandler(
        agent_name="Friday",
        memory=_FakeMemory(),
        memory_manager=None,
        enable_memory_manager=False,
    )

    msg = await handler.handle_conversation_command("/acp")

    assert msg.role == "assistant"
    assert "兼容入口" in msg.content[0]["text"]


def test_parse_external_agent_text_supports_cwd_and_session() -> None:
    parsed = parse_external_agent_text(
        '/acp opencode --cwd "./docs" --session-id session-123 简单分析一下 CONTRIBUTING_zh.md',
    )

    assert parsed is not None
    assert parsed.harness == "opencode"
    assert parsed.keep_session is True
    assert parsed.cwd == "./docs"
    assert parsed.existing_session_id == "session-123"
    assert parsed.prompt == "简单分析一下 CONTRIBUTING_zh.md"


def test_parse_external_agent_text_reuses_previous_session_phrase() -> None:
    parsed = parse_external_agent_text(
        "/acp opencode 请使用之前的 session 当前代码量",
    )

    assert parsed is not None
    assert parsed.harness == "opencode"
    assert parsed.keep_session is True
    assert parsed.existing_session_id is None
    assert parsed.prompt == "当前代码量"


def test_parse_external_agent_text_reuses_current_session_phrase() -> None:
    parsed = parse_external_agent_text(
        "/acp opencode 在当前 session 简单分析CONTRIBUTING_zh.md",
    )

    assert parsed is not None
    assert parsed.harness == "opencode"
    assert parsed.keep_session is True
    assert parsed.existing_session_id is None
    assert parsed.prompt == "简单分析CONTRIBUTING_zh.md"


def test_parse_external_agent_text_reuses_current_acp_session_phrase() -> None:
    parsed = parse_external_agent_text(
        "/acp opencode 在当前 acp session 用写个快速排序算法",
    )

    assert parsed is not None
    assert parsed.harness == "opencode"
    assert parsed.keep_session is True
    assert parsed.existing_session_id is None
    assert parsed.prompt == "写个快速排序算法"
