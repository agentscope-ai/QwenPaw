# -*- coding: utf-8 -*-
"""Tests for agent configuration I/O in the runtime builder."""

import threading
from types import SimpleNamespace

import pytest

from qwenpaw.app.workspace.workspace_plugins import WorkspacePlugins
from qwenpaw.modes.coding import CodingMode
from qwenpaw.agents import model_factory
from qwenpaw.config import config as config_module
from qwenpaw.config.config import AgentProfileConfig
from qwenpaw.config.runtime import RuntimeParameters
from qwenpaw.services import session_config
from qwenpaw.exceptions import ConfigurationException
from qwenpaw.providers import provider_manager
from qwenpaw.runtime.builder import AgentBuilder


@pytest.mark.asyncio
async def test_runtime_resolves_config_once_in_worker_thread(
    monkeypatch,
    tmp_path,
):
    """The async builder must not read agent config on its event loop."""
    caller_thread = threading.get_ident()
    calls = []
    config = AgentProfileConfig(
        id="agent-1",
        name="Agent",
        agent_mode="code",
    )

    def load_agent_config(agent_id):
        calls.append((agent_id, threading.get_ident()))
        return config

    monkeypatch.setattr(
        session_config,
        "load_persisted_agent_config",
        load_agent_config,
    )
    monkeypatch.setattr(
        provider_manager,
        "ProviderManager",
        SimpleNamespace(
            get_instance=lambda: SimpleNamespace(
                get_active_model=lambda: None,
            ),
        ),
    )
    builder = AgentBuilder.__new__(AgentBuilder)
    workspace = SimpleNamespace(plugins=WorkspacePlugins())
    workspace.plugins.register_mode(CodingMode(), workspace)
    ctx = SimpleNamespace(
        agent_id="agent-1",
        session_id="",
        workspace=workspace,
        workspace_dir=tmp_path,
        request=SimpleNamespace(),
    )
    parameters, _ = await session_config.resolve_runtime_parameters(ctx)
    assert parameters.config.coding_mode.enabled is True
    with parameters.with_overrides(
        {"coding_mode": {"enabled": False}},
    ).scope():
        overridden, _ = await session_config.resolve_runtime_parameters(ctx)
    assert overridden.config.coding_mode.enabled is False
    with parameters.with_overrides({"agent_mode": None}).scope():
        reset, _ = await session_config.resolve_runtime_parameters(ctx)
    assert reset.config.coding_mode.enabled is False
    ctx.agent_config = parameters.config

    with pytest.raises(
        ConfigurationException,
        match="No active model configured",
    ):
        await builder.build(ctx)

    assert len(calls) == 1
    assert calls[0][0] == "agent-1"
    assert calls[0][1] != caller_thread


@pytest.mark.asyncio
async def test_build_constructs_model_in_worker_thread(monkeypatch):
    """The async builder must offload the complete model factory call."""
    caller_thread = threading.get_ident()
    model_threads = []
    skill_threads = []
    config = SimpleNamespace(
        id="agent-1",
        active_model=None,
        coding_mode=SimpleNamespace(enabled=False),
    )

    monkeypatch.setattr(
        config_module,
        "load_agent_config",
        lambda _agent_id: config,
    )
    monkeypatch.setattr(
        provider_manager,
        "ProviderManager",
        SimpleNamespace(
            get_instance=lambda: SimpleNamespace(
                get_active_model=lambda: SimpleNamespace(
                    provider_id="openai",
                    model="gpt-test",
                ),
            ),
        ),
    )

    builder = AgentBuilder.__new__(AgentBuilder)

    def build_model(_config, model_slot_override=None):
        _ = model_slot_override
        model_threads.append(threading.get_ident())
        raise RuntimeError("model built")

    monkeypatch.setattr(builder, "build_model", build_model)
    monkeypatch.setattr(builder, "_init_governor", lambda *_args: None)
    monkeypatch.setattr(
        builder,
        "_collect_context_recall_tools",
        lambda *_args: [],
    )

    async def collect_drivers(*_args):
        return [], []

    monkeypatch.setattr(
        builder,
        "_collect_driver_tools_and_prompts",
        collect_drivers,
    )

    def ensure_skills_initialized(*_args):
        skill_threads.append(threading.get_ident())

    def resolve_effective_skills(*_args):
        skill_threads.append(threading.get_ident())
        return []

    monkeypatch.setattr(
        "qwenpaw.agents.skill_system.ensure_skills_initialized",
        ensure_skills_initialized,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.skill_system.resolve_effective_skills",
        resolve_effective_skills,
    )
    ctx = SimpleNamespace(
        agent_id="agent-1",
        agent_config=config,
        request=SimpleNamespace(model_slot_override=None),
        extras={},
    )

    with pytest.raises(RuntimeError, match="model built"):
        await builder.build(ctx)

    assert model_threads == [model_threads[0]]
    assert model_threads[0] != caller_thread
    assert len(skill_threads) == 2
    assert all(thread_id != caller_thread for thread_id in skill_threads)


