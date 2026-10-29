# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Compare the default memory route with the real, pre-override factory."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from qwenpaw.agents import model_factory
from qwenpaw.agents.memory import reme_light_memory_manager as memory_module
from qwenpaw.config import config as config_module
from qwenpaw.config.config import AgentProfileConfig, ModelSlotConfig
from qwenpaw.exceptions import ConfigurationException, ProviderError
from qwenpaw.providers.fallback_chat_model import FallbackChatModel
from qwenpaw.providers.model_info import ModelInfo
from qwenpaw.providers.ollama_provider import OllamaProvider
from qwenpaw.providers.provider_manager import ProviderManager
from qwenpaw.providers.retry_chat_model import RetryChatModel


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
    providers = SimpleNamespace(
        active_model=ModelSlotConfig(provider_id="ollama", model="global"),
        get_provider=lambda provider_id: (
            provider if provider_id == "ollama" else None
        ),
    )
    providers.get_active_model = lambda: providers.active_model
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
