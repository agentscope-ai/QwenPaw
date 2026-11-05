# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Compare the default memory route with the real, pre-override factory."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from agentscope.model._model_response import ChatResponse, StructuredResponse

from qwenpaw.agents import model_factory
from qwenpaw.agents.memory import reme_light_memory_manager as memory_module
from qwenpaw.config import config as config_module
from qwenpaw.config.config import AgentProfileConfig, ModelSlotConfig
from qwenpaw.exceptions import ConfigurationException, ProviderError
from qwenpaw.providers.fallback_chat_model import FallbackChatModel
from qwenpaw.providers.model_info import ModelInfo
from qwenpaw.providers.ollama_provider import OllamaProvider
from qwenpaw.providers.plugin_provider_registry import PluginProviderRegistry
from qwenpaw.providers.provider_manager import ProviderManager
from qwenpaw.providers.retry_chat_model import RetryChatModel


@pytest.mark.parametrize("output", ["response", "stream", "structured"])
@pytest.mark.parametrize("main_status", [200, 401, 503])
async def test_combined_memory_fallback_preserves_policy_and_metadata(
    monkeypatch,
    local_models,
    make_memory_model_manager,
    output,
    main_status,
):
    """Use the real factory; replace only SDK calls and ReMe injection."""
    from qwenpaw.providers.openai_chat_model_compat import (
        OpenAIChatModelCompat,
    )

    class HttpError(Exception):
        def __init__(self, status):
            super().__init__(f"HTTP {status}")
            self.status_code = status

    calls = []

    async def call(model, *args, **kwargs):
        calls.append(model.model)
        status = 401 if model.model == "global" else main_status
        if model.model == "vision-fallback":
            status = 200
        if status != 200:
            raise HttpError(status)
        if output == "structured":
            return StructuredResponse(content={"answer": "ok"})
        response = ChatResponse(
            content=[{"type": "text", "text": "ok"}],
            is_last=True,
        )
        if output == "stream":

            async def stream():
                yield response

            return stream()
        return response

    monkeypatch.setattr(OpenAIChatModelCompat, "__call__", call)
    monkeypatch.setattr(
        OpenAIChatModelCompat,
        "generate_structured_output",
        call,
    )

    def slot(name):
        return {"provider_id": "ollama", "model": name}

    profile = AgentProfileConfig.model_validate(
        {
            "id": "combined-chain",
            "name": "Combined chain",
            "active_model": slot("agent"),
            "fallback_policy": {"enabled": True, "target_scope": "configured"},
            "fallback_models": [slot("global"), slot("vision-fallback")],
            "running": {
                "llm_retry_enabled": False,
                "reme_light_memory_config": {"memory_model": slot("global")},
            },
        },
    )
    monkeypatch.setattr(
        memory_module,
        "load_agent_config_async",
        AsyncMock(return_value=profile),
    )
    manager = make_memory_model_manager(profile.id)
    model = await manager._update_qwenpaw_model()
    # Keep the inner policy boundary rather than flattening all candidates
    # into the dedicated memory model's fallback-on-any-error policy.
    assert model._fallback_on_any_error is True
    assert model._models[1]._fallback_on_any_error is False
    assert [m.model for m in model._models[1]._models] == [
        "agent",
        "vision-fallback",
    ]
    invoke = (
        model.generate_structured_output if output == "structured" else model
    )
    if main_status == 401:
        with pytest.raises(HttpError):
            await invoke(messages=[], tools=[])
        assert calls == ["global", "agent"]
        return
    response = await invoke(messages=[], tools=[])
    if output == "stream":
        response = [chunk async for chunk in response][0]
    serving = "vision-fallback" if main_status == 503 else "agent"
    assert calls == (
        ["global", "agent", "vision-fallback"]
        if main_status == 503
        else ["global", "agent"]
    )
    assert response.metadata["qwenpaw_actual_model"]["model_id"] == serving
    assert response.metadata["qwenpaw_actual_model"]["provider_id"] == "ollama"
    events = response.metadata["qwenpaw_model_fallbacks"]
    assert [(e["from_model_id"], e["to_model_id"]) for e in events] == (
        [("global", "agent"), ("agent", "vision-fallback")]
        if main_status == 503
        else [("global", "agent")]
    )


