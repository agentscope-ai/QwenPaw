# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for the configurable memory-writing model slot."""

import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from qwenpaw.agents.memory import reme_light_memory_manager
from qwenpaw.agents.memory.reme_light_memory_manager import (
    ReMeLightMemoryManager,
)
from qwenpaw.config.config import ModelSlotConfig
from qwenpaw.exceptions import ProviderError


def _agent_config(
    memory_model: ModelSlotConfig | None = None,
    active_model: ModelSlotConfig | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        active_model=active_model,
        running=SimpleNamespace(
            reme_light_memory_config=SimpleNamespace(
                memory_model=memory_model,
            ),
        ),
    )


def _patch_deps(
    monkeypatch: pytest.MonkeyPatch,
    *,
    agent_config: SimpleNamespace,
    factory: AsyncMock,
    global_model: ModelSlotConfig | None = None,
) -> Mock:
    monkeypatch.setattr(
        reme_light_memory_manager,
        "load_agent_config_async",
        AsyncMock(return_value=agent_config),
    )
    monkeypatch.setattr(
        reme_light_memory_manager,
        "create_model_and_formatter_async",
        factory,
    )
    provider_manager = SimpleNamespace(
        get_active_model=lambda: global_model,
    )
    monkeypatch.setattr(
        reme_light_memory_manager,
        "ProviderManager",
        SimpleNamespace(get_instance=lambda: provider_manager),
    )
    fallback_factory = Mock(
        return_value=SimpleNamespace(name="memory-fallback"),
    )
    monkeypatch.setattr(
        reme_light_memory_manager,
        "FallbackChatModel",
        fallback_factory,
    )
    return fallback_factory


def _build_manager() -> ReMeLightMemoryManager:
    manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    manager.agent_id = "default"
    manager._reme = SimpleNamespace(update_component=AsyncMock())
    return manager


async def test_inherited_hub_catalog_lookup_runs_off_event_loop(monkeypatch):
    """Use the real Hub resolution chain without sending an HTTP request."""
    from qwenpaw.providers import hub_managed
    from qwenpaw.providers.provider_manager import ProviderManager

    loop_thread = threading.get_ident()
    lookup_threads = []
    response = Mock()
    response.json.return_value = {"models": [{"id": "main"}]}

    def get_catalog(*_args, **_kwargs):
        lookup_threads.append(threading.get_ident())
        return response

    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    client.get.side_effect = get_catalog
    monkeypatch.setattr(hub_managed.httpx, "Client", Mock(return_value=client))
    monkeypatch.setenv("QWENPAW_HUB_MODEL_TOKEN", "test-token")
    monkeypatch.setenv("QWENPAW_HUB_MODEL_URL", "http://hub.test")
    providers = ProviderManager.__new__(ProviderManager)
    providers.default_models = {}
    providers.active_model = ModelSlotConfig(
        provider_id="hub-managed",
        model="main",
    )
    monkeypatch.setattr(ProviderManager, "_instance", providers)
    monkeypatch.setattr(
        reme_light_memory_manager,
        "load_agent_config_async",
        AsyncMock(
            return_value=_agent_config(
                memory_model=ModelSlotConfig(provider_id="", model="memory"),
            ),
        ),
    )
    factory = AsyncMock(return_value=(SimpleNamespace(name="model"), None))
    monkeypatch.setattr(
        reme_light_memory_manager,
        "create_model_and_formatter_async",
        factory,
    )
    monkeypatch.setattr(reme_light_memory_manager, "FallbackChatModel", Mock())

    await _build_manager()._update_qwenpaw_model()

    assert lookup_threads and all(t != loop_thread for t in lookup_threads)
    assert factory.await_args_list[1].kwargs["model_slot_override"] == (
        ModelSlotConfig(provider_id="hub-managed", model="memory")
    )


@pytest.mark.parametrize("inherited", [False, True])
async def test_identical_memory_and_main_slots_are_not_duplicated(
    monkeypatch,
    inherited,
):
    slot = ModelSlotConfig(provider_id="ollama", model="qwen2.5:7b")
    main_model = SimpleNamespace(model_key="ollama:qwen2.5:7b")
    factory = AsyncMock(return_value=(main_model, None))
    fallback_factory = _patch_deps(
        monkeypatch,
        agent_config=_agent_config(
            memory_model=(
                ModelSlotConfig(provider_id="", model=slot.model)
                if inherited
                else slot
            ),
            active_model=slot,
        ),
        factory=factory,
    )
    manager = _build_manager()

    assert await manager._update_qwenpaw_model() is main_model

    factory.assert_awaited_once()
    fallback_factory.assert_not_called()
    assert (
        manager._reme.update_component.await_args.kwargs["model"] is main_model
    )


