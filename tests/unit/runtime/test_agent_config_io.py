# -*- coding: utf-8 -*-
"""Tests for agent configuration I/O in the runtime builder."""

import threading
from types import SimpleNamespace

import pytest

from qwenpaw.agents import model_factory
from qwenpaw.app.workspace import workspace as workspace_module
from qwenpaw.app.workspace.workspace import Workspace
from qwenpaw.config import config as config_module
from qwenpaw.exceptions import ConfigurationException
from qwenpaw.providers import provider_manager
from qwenpaw import runtime as runtime_package
from qwenpaw.runtime import builder as builder_module
from qwenpaw.runtime.builder import AgentBuilder
from qwenpaw.runtime.configuration import load_runtime_agent_config


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
    ) as caught:
        await builder.build(ctx)

    assert caught.value.error_code == "MODEL_NOT_CONFIGURED"
    assert len(calls) == 1
    assert calls[0][0] == "agent-1"
    assert calls[0][1] != caller_thread


@pytest.mark.asyncio
async def test_config_load_failure_has_stable_runtime_code(monkeypatch):
    """Config read failures must not look like a missing model."""

    def fail_config_read(_agent_id):
        raise OSError("config offline")

    monkeypatch.setattr(
        config_module,
        "load_agent_config",
        fail_config_read,
    )

    with pytest.raises(ConfigurationException) as caught:
        await load_runtime_agent_config("agent-1")

    assert caught.value.error_code == "AGENT_CONFIG_UNAVAILABLE"
    assert caught.value.config_key == "agent"
    assert isinstance(caught.value.__cause__, OSError)


@pytest.mark.asyncio
async def test_config_load_preserves_existing_error_code(monkeypatch):
    """Structured config errors retain their more specific classification."""

    def fail_config_read(_agent_id):
        raise ConfigurationException(
            "config changed",
            config_key="agent",
            error_code="AGENT_CONFIG_STALE",
        )

    monkeypatch.setattr(
        config_module,
        "load_agent_config",
        fail_config_read,
    )

    with pytest.raises(ConfigurationException) as caught:
        await load_runtime_agent_config("agent-1")

    assert caught.value.error_code == "AGENT_CONFIG_STALE"


@pytest.mark.asyncio
async def test_workspace_emits_failed_response_when_config_is_unavailable(
    monkeypatch,
):
    """A config read failure must not become an empty successful SSE."""

    async def fail_config_read(_agent_id):
        raise ConfigurationException(
            "config offline",
            config_key="agent",
            error_code="AGENT_CONFIG_UNAVAILABLE",
        )

    monkeypatch.setattr(
        workspace_module,
        "load_runtime_agent_config",
        fail_config_read,
    )
    workspace = Workspace.__new__(Workspace)
    workspace.agent_id = "agent-1"

    events = [
        event
        async for event in workspace.stream_query(
            SimpleNamespace(session_id="console:test"),
        )
    ]

    assert len(events) == 1
    assert events[0].object == "response"
    assert events[0].status.value == "failed"
    assert events[0].error == {
        "code": "AGENT_CONFIG_UNAVAILABLE",
        "message": "config offline",
    }


@pytest.mark.asyncio
async def test_workspace_rejects_request_agent_mismatch() -> None:
    """Workspace identity must remain the source of the config snapshot."""
    workspace = Workspace.__new__(Workspace)
    workspace.agent_id = "agent-a"

    events = [
        event
        async for event in workspace.stream_query(
            {
                "agent_id": "agent-b",
                "session_id": "console:test",
            },
        )
    ]

    assert events[-1].status.value == "failed"
    assert events[-1].error["code"] == "AGENT_ID_MISMATCH"


@pytest.mark.asyncio
async def test_workspace_routes_read_only_command_when_config_is_unavailable(
    monkeypatch,
) -> None:
    """Read-only model commands are delegated to Runtime on config failure."""
    config_error = ConfigurationException(
        "config offline",
        config_key="agent",
        error_code="AGENT_CONFIG_UNAVAILABLE",
    )

    async def fail_config_read(_agent_id):
        raise config_error

    received = []

    class FakeRuntime:
        def __init__(self, *, workspace, app_services, config_error):
            received.append((workspace, app_services, config_error))

        async def run(self, request):
            yield request

    monkeypatch.setattr(
        workspace_module,
        "load_runtime_agent_config",
        fail_config_read,
    )
    monkeypatch.setattr(runtime_package, "Runtime", FakeRuntime)
    workspace = Workspace.__new__(Workspace)
    workspace.agent_id = "agent-1"
    workspace._app_services = "services"

    request = {
        "input": [
            {
                "role": "user",
                "content": [{"type": "text", "text": "/model help"}],
            },
        ],
        "session_id": "console:test",
    }
    events = [event async for event in workspace.stream_query(request)]

    assert events == [request]
    assert received == [(workspace, "services", config_error)]


@pytest.mark.asyncio
async def test_workspace_injects_its_single_config_snapshot(monkeypatch):
    """The runtime receives the same config object loaded by the workspace."""
    config = SimpleNamespace(backend="qwenpaw")
    load_calls = []
    received = []

    async def load_config(agent_id):
        load_calls.append(agent_id)
        return config

    class FakeRuntime:
        def __init__(self, *, workspace, app_services, agent_config):
            received.append((workspace, app_services, agent_config))

        async def run(self, request):
            yield request

    monkeypatch.setattr(
        workspace_module,
        "load_runtime_agent_config",
        load_config,
    )
    monkeypatch.setattr(runtime_package, "Runtime", FakeRuntime)
    workspace = Workspace.__new__(Workspace)
    workspace.agent_id = "agent-1"
    workspace.set_app_services("services")
    request = SimpleNamespace(session_id="console:test")

    events = [event async for event in workspace.stream_query(request)]

    assert events == [request]
    assert load_calls == ["agent-1"]
    assert received == [(workspace, "services", config)]


@pytest.mark.asyncio
async def test_builder_reuses_injected_config_snapshot(monkeypatch):
    """Builder must not reload a configuration already on HookContext."""
    config = SimpleNamespace(
        id="agent-1",
        active_model=None,
        coding_mode=None,
    )

    async def unexpected_load(_agent_id):
        raise AssertionError("config must not be loaded twice")

    monkeypatch.setattr(
        builder_module,
        "load_runtime_agent_config",
        unexpected_load,
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
    ctx = SimpleNamespace(
        agent_id="agent-1",
        agent_config=config,
    )

    with pytest.raises(ConfigurationException) as caught:
        await builder.build(ctx)

    assert caught.value.error_code == "MODEL_NOT_CONFIGURED"


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