@pytest.mark.parametrize("provider_id", ["ollama", "OLLAMA"])
@pytest.mark.parametrize("with_fallback", [False, True])
@pytest.mark.parametrize("output", ["response", "stream", "structured"])
async def test_equivalent_memory_primary_preserves_auth_failure_policy(
    monkeypatch,
    local_models,
    make_memory_model_manager,
    provider_id,
    with_fallback,
    output,
):
    from qwenpaw.providers.openai_chat_model_compat import (
        OpenAIChatModelCompat,
    )

    class AuthError(Exception):
        status_code = 401

    calls = []

    async def call(model, *args, **kwargs):
        calls.append(model.model)
        if model.model == "agent":
            raise AuthError("Invalid API key")
        return StructuredResponse(content={"answer": "unexpected fallback"})

    monkeypatch.setattr(OpenAIChatModelCompat, "__call__", call)
    monkeypatch.setattr(
        OpenAIChatModelCompat,
        "generate_structured_output",
        call,
    )
    profile = AgentProfileConfig.model_validate(
        {
            "id": "equivalent-primary",
            "name": "Equivalent primary",
            "active_model": {"provider_id": "ollama", "model": "agent"},
            "fallback_policy": {"enabled": True, "target_scope": "configured"},
            "fallback_models": (
                [{"provider_id": "ollama", "model": "vision-fallback"}]
                if with_fallback
                else []
            ),
            "running": {
                "llm_retry_enabled": False,
                "reme_light_memory_config": {
                    "memory_model": {
                        "provider_id": provider_id,
                        "model": "agent",
                    },
                },
            },
        },
    )
    monkeypatch.setattr(
        memory_module,
        "load_agent_config_async",
        AsyncMock(return_value=profile),
    )
    manager = make_memory_model_manager(profile.id)
    model = await manager._update_qwenpaw_model()
    invoke = (
        model.generate_structured_output if output == "structured" else model
    )
    with pytest.raises(AuthError):
        response = await invoke(messages=[], tools=[])
        if output == "stream":
            _ = [chunk async for chunk in response]
    assert calls == ["agent"]


@pytest.fixture(name="local_models")
def fixture_local_models(monkeypatch):
    """Real local model construction, without live model-service requests."""
    monkeypatch.delenv("QWENPAW_HUB_MODEL_TOKEN", raising=False)
    provider = OllamaProvider(
        id="ollama",
        name="Ollama",
        api_key="ollama",
        models=[
            ModelInfo(id=name, name=name, supports_image=image)
            for name, image in (
                ("agent", True),
                ("global", True),
                ("text-fallback", False),
                ("vision-fallback", True),
            )
        ],
    )
    providers = ProviderManager.__new__(ProviderManager)
    providers.default_models = {}
    providers.active_model = ModelSlotConfig(
        provider_id="ollama",
        model="global",
    )
    providers.builtin_providers = {"ollama": provider}
    providers.custom_providers = {}
    providers.plugin_providers = {}
    providers._plugin_registry = PluginProviderRegistry(providers)
    monkeypatch.setattr(ProviderManager, "_instance", providers)
    return providers


@pytest.mark.parametrize("require_images", [False, True])
async def test_dedicated_local_model_survives_missing_main_provider(
    monkeypatch,
    local_models,
    require_images,
    make_memory_model_manager,
):
    profile = AgentProfileConfig(
        id="compatibility",
        name="Compatibility",
        active_model=ModelSlotConfig(provider_id="removed", model="broken"),
    )
    profile.running.reme_light_memory_config.memory_model = ModelSlotConfig(
        provider_id="ollama",
        model="agent",
    )
    monkeypatch.setattr(
        memory_module,
        "load_agent_config_async",
        AsyncMock(return_value=profile),
    )
    manager = make_memory_model_manager("compatibility")

    actual = await manager._update_qwenpaw_model(
        require_image_support=require_images,
    )

    assert isinstance(actual, RetryChatModel)
    assert actual.model == "agent"
    assert actual.formatter.resize_images_to_max_bytes is True
    assert local_models.get_provider("ollama") is not None
    manager._reme.update_component.assert_awaited_once_with(
        "as_llm",
        "default",
        model=actual,
    )
    await manager.start()
    manager._reme.start.assert_awaited_once_with()


def _routing_snapshot(model):
    if isinstance(model, FallbackChatModel):
        return [_routing_snapshot(candidate) for candidate in model._models]
    assert isinstance(model, RetryChatModel)
    return (
        model.model_key,
        model._retry_config,
        model._rate_limit_config,
        model.formatter.resize_images_to_max_bytes,
    )


