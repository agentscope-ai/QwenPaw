# -*- coding: utf-8 -*-
"""Tests for agent configuration I/O in the runtime builder."""

import threading
from types import SimpleNamespace

import pytest

from qwenpaw.agents import model_factory
from qwenpaw.config import config as config_module
from qwenpaw.exceptions import ConfigurationException
from qwenpaw.providers import provider_manager
from qwenpaw.runtime.builder import AgentBuilder


@pytest.mark.asyncio
async def test_build_loads_agent_config_once_in_worker_thread(monkeypatch):
    """The async builder must not read agent config on its event loop."""
    caller_thread = threading.get_ident()
    calls = []
    config = SimpleNamespace(
        id="agent-1",
        active_model=None,
        coding_mode=None,
    )

    def load_agent_config(agent_id):
        calls.append((agent_id, threading.get_ident()))
        return config

    monkeypatch.setattr(
        config_module,
        "load_agent_config",
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
    ctx = SimpleNamespace(agent_id="agent-1")

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
        coding_mode=None,
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
        "_collect_coding_mode_tools",
        lambda *_args: [],
    )
    monkeypatch.setattr(
        builder,
        "_collect_visual_compression_tools",
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
        coding_mode=None,
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
        "_collect_coding_mode_tools",
        lambda *_args: [],
    )
    monkeypatch.setattr(
        builder,
        "_collect_visual_compression_tools",
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

    AgentBuilder.__new__(AgentBuilder).build_model(config, "provider:model")

    assert captured == {
        "agent_id": "agent-1",
        "model_slot_override": "provider:model",
        "agent_config": config,
    }
