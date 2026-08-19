# -*- coding: utf-8 -*-
"""Tests for the ephemeral ACP OpenAI-compatible provider."""

# pylint: disable=protected-access

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from acp import RequestError, text_block

from qwenpaw.agents.acp.runtime_provider import (
    QWENPAW_MODEL_INFO_ENV,
    RUNTIME_OPENAI_PROVIDER_ID,
    OpenAIRuntimeProviderConfig,
)
from qwenpaw.agents.acp.server import QwenPawACPAgent
from qwenpaw.config.config import ModelSlotConfig


class _FakeManager:
    def __init__(self) -> None:
        self.custom_providers = {}
        self.active_model = ModelSlotConfig(
            provider_id="original",
            model="original-model",
        )

    def get_provider(self, provider_id):  # noqa: ANN001
        return self.custom_providers.get(provider_id)

    async def list_provider_info(self):
        return [
            SimpleNamespace(
                id=provider.id,
                models=[
                    SimpleNamespace(id=model.id, name=model.name)
                    for model in provider.models
                ],
                extra_models=[],
            )
            for provider in self.custom_providers.values()
        ]


class _FakeConn:
    def __init__(self) -> None:
        self.updates = []

    async def session_update(self, session_id, update):  # noqa: ANN001
        self.updates.append((session_id, update))


class _FakeWorkspace:
    def __init__(self) -> None:
        self.requests = []

    async def stream_query(self, request):  # noqa: ANN001
        self.requests.append(request)
        for event in ():
            yield event


def _config() -> OpenAIRuntimeProviderConfig:
    return OpenAIRuntimeProviderConfig(
        base_url="https://policy.example.test/v1",
        api_key="execution-secret",
        model="policy",
    )


def test_runtime_provider_requires_complete_environment():
    with pytest.raises(ValueError) as exc_info:
        OpenAIRuntimeProviderConfig.from_env(
            {
                "OPENAI_BASE_URL": "https://policy.example.test/v1",
                "OPENAI_API_KEY": "execution-secret",
            },
        )

    assert "OPENAI_MODEL" in str(exc_info.value)
    assert "execution-secret" not in str(exc_info.value)


@pytest.mark.parametrize(
    "base_url",
    [
        "policy.example.test/v1",
        "file:///tmp/policy.sock",
        "",
    ],
)
def test_runtime_provider_rejects_invalid_base_url(base_url):
    with pytest.raises(ValueError):
        OpenAIRuntimeProviderConfig.from_env(
            {
                "OPENAI_BASE_URL": base_url,
                "OPENAI_API_KEY": "execution-secret",
                "OPENAI_MODEL": "policy",
            },
        )


def test_runtime_provider_builds_openai_provider():
    provider = _config().build_provider()

    assert provider.id == RUNTIME_OPENAI_PROVIDER_ID
    assert provider.base_url == "https://policy.example.test/v1"
    assert provider.api_key == "execution-secret"
    assert provider.has_model("policy")


def test_runtime_provider_applies_model_info():
    config = OpenAIRuntimeProviderConfig.from_env(
        {
            "OPENAI_BASE_URL": "https://policy.example.test/v1",
            "OPENAI_API_KEY": "execution-secret",
            "OPENAI_MODEL": "policy",
            QWENPAW_MODEL_INFO_ENV: (
                '{"max_input_tokens":32768,"max_output_tokens":4096}'
            ),
        },
    )

    provider = config.build_provider()
    model = provider.models[0]

    assert config.max_input_tokens == 32768
    assert config.max_output_tokens == 4096
    assert model.max_input_length == 32768
    assert model.max_input_length_configured is True
    assert model.max_tokens == 4096
    assert provider.get_context_size("policy") == 32768
    assert (
        provider.get_effective_generate_kwargs("policy")["max_tokens"] == 4096
    )


@pytest.mark.parametrize(
    "model_info",
    [
        "[]",
        "not-json",
        '{"max_input_tokens":0}',
        '{"max_input_tokens":999}',
        '{"max_input_tokens":1.0}',
        '{"max_input_tokens":"1000"}',
        '{"max_input_tokens":Infinity}',
        '{"max_output_tokens":NaN}',
        '{"max_output_tokens":true}',
    ],
)
def test_runtime_provider_rejects_invalid_model_info(model_info):
    with pytest.raises(ValueError, match=QWENPAW_MODEL_INFO_ENV):
        OpenAIRuntimeProviderConfig.from_env(
            {
                "OPENAI_BASE_URL": "https://policy.example.test/v1",
                "OPENAI_API_KEY": "execution-secret",
                "OPENAI_MODEL": "policy",
                QWENPAW_MODEL_INFO_ENV: model_info,
            },
        )


async def test_runtime_provider_is_registered_only_in_memory(monkeypatch):
    manager = _FakeManager()
    original_model = manager.active_model
    agent = QwenPawACPAgent(
        agent_id="default",
        runtime_provider=_config(),
    )
    monkeypatch.setattr(
        "qwenpaw.agents.acp.server.ProviderManager.get_instance",
        lambda: manager,
    )

    await agent._install_runtime_provider()

    provider = manager.custom_providers[RUNTIME_OPENAI_PROVIDER_ID]
    assert provider.api_key == "execution-secret"
    assert manager.active_model == _config().model_slot

    agent._remove_runtime_provider()

    assert not manager.custom_providers
    assert manager.active_model is original_model


