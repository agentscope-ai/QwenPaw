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


def _manager():
    manager = memory_module.ReMeLightMemoryManager.__new__(
        memory_module.ReMeLightMemoryManager,
    )
    manager.agent_id = "compatibility"
    manager._reme = SimpleNamespace(
        update_component=AsyncMock(),
        start=AsyncMock(),
    )
    return manager


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
        get_provider=lambda _provider_id: provider,
    )
    providers.get_active_model = lambda: providers.active_model
    monkeypatch.setattr(ProviderManager, "_instance", providers)
    return providers


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
    manager = _manager()

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


@pytest.mark.parametrize("error_type", [ConfigurationException, OSError])
@pytest.mark.parametrize("has_global", [False, True])
@pytest.mark.parametrize("operation", ["start", "update"])
async def test_config_read_failure_keeps_original_global_fallback(
    monkeypatch,
    local_models,
    error_type,
    has_global,
    operation,
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
    manager = _manager()
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


@pytest.mark.parametrize("stage", ["config", "construction", "injection"])
@pytest.mark.parametrize("error_type", [asyncio.CancelledError, RuntimeError])
async def test_default_route_does_not_hide_cancellation_or_model_errors(
    monkeypatch,
    stage,
    error_type,
):
    manager = _manager()
    profile = AgentProfileConfig(id="compatibility", name="Compatibility")
    factory = AsyncMock(return_value=(SimpleNamespace(model="main"), None))
    loader = AsyncMock(return_value=profile)
    error = error_type("Interrupted")
    if stage == "config":
        loader.side_effect = error
    elif stage == "construction":
        factory.side_effect = error
    else:
        manager._reme.update_component.side_effect = error
    monkeypatch.setattr(memory_module, "load_agent_config_async", loader)
    monkeypatch.setattr(
        memory_module,
        "create_model_and_formatter_async",
        factory,
    )
    if stage == "config" and error_type is RuntimeError:
        # Ordinary read failures delegate to the original factory route.
        await manager._update_qwenpaw_model()
        assert factory.await_args.kwargs["agent_config"] is None
    else:
        with pytest.raises(error_type):
            await manager.start()
        manager._reme.start.assert_not_awaited()
    if stage == "config" and error_type is asyncio.CancelledError:
        factory.assert_not_awaited()
