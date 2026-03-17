# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest


MODEL_FACTORY_PATH = Path(__file__).resolve().parents[3] / "src" / "copaw" / "agents" / "model_factory.py"


class FakeMsg:
    def __init__(self, role: str, blocks: list[dict] | str):
        self.role = role
        self.content = blocks

    def get_content_blocks(self) -> list[dict]:
        if isinstance(self.content, list):
            return list(self.content)
        if not self.content:
            return []
        return [{"type": "text", "text": self.content}]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def model_factory_module(monkeypatch: pytest.MonkeyPatch):
    for name in list(sys.modules):
        if name.startswith("copaw.agents.model_factory"):
            sys.modules.pop(name, None)

    copaw_pkg = types.ModuleType("copaw")
    copaw_pkg.__path__ = []
    agents_pkg = types.ModuleType("copaw.agents")
    agents_pkg.__path__ = []
    utils_pkg = types.ModuleType("copaw.agents.utils")
    utils_pkg.__path__ = []
    providers_pkg = types.ModuleType("copaw.providers")
    providers_pkg.__path__ = []

    monkeypatch.setitem(sys.modules, "copaw", copaw_pkg)
    monkeypatch.setitem(sys.modules, "copaw.agents", agents_pkg)
    monkeypatch.setitem(sys.modules, "copaw.agents.utils", utils_pkg)
    monkeypatch.setitem(sys.modules, "copaw.providers", providers_pkg)

    tool_utils = types.ModuleType("copaw.agents.utils.tool_message_utils")
    tool_utils._sanitize_tool_messages = lambda msgs: msgs
    monkeypatch.setitem(
        sys.modules,
        "copaw.agents.utils.tool_message_utils",
        tool_utils,
    )

    providers_pkg.ProviderManager = object
    retry_model = types.ModuleType("copaw.providers.retry_chat_model")
    retry_model.RetryChatModel = object
    monkeypatch.setitem(
        sys.modules,
        "copaw.providers.retry_chat_model",
        retry_model,
    )

    token_usage = types.ModuleType("copaw.token_usage")
    token_usage.TokenRecordingModelWrapper = object
    monkeypatch.setitem(sys.modules, "copaw.token_usage", token_usage)

    agentscope = types.ModuleType("agentscope")
    agentscope.__version__ = "1.0.16"
    formatter_mod = types.ModuleType("agentscope.formatter")
    model_mod = types.ModuleType("agentscope.model")
    message_mod = types.ModuleType("agentscope.message")

    class FormatterBase:
        pass

    class OpenAIChatFormatter(FormatterBase):
        async def format(self, msgs, **kwargs):
            return await self._format(msgs, **kwargs)

    class ChatModelBase:
        pass

    class OpenAIChatModel:
        pass

    class Msg:
        pass

    formatter_mod.FormatterBase = FormatterBase
    formatter_mod.OpenAIChatFormatter = OpenAIChatFormatter
    model_mod.ChatModelBase = ChatModelBase
    model_mod.OpenAIChatModel = OpenAIChatModel
    message_mod.Msg = Msg

    monkeypatch.setitem(sys.modules, "agentscope", agentscope)
    monkeypatch.setitem(sys.modules, "agentscope.formatter", formatter_mod)
    monkeypatch.setitem(sys.modules, "agentscope.model", model_mod)
    monkeypatch.setitem(sys.modules, "agentscope.message", message_mod)

    spec = importlib.util.spec_from_file_location(
        "copaw.agents.model_factory",
        MODEL_FACTORY_PATH,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "copaw.agents.model_factory", module)
    spec.loader.exec_module(module)
    return module


@pytest.mark.anyio
async def test_reasoning_content_skips_dropped_thinking_only_messages(
    model_factory_module,
    caplog: pytest.LogCaptureFixture,
):
    class BaseFormatter:
        async def _format(self, msgs):
            messages = []
            for msg in msgs:
                blocks = msg.get_content_blocks()
                text = " ".join(
                    block.get("text", "")
                    for block in blocks
                    if block.get("type") == "text" and block.get("text")
                )
                if msg.role == "assistant" and text:
                    messages.append({"role": "assistant", "content": text})
            return messages

    formatter = model_factory_module._create_file_block_support_formatter(
        BaseFormatter
    )()

    messages = [
        FakeMsg("assistant", [{"type": "thinking", "thinking": "discard me"}]),
        FakeMsg(
            "assistant",
            [
                {"type": "thinking", "thinking": "keep me"},
                {"type": "text", "text": "visible answer"},
            ],
        ),
    ]

    with caplog.at_level("WARNING"):
        formatted = await formatter._format(messages)

    assert formatted == [
        {
            "role": "assistant",
            "content": "visible answer",
            "reasoning_content": "keep me",
        }
    ]
    assert "Assistant message count mismatch after formatting" not in caplog.text


@pytest.mark.anyio
async def test_reasoning_content_stays_aligned_with_surviving_assistant_messages(
    model_factory_module,
):
    class BaseFormatter:
        async def _format(self, msgs):
            messages = []
            for msg in msgs:
                blocks = msg.get_content_blocks()
                text = " ".join(
                    block.get("text", "")
                    for block in blocks
                    if block.get("type") == "text" and block.get("text")
                )
                if msg.role == "assistant" and text:
                    messages.append({"role": "assistant", "content": text})
            return messages

    formatter = model_factory_module._create_file_block_support_formatter(
        BaseFormatter
    )()

    formatted = await formatter._format(
        [
            FakeMsg("assistant", [{"type": "text", "text": "plain"}]),
            FakeMsg(
                "assistant",
                [
                    {"type": "thinking", "thinking": "reasoned"},
                    {"type": "text", "text": "final"},
                ],
            ),
        ]
    )

    assert formatted == [
        {"role": "assistant", "content": "plain"},
        {
            "role": "assistant",
            "content": "final",
            "reasoning_content": "reasoned",
        },
    ]
