# -*- coding: utf-8 -*-
"""Tests for active-model context-window metadata."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from qwenpaw.app.routers.providers import (
    ModelConfigRequest,
    _active_models_info,
    configure_model,
)
from qwenpaw.config.config import ModelSlotConfig


@pytest.mark.asyncio
async def test_provider_list_exposes_resolved_not_placeholder_window():
    from qwenpaw.providers.provider import ModelInfo
    from qwenpaw.providers.openai_provider import OpenAIProvider

    provider = OpenAIProvider(
        id="openai",
        name="OpenAI",
        models=[ModelInfo(id="gpt-4.1", name="GPT-4.1")],
    )
    info = await provider.get_info()
    assert info.models[0].max_input_length == 131072
    assert info.effective_context_windows[
        "gpt-4.1"
    ] == provider.get_context_size("gpt-4.1")
    assert info.effective_context_windows["gpt-4.1"] > 131072


def test_active_models_info_uses_runtime_context_resolution():
    provider = SimpleNamespace(get_context_size=lambda _model_id: 1_000_000)
    manager = SimpleNamespace(get_provider=lambda _provider_id: provider)
    slot = ModelSlotConfig(provider_id="dashscope", model="qwen3.7-max")

    info = _active_models_info(manager, slot)

    assert info.active_llm == slot
    assert info.effective_max_input_length == 1_000_000


async def test_configure_model_only_forwards_submitted_fields() -> None:
    captured = None

    async def update_model_config(**kwargs):
        nonlocal captured
        captured = kwargs
        return SimpleNamespace()

    manager = SimpleNamespace(update_model_config=update_model_config)

    await configure_model(
        manager=manager,
        provider_id="openai",
        model_id="gpt-test",
        body=ModelConfigRequest(
            generate_kwargs={"max_tokens": 4096},
        ),
    )

    assert captured == {
        "provider_id": "openai",
        "model_id": "gpt-test",
        "config": {"generate_kwargs": {"max_tokens": 4096}},
    }


@pytest.mark.parametrize("value", [0, -1, 1.5, True])
def test_model_config_rejects_invalid_max_tokens(value: object) -> None:
    with pytest.raises(ValidationError, match="max_tokens"):
        ModelConfigRequest(generate_kwargs={"max_tokens": value})


async def test_hub_provider_exposes_effective_context_windows():
    from qwenpaw.providers.hub_managed import ManagedProvider
    from qwenpaw.providers.provider import ModelInfo

    provider = ManagedProvider(
        id="hub-managed",
        name="Hub",
        models=[
            ModelInfo(
                id="organization-model",
                name="Model",
                max_input_length=64000,
                max_input_length_configured=True,
            ),
        ],
    )
    info = await provider.get_info()
    assert info.effective_context_windows == {
        "organization-model": provider.get_context_size("organization-model"),
    }