@pytest.mark.parametrize(
    ("memory_model", "active_model", "global_model", "expected_override"),
    [
        # Unset config keeps the existing main-model behavior.
        (None, None, None, None),
        # A full slot is passed through as the override.
        (
            ModelSlotConfig(provider_id="dashscope", model="qwenpaw-flash-4b"),
            None,
            None,
            ModelSlotConfig(provider_id="dashscope", model="qwenpaw-flash-4b"),
        ),
        # A bare model name inherits the agent main model's provider.
        (
            ModelSlotConfig(provider_id="", model="qwenpaw-flash-4b"),
            ModelSlotConfig(provider_id="dashscope", model="qwen3-max"),
            None,
            ModelSlotConfig(provider_id="dashscope", model="qwenpaw-flash-4b"),
        ),
        # Without an agent main model, the global active provider is used.
        (
            ModelSlotConfig(provider_id="", model="qwenpaw-flash-4b"),
            None,
            ModelSlotConfig(provider_id="ollama", model="qwen2.5:7b"),
            ModelSlotConfig(provider_id="ollama", model="qwenpaw-flash-4b"),
        ),
        # Version-tagged bare names inherit the agent's typed provider slot.
        (
            ModelSlotConfig(provider_id="", model="qwen2.5:7b"),
            ModelSlotConfig(provider_id="ollama", model="qwen3:8b"),
            None,
            ModelSlotConfig(provider_id="ollama", model="qwen2.5:7b"),
        ),
        # No inherited provider means the unchanged main-model path is used.
        (
            ModelSlotConfig(provider_id="", model="qwen2.5:7b"),
            None,
            None,
            None,
        ),
        # A slot without a model name is unusable and ignored.
        (
            ModelSlotConfig(provider_id="dashscope", model=""),
            None,
            None,
            None,
        ),
    ],
)
async def test_update_model_slot_selection(
    monkeypatch: pytest.MonkeyPatch,
    memory_model: ModelSlotConfig | None,
    active_model: ModelSlotConfig | None,
    global_model: ModelSlotConfig | None,
    expected_override: ModelSlotConfig | None,
) -> None:
    """The factory must receive the resolved slot, or none when unusable."""
    main_model = SimpleNamespace(name="main")
    memory_model_instance = SimpleNamespace(name="memory")
    factory = AsyncMock(
        side_effect=[
            (main_model, None),
            (memory_model_instance, None),
        ],
    )
    agent_config = _agent_config(
        memory_model=memory_model,
        active_model=active_model,
    )
    fallback_factory = _patch_deps(
        monkeypatch,
        agent_config=agent_config,
        factory=factory,
        global_model=global_model,
    )
    manager = _build_manager()

    await manager._update_qwenpaw_model()

    if expected_override is None:
        factory.assert_awaited_once_with(
            "default",
            agent_config=agent_config,
            require_image_support=False,
            resize_images_to_max_bytes=True,
        )
        expected_model = main_model
        fallback_factory.assert_not_called()
    else:
        assert factory.await_args_list[0].args == ("default",)
        assert factory.await_args_list[0].kwargs == {
            "agent_config": agent_config,
            "require_image_support": False,
            "resize_images_to_max_bytes": True,
        }
        assert factory.await_args_list[1].args == ("default",)
        assert factory.await_args_list[1].kwargs == {
            "model_slot_override": expected_override,
            "agent_config": agent_config,
            "require_image_support": False,
            "resize_images_to_max_bytes": True,
        }
        expected_model = fallback_factory.return_value
        fallback_factory.assert_called_once_with(
            [memory_model_instance, main_model],
            fallback_on_any_error=True,
        )
    manager._reme.update_component.assert_awaited_once_with(
        "as_llm",
        "default",
        model=expected_model,
    )