async def test_runtime_provider_initialization_uses_sync_io(monkeypatch):
    manager = _FakeManager()
    operations = []
    agent = QwenPawACPAgent(
        agent_id="default",
        runtime_provider=_config(),
    )

    def get_manager():
        return manager

    async def fake_run_sync_io(operation):
        operations.append(operation)
        return operation()

    monkeypatch.setattr(
        "qwenpaw.agents.acp.server.ProviderManager.get_instance",
        get_manager,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.acp.server.run_sync_io",
        fake_run_sync_io,
    )

    await agent._install_runtime_provider()

    assert operations == [get_manager]


async def test_runtime_provider_credentials_are_not_persisted(
    isolated_secret_dir,
):
    agent = QwenPawACPAgent(
        agent_id="default",
        runtime_provider=_config(),
    )

    await agent._install_runtime_provider()

    stored_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in isolated_secret_dir.rglob("*")
        if path.is_file()
    )
    assert "execution-secret" not in stored_text
    assert "policy.example.test" not in stored_text

    agent._remove_runtime_provider()


async def test_runtime_provider_forces_model_override(monkeypatch):
    manager = _FakeManager()
    workspace = _FakeWorkspace()
    agent = QwenPawACPAgent(
        agent_id="default",
        runtime_provider=_config(),
    )
    agent.on_connect(_FakeConn())
    monkeypatch.setattr(
        "qwenpaw.agents.acp.server.ProviderManager.get_instance",
        lambda: manager,
    )

    async def _fake_workspace():
        return workspace

    monkeypatch.setattr(agent, "_ensure_workspace", _fake_workspace)
    await agent._install_runtime_provider()
    response = await agent.new_session(cwd="/task")

    await agent.set_session_model(
        model_id="policy",
        session_id=response.session_id,
    )
    await agent.prompt(
        prompt=[text_block("hello")],
        session_id=response.session_id,
    )

    assert workspace.requests
    assert workspace.requests[0].model_slot_override == _config().model_slot


async def test_runtime_provider_is_advertised_as_current_model(monkeypatch):
    manager = _FakeManager()
    agent = QwenPawACPAgent(
        agent_id="default",
        runtime_provider=_config(),
    )
    monkeypatch.setattr(
        "qwenpaw.agents.acp.server.ProviderManager.get_instance",
        lambda: manager,
    )
    await agent._install_runtime_provider()

    model_state = await agent._build_model_state()

    assert model_state is not None
    assert model_state.current_model_id == "runtime-openai:policy"
    assert [model.model_id for model in model_state.available_models] == [
        "runtime-openai:policy",
    ]


async def test_runtime_provider_rejects_other_model():
    agent = QwenPawACPAgent(
        agent_id="default",
        runtime_provider=_config(),
    )
    response = await agent.new_session(cwd="/task")

    with pytest.raises(RequestError) as exc_info:
        await agent.set_session_model(
            model_id="fallback-model",
            session_id=response.session_id,
        )

    assert exc_info.value.code == -32602
    assert exc_info.value.data == {
        "model_id": "fallback-model",
        "details": "Runtime model must be 'policy'",
    }


async def test_runtime_failure_is_an_acp_request_error(monkeypatch):
    async def _raise_runtime_error():
        raise RuntimeError("upstream returned secret-token")

    class _FailingWorkspace:
        async def stream_query(self, request):  # noqa: ANN001
            del request
            yield await _raise_runtime_error()

    agent = QwenPawACPAgent(
        agent_id="default",
        runtime_provider=_config(),
    )
    conn = _FakeConn()
    agent.on_connect(conn)

    async def _fake_workspace():
        return _FailingWorkspace()

    monkeypatch.setattr(agent, "_ensure_workspace", _fake_workspace)
    response = await agent.new_session(cwd="/task")

    with pytest.raises(RequestError) as exc_info:
        await agent.prompt(
            prompt=[text_block("hello")],
            session_id=response.session_id,
        )

    assert exc_info.value.code == -32603
    assert exc_info.value.data == {
        "details": "QwenPaw runtime failed",
    }
    assert "secret-token" not in str(conn.updates)


async def test_cancel_stops_active_prompt(monkeypatch):
    started = asyncio.Event()
    cancelled = asyncio.Event()

    class _BlockingWorkspace:
        async def stream_query(self, request):  # noqa: ANN001
            del request
            started.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                cancelled.set()
                raise
            yield

    agent = QwenPawACPAgent(
        agent_id="default",
        runtime_provider=_config(),
    )
    agent.on_connect(_FakeConn())

    async def _fake_workspace():
        return _BlockingWorkspace()

    monkeypatch.setattr(agent, "_ensure_workspace", _fake_workspace)
    response = await agent.new_session(cwd="/task")
    prompt_task = asyncio.create_task(
        agent.prompt(
            prompt=[text_block("hello")],
            session_id=response.session_id,
        ),
    )
    await asyncio.wait_for(started.wait(), timeout=1)

    await agent.cancel(session_id=response.session_id)
    result = await asyncio.wait_for(prompt_task, timeout=1)

    assert cancelled.is_set()
    assert result.stop_reason == "cancelled"
