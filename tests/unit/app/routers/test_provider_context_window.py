# -*- coding: utf-8 -*-
"""Tests for active-model context-window metadata."""

from types import SimpleNamespace

from qwenpaw.app.routers.providers import (
    ModelConfigRequest,
    _active_models_info,
    configure_model,
)
from qwenpaw.config.config import ModelSlotConfig


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
        body=ModelConfigRequest(max_tokens=4096),
    )

    assert captured == {
        "provider_id": "openai",
        "model_id": "gpt-test",
        "config": {"max_tokens": 4096},
    }