@pytest.mark.parametrize(
    "error",
    [
        ProviderError("Provider 'missing' not found."),
        ValueError("No API key was provided."),
        RuntimeError("Provider SDK could not initialize."),
    ],
)
async def test_update_model_unavailable_slot_falls_back_to_main_model(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    """A broken memory_model must degrade to the agent's main model."""
    slot = ModelSlotConfig(provider_id="missing", model="qwenpaw-flash-4b")
    main_model = SimpleNamespace(name="main")
    factory = AsyncMock(
        side_effect=[
            (main_model, None),
            error,
        ],
    )
    _patch_deps(
        monkeypatch,
        agent_config=_agent_config(memory_model=slot),
        factory=factory,
    )
    manager = _build_manager()

    actual_model = await manager._update_qwenpaw_model()

    assert actual_model is main_model
    assert factory.await_count == 2
    assert factory.await_args_list[0].kwargs == {
        "agent_config": factory.await_args_list[1].kwargs["agent_config"],
        "require_image_support": False,
        "resize_images_to_max_bytes": True,
    }
    assert factory.await_args_list[1].kwargs["model_slot_override"] == slot
    manager._reme.update_component.assert_awaited_once_with(
        "as_llm",
        "default",
        model=main_model,
    )


async def test_gemini_without_api_key_falls_back_and_reme_starts(monkeypatch):
    """Exercise SDK construction without a model-service request."""
    from qwenpaw.providers.gemini_provider import GeminiProvider

    for variable in (
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_GENAI_USE_VERTEXAI",
        "GOOGLE_CLOUD_PROJECT",
        "GOOGLE_CLOUD_LOCATION",
    ):
        monkeypatch.delenv(variable, raising=False)
    provider = GeminiProvider(id="gemini", name="Gemini", api_key="")
    slot = ModelSlotConfig(provider_id="gemini", model="gemini-2.5-flash")
    # Prove the SDK, rather than a mock exception, reproduces the failure.
    with pytest.raises(ValueError, match="[Aa][Pp][Ii] [Kk]ey"):
        provider.get_chat_model_instance(slot.model)
    main_model = SimpleNamespace(name="healthy-main")

    async def construct_model(_agent_id, **kwargs):
        override = kwargs.get("model_slot_override")
        if override is not None:
            return provider.get_chat_model_instance(override.model), None
        return main_model, None

    factory = AsyncMock(side_effect=construct_model)
    fallback_factory = _patch_deps(
        monkeypatch,
        agent_config=_agent_config(memory_model=slot),
        factory=factory,
    )
    manager = _build_manager()
    manager._reme.start = AsyncMock()

    await manager.start()

    assert factory.await_count == 2
    fallback_factory.assert_not_called()
    manager._reme.update_component.assert_awaited_once_with(
        "as_llm",
        "default",
        model=main_model,
    )
    manager._reme.start.assert_awaited_once_with()


async def test_main_model_construction_errors_remain_visible(monkeypatch):
    """A dedicated-model fallback cannot hide an unusable main model."""
    _patch_deps(
        monkeypatch,
        agent_config=_agent_config(),
        factory=AsyncMock(side_effect=ValueError("Main model is broken")),
    )
    manager = _build_manager()
    with pytest.raises(ValueError, match="Main model is broken"):
        await manager._update_qwenpaw_model()
    manager._reme.update_component.assert_not_awaited()


@pytest.mark.parametrize(
    ("main_supports_images", "memory_supports_images", "expect_fallback"),
    [
        (True, True, True),
        (False, True, False),
        (None, True, False),
        (True, False, True),
    ],
)
async def test_image_jobs_exclude_unsafe_main_model_fallback(
    monkeypatch,
    main_supports_images,
    memory_supports_images,
    expect_fallback,
):
    """Only confirmed image-capable main models can receive memory images."""
    main_model = SimpleNamespace(name="main")
    memory_model = SimpleNamespace(name="memory")
    factory = AsyncMock(side_effect=[(main_model, None), (memory_model, None)])
    fallback_factory = _patch_deps(
        monkeypatch,
        agent_config=_agent_config(
            memory_model=ModelSlotConfig(provider_id="custom", model="vision"),
        ),
        factory=factory,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.prompt.get_model_supports_image",
        lambda model: (
            memory_supports_images
            if model is memory_model
            else main_supports_images
        ),
    )
    manager = _build_manager()

    actual_model = await manager._update_qwenpaw_model(
        require_image_support=True,
    )

    for call in factory.await_args_list:
        assert call.kwargs["require_image_support"] is True
        assert call.kwargs["resize_images_to_max_bytes"] is True
    if expect_fallback:
        fallback_factory.assert_called_once_with(
            [memory_model, main_model],
            fallback_on_any_error=True,
        )
        assert actual_model is fallback_factory.return_value
    else:
        fallback_factory.assert_not_called()
        assert actual_model is memory_model
    assert (
        manager._reme.update_component.await_args.kwargs["model"]
        is actual_model
    )
