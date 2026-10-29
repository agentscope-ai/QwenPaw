# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for the configurable memory-writing model slot."""

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call

import pytest

from qwenpaw.agents.memory import reme_light_memory_manager
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


@pytest.fixture(name="model_setup")
def fixture_model_setup(monkeypatch, make_memory_model_manager):
    """Wire mocked dependencies and return the manager and fallback spy."""

    def setup(
        *,
        factory,
        memory_model=None,
        active_model=None,
        global_model=None,
        agent_config=None,
    ):
        if agent_config is None:
            agent_config = _agent_config(memory_model, active_model)
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
        return make_memory_model_manager(), fallback_factory

    return setup


async def test_inherited_hub_catalog_lookup_runs_off_event_loop(
    monkeypatch,
    make_memory_model_manager,
):
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

    await make_memory_model_manager()._update_qwenpaw_model()

    assert lookup_threads and all(t != loop_thread for t in lookup_threads)
    assert factory.await_args_list[1].kwargs["model_slot_override"] == (
        ModelSlotConfig(provider_id="hub-managed", model="memory")
    )


@pytest.mark.parametrize(
    "main_error",
    [
        ProviderError("Main provider removed"),
        ValueError("No main API key"),
    ],
)
async def test_main_construction_failure_allows_dedicated_model(
    main_error,
    model_setup,
):
    memory_model = SimpleNamespace(model="memory")
    factory = AsyncMock(side_effect=[main_error, (memory_model, None)])
    manager, fallback = model_setup(
        memory_model=ModelSlotConfig(
            provider_id="memory-provider",
            model="memory",
        ),
        factory=factory,
    )

    assert await manager._update_qwenpaw_model() is memory_model
    fallback.assert_not_called()
    assert factory.await_count == 2


async def test_both_model_construction_failures_are_not_hidden(model_setup):
    factory = AsyncMock(
        side_effect=[
            ProviderError("Main provider removed"),
            ValueError("Memory key missing"),
        ],
    )
    manager, _ = model_setup(
        memory_model=ModelSlotConfig(
            provider_id="memory-provider",
            model="memory",
        ),
        factory=factory,
    )
    with pytest.raises(ValueError, match="Memory key missing"):
        await manager._update_qwenpaw_model()
    manager._reme.update_component.assert_not_awaited()


async def test_main_construction_cancellation_does_not_try_memory(model_setup):
    factory = AsyncMock(side_effect=asyncio.CancelledError())
    manager, _ = model_setup(
        memory_model=ModelSlotConfig(
            provider_id="memory-provider",
            model="memory",
        ),
        factory=factory,
    )
    with pytest.raises(asyncio.CancelledError):
        await manager._update_qwenpaw_model()
    factory.assert_awaited_once()
    manager._reme.update_component.assert_not_awaited()


@pytest.mark.parametrize("inherited", [False, True])
async def test_identical_memory_and_main_slots_are_not_duplicated(
    inherited,
    model_setup,
):
    slot = ModelSlotConfig(provider_id="ollama", model="qwen2.5:7b")
    main_model = SimpleNamespace(model_key="ollama:qwen2.5:7b")
    factory = AsyncMock(return_value=(main_model, None))
    manager, fallback_factory = model_setup(
        memory_model=(
            ModelSlotConfig(provider_id="", model=slot.model)
            if inherited
            else slot
        ),
        active_model=slot,
        factory=factory,
    )

    assert await manager._update_qwenpaw_model() is main_model

    factory.assert_awaited_once()
    fallback_factory.assert_not_called()
    assert (
        manager._reme.update_component.await_args.kwargs["model"] is main_model
    )


@pytest.mark.parametrize(
    ("provider", "model", "agent_provider", "global_provider", "expected"),
    [
        ("", None, None, None, None),
        ("dashscope", "memory", None, None, "dashscope"),
        ("", "memory", "dashscope", None, "dashscope"),
        ("", "memory", None, "ollama", "ollama"),
        ("", "qwen2.5:7b", "ollama", None, "ollama"),
        ("", "memory", None, None, None),
        ("dashscope", "", None, None, None),
    ],
    ids=[
        "unset",
        "explicit",
        "agent-provider",
        "global-provider",
        "version-tag",
        "no-provider",
        "empty-model",
    ],
)
def test_memory_slot_resolution(
    model_setup,
    provider,
    model,
    agent_provider,
    global_provider,
    expected,
):
    config = _agent_config(
        memory_model=(
            ModelSlotConfig(provider_id=provider, model=model)
            if model is not None
            else None
        ),
        active_model=(
            ModelSlotConfig(provider_id=agent_provider, model="chat")
            if agent_provider
            else None
        ),
    )
    manager, _ = model_setup(
        agent_config=config,
        factory=AsyncMock(),
        global_model=(
            ModelSlotConfig(provider_id=global_provider, model="chat")
            if global_provider
            else None
        ),
    )

    assert manager._memory_model_slot(config) == (
        ModelSlotConfig(provider_id=expected, model=model)
        if expected
        else None
    )


async def test_dedicated_model_receives_shared_factory_settings(model_setup):
    """Verify factory wiring once, separately from slot normalization."""
    slot = ModelSlotConfig(provider_id="dashscope", model="memory")
    config = _agent_config(memory_model=slot)
    main_model, memory_model = SimpleNamespace(name="main"), SimpleNamespace(
        name="memory",
    )
    factory = AsyncMock(side_effect=[(main_model, None), (memory_model, None)])
    manager, fallback = model_setup(agent_config=config, factory=factory)

    actual = await manager._update_qwenpaw_model()

    kwargs = {
        "agent_config": config,
        "require_image_support": False,
        "resize_images_to_max_bytes": True,
    }
    assert factory.await_args_list == [
        call("default", **kwargs),
        call("default", model_slot_override=slot, **kwargs),
    ]
    fallback.assert_called_once_with(
        [memory_model, main_model],
        fallback_on_any_error=True,
    )
    assert actual is fallback.return_value
    manager._reme.update_component.assert_awaited_once_with(
        "as_llm",
        "default",
        model=actual,
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
    error: Exception,
    model_setup,
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
    manager, _ = model_setup(
        memory_model=slot,
        factory=factory,
    )

    actual_model = await manager._update_qwenpaw_model()

    assert actual_model is main_model
    assert factory.await_count == 2
    manager._reme.update_component.assert_awaited_once_with(
        "as_llm",
        "default",
        model=main_model,
    )


async def test_gemini_without_api_key_falls_back_and_reme_starts(
    monkeypatch,
    model_setup,
):
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
    manager, fallback_factory = model_setup(
        memory_model=slot,
        factory=factory,
    )

    await manager.start()

    assert factory.await_count == 2
    fallback_factory.assert_not_called()
    manager._reme.update_component.assert_awaited_once_with(
        "as_llm",
        "default",
        model=main_model,
    )
    manager._reme.start.assert_awaited_once_with()


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
    model_setup,
):
    """Only confirmed image-capable main models can receive memory images."""
    main_model = SimpleNamespace(name="main")
    memory_model = SimpleNamespace(name="memory")
    factory = AsyncMock(side_effect=[(main_model, None), (memory_model, None)])
    manager, fallback_factory = model_setup(
        memory_model=ModelSlotConfig(provider_id="custom", model="vision"),
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

    actual_model = await manager._update_qwenpaw_model(
        require_image_support=True,
    )

    for factory_call in factory.await_args_list:
        assert factory_call.kwargs["require_image_support"] is True
        assert factory_call.kwargs["resize_images_to_max_bytes"] is True
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
