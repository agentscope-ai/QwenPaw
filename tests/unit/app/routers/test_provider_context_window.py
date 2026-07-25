# -*- coding: utf-8 -*-
"""Tests for active-model context-window metadata."""

from types import SimpleNamespace

from qwenpaw.app.routers.providers import _active_models_info
from qwenpaw.config.config import ModelSlotConfig


def test_active_models_info_uses_runtime_context_resolution():
    provider = SimpleNamespace(get_context_size=lambda _model_id: 1_000_000)
    manager = SimpleNamespace(get_provider=lambda _provider_id: provider)
    slot = ModelSlotConfig(provider_id="dashscope", model="qwen3.7-max")

    info = _active_models_info(manager, slot)

    assert info.active_llm == slot
    assert info.effective_max_input_length == 1_000_000
