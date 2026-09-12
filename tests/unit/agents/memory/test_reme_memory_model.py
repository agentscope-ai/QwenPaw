# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for the configurable memory-writing model slot."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

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
) -> None:
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


def _build_manager() -> ReMeLightMemoryManager:
    manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    manager.agent_id = "default"
    manager._reme = SimpleNamespace(update_component=AsyncMock())
    return manager


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
    injected = SimpleNamespace(name="injected")
    factory = AsyncMock(return_value=(injected, None))
    _patch_deps(
        monkeypatch,
        agent_config=_agent_config(
            memory_model=memory_model,
            active_model=active_model,
        ),
        factory=factory,
        global_model=global_model,
    )
    manager = _build_manager()

    await manager._update_qwenpaw_model()

    if expected_override is None:
        factory.assert_awaited_once_with("default")
    else:
        factory.assert_awaited_once_with(
            "default",
            model_slot_override=expected_override,
        )
    manager._reme.update_component.assert_awaited_once_with(
        "as_llm",
        "default",
        model=injected,
    )


async def test_update_model_unavailable_slot_falls_back_to_main_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A broken memory_model must degrade to the agent's main model."""
    slot = ModelSlotConfig(provider_id="missing", model="qwenpaw-flash-4b")
    main_model = SimpleNamespace(name="main")
    factory = AsyncMock(
        side_effect=[
            ProviderError("Provider 'missing' not found."),
            (main_model, None),
        ],
    )
    _patch_deps(
        monkeypatch,
        agent_config=_agent_config(memory_model=slot),
        factory=factory,
    )
    manager = _build_manager()

    await manager._update_qwenpaw_model()

    assert factory.await_count == 2
    assert factory.await_args_list[1].args == ("default",)
    assert "model_slot_override" not in factory.await_args_list[1].kwargs
    manager._reme.update_component.assert_awaited_once_with(
        "as_llm",
        "default",
        model=main_model,
    )