@pytest.mark.parametrize("memory_setting", [{}, {"memory_model": None}])
@pytest.mark.parametrize("agent_specific", [False, True])
@pytest.mark.parametrize("require_images", [False, True])
async def test_default_route_preserves_factory_settings(
    monkeypatch,
    local_models,
    memory_setting,
    agent_specific,
    require_images,
    make_memory_model_manager,
):
    profile = AgentProfileConfig.model_validate(
        {
            "id": "compatibility",
            "name": "Compatibility",
            "active_model": (
                {"provider_id": "ollama", "model": "agent"}
                if agent_specific
                else None
            ),
            "fallback_policy": {"enabled": True, "target_scope": "configured"},
            "fallback_models": [
                {"provider_id": "ollama", "model": "text-fallback"},
                {"provider_id": "ollama", "model": "vision-fallback"},
            ],
            "running": {
                "reme_light_memory_config": memory_setting,
                "llm_max_retries": 2,
                "llm_max_concurrent": 3,
            },
        },
    )
    monkeypatch.setattr(
        config_module,
        "load_agent_config",
        Mock(return_value=profile),
    )
    monkeypatch.setattr(
        memory_module,
        "load_agent_config_async",
        AsyncMock(return_value=profile),
    )
    # This is the original method's factory call, without the new preload.
    expected, _ = await model_factory.create_model_and_formatter_async(
        "compatibility",
        require_image_support=require_images,
        resize_images_to_max_bytes=True,
    )
    manager = make_memory_model_manager("compatibility")

    actual = await manager._update_qwenpaw_model(
        require_image_support=require_images,
    )

    assert _routing_snapshot(actual) == _routing_snapshot(expected)
    assert len(actual._models) == (2 if require_images else 3)
    assert not isinstance(actual._models[0], FallbackChatModel)
    expected_name = (
        "agent" if agent_specific else local_models.active_model.model
    )
    assert actual._models[0].model == expected_name
    manager._reme.update_component.assert_awaited_once_with(
        "as_llm",
        "default",
        model=actual,
    )


@pytest.mark.parametrize(
    "error_type",
    [ConfigurationException, OSError, RuntimeError],
)
@pytest.mark.parametrize("has_global", [False, True])
@pytest.mark.parametrize("operation", ["start", "update"])
async def test_config_read_failure_keeps_original_global_fallback(
    monkeypatch,
    local_models,
    error_type,
    has_global,
    operation,
    make_memory_model_manager,
):
    if not has_global:
        local_models.active_model = None
    error = error_type("Unreadable agent config")
    monkeypatch.setattr(
        config_module,
        "load_agent_config",
        Mock(side_effect=error),
    )
    monkeypatch.setattr(
        memory_module,
        "load_agent_config_async",
        AsyncMock(side_effect=error),
    )
    manager = make_memory_model_manager("compatibility")
    if operation == "start":
        await manager.start()
        manager._reme.start.assert_awaited_once_with()
    elif has_global:
        await manager._update_qwenpaw_model()
    else:
        with pytest.raises(ProviderError):
            await manager._update_qwenpaw_model()
    if has_global:
        actual = manager._reme.update_component.await_args.kwargs["model"]
        expected, _ = await model_factory.create_model_and_formatter_async(
            "compatibility",
            resize_images_to_max_bytes=True,
        )
        assert _routing_snapshot(actual) == _routing_snapshot(expected)
    else:
        manager._reme.update_component.assert_not_awaited()


@pytest.fixture(name="default_route")
def fixture_default_route(monkeypatch, make_memory_model_manager):
    manager = make_memory_model_manager("compatibility")
    profile = AgentProfileConfig(id="compatibility", name="Compatibility")
    calls = {
        "config": AsyncMock(return_value=profile),
        "construction": AsyncMock(
            return_value=(SimpleNamespace(model="main"), None),
        ),
        "injection": manager._reme.update_component,
    }
    monkeypatch.setattr(
        memory_module,
        "load_agent_config_async",
        calls["config"],
    )
    monkeypatch.setattr(
        memory_module,
        "create_model_and_formatter_async",
        calls["construction"],
    )
    return manager, calls


@pytest.mark.parametrize("stage", ["config", "construction", "injection"])
async def test_default_route_propagates_cancellation(default_route, stage):
    manager, calls = default_route
    calls[stage].side_effect = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await manager.start()

    manager._reme.start.assert_not_awaited()
    if stage == "config":
        calls["construction"].assert_not_awaited()


@pytest.mark.parametrize("stage", ["construction", "injection"])
@pytest.mark.parametrize("error_type", [RuntimeError, ValueError])
async def test_default_route_propagates_model_errors(
    default_route,
    stage,
    error_type,
):
    manager, calls = default_route
    calls[stage].side_effect = error_type("Model operation failed")

    with pytest.raises(error_type, match="Model operation failed"):
        await manager.start()

    manager._reme.start.assert_not_awaited()
