# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name,unused-argument
"""Conversation commands must share normal turns' model-selection scope."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentscope.message import Msg, TextBlock
from agentscope.state import AgentState

from qwenpaw.agents.command_handler import CommandHandler
from qwenpaw.app.chats.manager import ChatManager
from qwenpaw.app.chats.models import ChatSpec
from qwenpaw.app.chats.repo import JsonChatRepository
from qwenpaw.config.config import AgentProfileConfig, ModelSlotConfig
from qwenpaw.runtime import builtin_commands
from qwenpaw.runtime.builder import AgentBuilder


@pytest.fixture
async def conversation(tmp_path, monkeypatch):
    default = ModelSlotConfig(provider_id="default", model="M1")
    selected = ModelSlotConfig(provider_id="session", model="M2")
    config = AgentProfileConfig(
        id="agent",
        name="Agent",
        active_model=default,
        thinking_level="high",
    )
    manager = ChatManager(repo=JsonChatRepository(tmp_path / "chats.json"))
    chat = await manager.create_chat(
        ChatSpec(session_id="s", user_id="u", channel="console"),
    )
    await manager.set_session_model(chat.id, selected.model_dump())
    # A colliding session belonging to another user must never win lookup.
    other = await manager.create_chat(
        ChatSpec(session_id="s", user_id="other", channel="console"),
    )
    await manager.set_session_model(
        other.id,
        {"provider_id": "wrong-user", "model": "private"},
    )
    ctx = SimpleNamespace(
        workspace=SimpleNamespace(
            chat_manager=manager,
            memory_manager=None,
            workspace_dir="",
        ),
        workspace_dir=tmp_path,
        agent_id="agent",
        session_id="s",
        request=SimpleNamespace(channel="console", user_id="u"),
        extras={},
    )
    state = AgentState()
    state.context.append(
        Msg(
            name="user",
            role="user",
            content=[TextBlock(type="text", text="Conversation content")],
        ),
    )
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _: config,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.command_handler.load_agent_config",
        lambda _: config,
    )
    monkeypatch.setattr(
        builtin_commands,
        "_load_agent_state",
        AsyncMock(return_value=(state, {})),
    )
    monkeypatch.setattr(builtin_commands, "_save_agent_state", AsyncMock())
    return ctx, config, selected, state


@pytest.mark.parametrize("strategy", ["scroll", "native"])
@pytest.mark.parametrize(
    "selection",
    ["session", "request", "context", "inherit"],
)
async def test_compact_uses_effective_model(
    conversation,
    monkeypatch,
    strategy,
    selection,
):
    ctx, config, selected, _state = conversation
    config.running.light_context_config.strategy = strategy
    config.running.light_context_config.context_compact_config.enabled = True
    override = ModelSlotConfig(provider_id="request", model="M3")
    expected = selected
    if selection == "request":
        ctx.request.model_slot_override = override.model_dump()
        expected = override
    elif selection == "context":
        ctx.request.request_context = {"model_slot_override": "request:M3"}
        expected = override
    elif selection == "inherit":
        chat_id = await ctx.workspace.chat_manager.get_chat_id_by_session(
            "s",
            "console",
            "u",
        )
        await ctx.workspace.chat_manager.set_session_model(chat_id, None)
        expected = config.active_model
    model = object()
    factory = AsyncMock(return_value=(model, None))
    monkeypatch.setattr(
        "qwenpaw.agents.model_factory.create_model_and_formatter_async",
        factory,
    )
    built = []

    def make_agent(**kwargs):
        agent = SimpleNamespace(**kwargs)
        agent.compress_context = AsyncMock()
        built.append(agent)
        return agent

    monkeypatch.setattr("agentscope.agent.Agent", make_agent)
    scroll = SimpleNamespace(
        load_state=lambda _: None,
        compress=AsyncMock(),
        to_dict=lambda: {},
        describe_index=lambda: "",
        describe_summary=lambda: "",
        last_compress={},
        close=lambda: None,
    )
    monkeypatch.setattr(
        CommandHandler,
        "_build_standalone_scroll_manager",
        AsyncMock(return_value=scroll if strategy == "scroll" else None),
    )
    prompt_configs = []

    def build_prompt(_builder, _ctx, cfg):
        prompt_configs.append(cfg)
        return "System prompt"

    monkeypatch.setattr(AgentBuilder, "build_prompt", build_prompt)
    lookup = AsyncMock(
        wraps=ctx.workspace.chat_manager.get_chat_id_by_session,
    )
    monkeypatch.setattr(
        ctx.workspace.chat_manager,
        "get_chat_id_by_session",
        lookup,
    )
    await builtin_commands._make_conversation_adapter("compact").handler(
        ctx,
        "",
    )
    used = factory.await_args.kwargs["agent_config"]
    assert prompt_configs[0] is used
    lookup.assert_awaited_once()
    assert used.active_model == expected
    assert used.thinking_level == (
        "high" if selection == "inherit" else "inherit"
    )
    assert config.active_model.model == "M1"
    assert config.thinking_level == "high"
    assert built[0].model is model
    if strategy == "scroll":
        assert scroll.compress.await_args.args[0] is built[0]
    else:
        built[0].compress_context.assert_awaited_once()


@pytest.mark.parametrize("selection", ["session", "request"])
async def test_history_reports_effective_context_window(
    conversation,
    monkeypatch,
    selection,
):
    ctx, config, _selected, _state = conversation
    if selection == "request":
        ctx.request.model_slot_override = "request:M3"
    monkeypatch.setattr(
        "qwenpaw.agents.command_handler.get_model_max_input_length",
        lambda cfg: {"M1": 1000, "M2": 2000, "M3": 3000}[
            cfg.active_model.model
        ],
    )
    formatter = AsyncMock(return_value="History")
    monkeypatch.setattr(
        "qwenpaw.agents.command_handler.format_history_str",
        formatter,
    )
    await builtin_commands._make_conversation_adapter("history").handler(
        ctx,
        "",
    )
    assert formatter.await_args.args[2] == (
        3000 if selection == "request" else 2000
    )
    assert config.active_model.model == "M1"


async def test_standalone_system_prompt_reports_session_model(
    conversation,
    monkeypatch,
):
    ctx, config, _selected, _state = conversation
    monkeypatch.setattr(
        AgentBuilder,
        "build_prompt",
        lambda self, context, cfg: self._build_env_context(context, cfg),
    )
    result = await builtin_commands._make_conversation_adapter(
        "system_prompt",
    ).handler(ctx, "")
    text = result.get_text_content()
    assert "powered by M2" in text
    assert "powered by M1" not in text
    assert config.active_model.model == "M1"
