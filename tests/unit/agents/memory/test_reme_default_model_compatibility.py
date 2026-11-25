# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Compare the default memory route with the real, pre-override factory."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from agentscope.model._model_response import ChatResponse, StructuredResponse
from agentscope.message import Msg

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


def _slot(name, provider_id="ollama"):
    return {"provider_id": provider_id, "model": name}


@pytest.fixture
def make_memory_profile(monkeypatch):
    """Share route configuration while leaving the real factory in use."""

    def make(memory_model, fallback_names):
        profile = AgentProfileConfig(
            id="compatibility",
            name="Compatibility",
            active_model=_slot("agent"),
            fallback_models=[_slot(name) for name in fallback_names],
            fallback_policy={"enabled": True, "target_scope": "configured"},
            running={
                "llm_retry_enabled": False,
                "reme_light_memory_config": {"memory_model": memory_model},
            },
        )
        monkeypatch.setattr(
            memory_module,
            "load_agent_config_async",
            AsyncMock(return_value=profile),
        )
        return profile

    return make


@pytest.mark.parametrize(
    ("saved_image", "main_image", "fallback_image", "override", "expected"),
    [
        (True, False, False, False, ["global"]),
        (True, True, False, False, ["global", "agent"]),
        (False, True, False, False, ["global", "agent"]),
        (False, True, True, False, ["global", "agent", "vision-fallback"]),
        (True, False, False, True, ["global", "agent", "vision-fallback"]),
    ],
)
async def test_image_memory_uses_resolved_capabilities(
    monkeypatch,
    local_models,
    make_memory_model_manager,
    make_memory_profile,
    saved_image,
    main_image,
    fallback_image,
    override,
    expected,
):
    from qwenpaw.providers.openai_chat_model_compat import (
        OpenAIChatModelCompat,
    )

    provider = local_models.get_provider("ollama")
    for card in provider.models:
        if card.id in {"agent", "vision-fallback"}:
            card.supports_image = saved_image
            card.config_overrides = ["supports_image"] if override else []
    provider.discovered_models = [
        ModelInfo(
            id=name,
            name=name,
            supports_image=images,
            probe_source="api",
        )
        for name, images in (
            ("agent", main_image),
            ("vision-fallback", fallback_image),
        )
    ]

    profile = make_memory_profile(_slot("global"), ["vision-fallback"])
    calls = []

    class TransientError(Exception):
        status_code = 503

    async def call(model, messages, **kwargs):
        formatted = await model.formatter.format(messages)
        assert "image_url" in str(formatted)
        calls.append(model.model)
        if model.model != "vision-fallback":
            raise TransientError("unavailable")
        return ChatResponse(
            content=[{"type": "text", "text": "ok"}],
            is_last=True,
        )

    monkeypatch.setattr(OpenAIChatModelCompat, "__call__", call)
    model = await make_memory_model_manager(profile.id)._update_qwenpaw_model(
        require_image_support=True,
    )
    messages = [
        Msg(
            name="user",
            content=[
                {
                    "type": "data",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": (
                            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwC"
                            "AAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII="
                        ),
                    },
                },
            ],
            role="user",
        ),
    ]
    if expected[-1] == "vision-fallback":
        await model(messages=messages)
    else:
        with pytest.raises(TransientError):
            await model(messages=messages)
    assert calls == expected


@pytest.mark.parametrize(
    "provider_id",
    ["OLLAMA", ""],
    ids=["alias", "inherited"],
)
@pytest.mark.parametrize("fallback_names", [[], ["vision-fallback"]])
async def test_equivalent_memory_provider_keeps_main_chain(
    local_models,
    make_memory_model_manager,
    make_memory_profile,
    provider_id,
    fallback_names,
):
    profile = make_memory_profile(_slot("agent", provider_id), fallback_names)
    expected, _ = await model_factory.create_model_and_formatter_async(
        profile.id,
        agent_config=profile,
        resize_images_to_max_bytes=True,
    )
    actual = await make_memory_model_manager(
        profile.id,
    )._update_qwenpaw_model()

    assert _routing_snapshot(actual) == _routing_snapshot(expected)
    if isinstance(actual, FallbackChatModel):
        assert actual._fallback_on_any_error is False


@pytest.mark.parametrize("output", ["response", "stream", "structured"])
@pytest.mark.parametrize(
    ("memory_name", "fallback_names", "main_status", "expected_calls"),
    [
        ("global", ["global", "vision-fallback"], 200, ["global", "agent"]),
        ("global", ["global", "vision-fallback"], 401, ["global", "agent"]),
        (
            "global",
            ["global", "vision-fallback"],
            503,
            ["global", "agent", "vision-fallback"],
        ),
        ("global", ["global"], 200, ["global", "agent"]),
        ("global", ["global"], 401, ["global", "agent"]),
        ("agent", [], 401, ["agent"]),
        ("agent", ["vision-fallback"], 401, ["agent"]),
        ("agent", ["vision-fallback"], 503, ["agent", "vision-fallback"]),
    ],
    ids=[
        "dedicated-main-success",
        "dedicated-main-auth-error",
        "dedicated-chat-fallback",
        "single-main-success",
        "single-main-error",
        "same-primary",
        "same-primary-auth-policy",
        "same-primary-transient",
    ],
)
async def test_memory_routing_preserves_policy_and_metadata(
    monkeypatch,
    local_models,
    make_memory_model_manager,
    make_memory_profile,
    output,
    memory_name,
    fallback_names,
    main_status,
    expected_calls,
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
        assert model.formatter.resize_images_to_max_bytes is True
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

    profile = make_memory_profile(
        _slot(memory_name),
        fallback_names,
    )
    manager = make_memory_model_manager(profile.id)
    model = await manager._update_qwenpaw_model()
    manager._reme.update_component.assert_awaited_once_with(
        "as_llm",
        "default",
        model=model,
    )
    invoke = (
        model.generate_structured_output if output == "structured" else model
    )
    if main_status == 401:
        with pytest.raises(HttpError):
            await invoke(messages=[], tools=[])
        assert calls == expected_calls
        return
    response = await invoke(messages=[], tools=[])
    if output == "stream":
        response = [chunk async for chunk in response][0]
    serving = expected_calls[-1]
    assert calls == expected_calls
    assert response.metadata["qwenpaw_actual_model"]["model_id"] == serving
    assert response.metadata["qwenpaw_actual_model"]["provider_id"] == "ollama"
    events = response.metadata["qwenpaw_model_fallbacks"]
    assert [(e["from_model_id"], e["to_model_id"]) for e in events] == list(
        zip(expected_calls, expected_calls[1:]),
    )


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