@pytest.mark.asyncio
async def test_build_constructs_prompt_in_worker_thread(monkeypatch):
    """The async builder must offload prompt file and memory reads."""
    caller_thread = threading.get_ident()
    prompt_threads = []
    config = SimpleNamespace(
        id="agent-1",
        active_model=None,
        coding_mode=SimpleNamespace(enabled=False),
    )

    monkeypatch.setattr(
        config_module,
        "load_agent_config",
        lambda _agent_id: config,
    )
    monkeypatch.setattr(
        provider_manager,
        "ProviderManager",
        SimpleNamespace(
            get_instance=lambda: SimpleNamespace(
                get_active_model=lambda: SimpleNamespace(
                    provider_id="openai",
                    model="gpt-test",
                ),
            ),
        ),
    )

    builder = AgentBuilder.__new__(AgentBuilder)
    monkeypatch.setattr(builder, "_init_governor", lambda *_args: None)
    monkeypatch.setattr(
        builder,
        "_collect_context_recall_tools",
        lambda *_args: [],
    )

    async def collect_drivers(*_args):
        return [], []

    monkeypatch.setattr(
        builder,
        "_collect_driver_tools_and_prompts",
        collect_drivers,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.skill_system.ensure_skills_initialized",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.skill_system.resolve_effective_skills",
        lambda *_args: [],
    )
    monkeypatch.setattr(
        builder,
        "build_model",
        lambda *_args, **_kwargs: (SimpleNamespace(formatter=None), None),
    )

    def build_prompt(_ctx, _config):
        prompt_threads.append(threading.get_ident())
        raise RuntimeError("prompt built")

    monkeypatch.setattr(builder, "build_prompt", build_prompt)
    ctx = SimpleNamespace(
        agent_id="agent-1",
        agent_config=config,
        request=SimpleNamespace(model_slot_override=None),
        extras={},
    )

    with pytest.raises(RuntimeError, match="prompt built"):
        await builder.build(ctx)

    assert prompt_threads[0] != caller_thread


def test_build_model_reuses_preloaded_agent_config(monkeypatch):
    """Model creation receives the config already loaded by the builder."""
    config = SimpleNamespace(id="agent-1")
    captured = {}

    def create_model_and_formatter(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(formatter=None), None

    monkeypatch.setattr(
        model_factory,
        "create_model_and_formatter",
        create_model_and_formatter,
    )

    AgentBuilder.__new__(AgentBuilder).build_model(config)

    assert captured == {
        "agent_id": "agent-1",
        "agent_config": config,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("location", ["direct", "context"])
async def test_request_model_is_resolved_before_validation_and_build(
    monkeypatch,
    location,
    tmp_path,
):
    """A request override works even when no agent/global default exists."""
    from unittest.mock import AsyncMock
    from qwenpaw.config.config import AgentProfileConfig, ModelSlotConfig

    config = AgentProfileConfig(
        id="agent",
        name="Agent",
        thinking_level="high",
    )
    selected = ModelSlotConfig(provider_id="request", model="selected")
    monkeypatch.setattr(config_module, "load_agent_config", lambda _: config)
    monkeypatch.setattr(
        "qwenpaw.services.session_thinking.ProviderManager.get_instance",
        lambda: SimpleNamespace(
            active_model=None,
            get_active_model=lambda: None,
        ),
    )
    monkeypatch.setattr(
        "qwenpaw.agents.skill_system.ensure_skills_initialized",
        lambda *_: None,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.skill_system.resolve_effective_skills",
        lambda *_: [],
    )
    builder = AgentBuilder.__new__(AgentBuilder)
    monkeypatch.setattr(builder, "_init_governor", lambda *_: None)
    monkeypatch.setattr(
        builder,
        "_collect_context_recall_tools",
        lambda *_: [],
    )
    monkeypatch.setattr(
        builder,
        "_collect_driver_tools_and_prompts",
        AsyncMock(return_value=([], [])),
    )
    request = SimpleNamespace(request_context={})
    if location == "direct":
        request.model_slot_override = selected
    else:
        request.request_context["model_slot_override"] = selected
    ctx = SimpleNamespace(
        agent_id="agent",
        request=request,
        extras={},
        session_id="",
        workspace=None,
        workspace_dir=tmp_path,
    )
    with RuntimeParameters(profile=config).scope():
        parameters, _ = await session_config.resolve_runtime_parameters(ctx)
    ctx.agent_config = parameters.config

    def build_model(cfg, model_slot_override=None):
        assert cfg.active_model == selected
        assert cfg.thinking_level == "inherit"
        assert model_slot_override is None
        raise RuntimeError("selected model reached factory")

    monkeypatch.setattr(builder, "build_model", build_model)
    with pytest.raises(RuntimeError, match="selected model reached factory"):
        await builder.build(ctx)
    assert config.active_model is None
    assert config.thinking_level == "high"
