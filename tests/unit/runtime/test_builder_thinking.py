# -*- coding: utf-8 -*-
"""Per-job thinking overrides are applied before model construction."""

# pylint: disable=protected-access

from types import SimpleNamespace

import pytest

from qwenpaw.agents.model_factory import _load_agent_model_settings
from qwenpaw.app.chats.manager import ChatManager
from qwenpaw.app.chats.models import ChatSpec
from qwenpaw.app.chats.repo import JsonChatRepository
from qwenpaw.config.config import AgentProfileConfig, ModelSlotConfig
from qwenpaw.providers.provider import agent_thinking_level
from qwenpaw.providers.provider_catalog import (
    PROVIDER_DASHSCOPE,
    PROVIDER_OPENAI,
)
from qwenpaw.providers.thinking import ThinkingPreference
from qwenpaw.runtime.builder import AgentBuilder
from qwenpaw.schemas import AgentRequest
from qwenpaw.services.session_thinking import apply_session_thinking


def _agent_config(**kwargs) -> AgentProfileConfig:
    return AgentProfileConfig(id="agent", name="Agent", **kwargs)


def test_builder_request_context_merges_cron_override():
    request = AgentRequest(
        session_id="session-1",
        request_context={
            "source": "cron",
            "cron_thinking_level": "off",
        },
    )
    ctx = SimpleNamespace(
        request=request,
        session_id="session-1",
        agent_id="agent",
        root_session_id="session-1",
        root_agent_id="agent",
        workspace_dir=None,
        app_services=None,
        mode_state={},
    )

    request_context = AgentBuilder._build_request_context(ctx)
    config = _agent_config(thinking_level="high")
    result = AgentBuilder._apply_request_thinking(
        config,
        request_context,
    )

    assert request_context["cron_thinking_level"] == "off"
    assert result.thinking_level == "off"


def test_inherit_leaves_agent_level_untouched():
    config = _agent_config(thinking_level="high")

    result = AgentBuilder._apply_request_thinking(
        config,
        {"cron_thinking_level": "inherit"},
    )

    assert result is config
    assert result.thinking_level == "high"


def test_missing_override_leaves_agent_level_untouched():
    config = _agent_config(thinking_level="high")

    result = AgentBuilder._apply_request_thinking(config, {})

    assert result is config
    assert result.thinking_level == "high"


def test_job_off_overrides_session_resolved_agent_level():
    config = _agent_config(thinking_level="high")

    result = AgentBuilder._apply_request_thinking(
        config,
        {"cron_thinking_level": "off"},
    )

    assert result.thinking_level == "off"
    assert result.thinking_budget is None
    assert config.thinking_level == "high"


def test_job_budget_carries_level_and_budget():
    config = _agent_config(thinking_level="high")

    result = AgentBuilder._apply_request_thinking(
        config,
        {
            "cron_thinking_level": "budget",
            "cron_thinking_budget": 4096,
        },
    )

    assert result.thinking_level == "budget"
    assert result.thinking_budget == 4096


def test_invalid_request_override_is_ignored():
    config = _agent_config(thinking_level="high")

    for request_context in (
        {"cron_thinking_level": "enabled"},
        {"cron_thinking_level": "budget"},
        {"cron_thinking_level": "off", "cron_thinking_budget": 4096},
    ):
        result = AgentBuilder._apply_request_thinking(
            config,
            request_context,
        )
        assert result is config
        assert result.thinking_level == "high"


def test_job_off_reaches_provider_wire_settings():
    provider = PROVIDER_OPENAI.model_copy(deep=True)
    config = _agent_config(thinking_level="high")
    overridden = AgentBuilder._apply_request_thinking(
        config,
        {"cron_thinking_level": "off"},
    )

    with agent_thinking_level(
        overridden.thinking_level,
        overridden.thinking_budget,
    ):
        kwargs = provider.get_effective_generate_kwargs("gpt-5.2")

    assert kwargs["reasoning_effort"] == "none"


def test_factory_settings_read_the_request_override():
    config = _agent_config(thinking_level="high")
    overridden = AgentBuilder._apply_request_thinking(
        config,
        {"cron_thinking_level": "off"},
    )

    settings = _load_agent_model_settings("agent", overridden)

    assert settings.thinking_level == "off"
    assert settings.thinking_budget is None


def test_job_budget_reaches_provider_wire_settings():
    provider = PROVIDER_DASHSCOPE.model_copy(deep=True)
    config = _agent_config(thinking_level="high")
    overridden = AgentBuilder._apply_request_thinking(
        config,
        {
            "cron_thinking_level": "budget",
            "cron_thinking_budget": 1234,
        },
    )

    with agent_thinking_level(
        overridden.thinking_level,
        overridden.thinking_budget,
    ):
        kwargs = provider.get_effective_generate_kwargs("qwen3.8-max")

    assert kwargs["thinking_enable"] is True
    assert kwargs["thinking_budget"] == 1234


@pytest.mark.asyncio
async def test_job_override_wins_over_session_preference(tmp_path):
    manager = ChatManager(
        repo=JsonChatRepository(tmp_path / "chats.json"),
    )
    chat = await manager.create_chat(
        ChatSpec(
            session_id="cron:target:job:example",
            user_id="u1",
            channel="console",
        ),
    )
    await manager.set_session_thinking(
        chat.id,
        ThinkingPreference(level="high"),
        "p:m",
    )
    config = AgentProfileConfig(
        id="agent",
        name="Agent",
        active_model=ModelSlotConfig(provider_id="p", model="m"),
    )
    ctx = SimpleNamespace(
        workspace=SimpleNamespace(chat_manager=manager),
        session_id="cron:target:job:example",
        request=SimpleNamespace(channel="console", user_id="u1"),
    )

    resolved = await apply_session_thinking(ctx, config)
    result = AgentBuilder._apply_request_thinking(
        resolved,
        {"cron_thinking_level": "off"},
    )

    assert resolved.thinking_level == "high"
    assert result.thinking_level == "off"
    assert result.thinking_budget is None
