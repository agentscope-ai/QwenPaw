# -*- coding: utf-8 -*-
"""Providers without bundled cards retain explicit configuration."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.hub.model_service.provider_setup import provider_presets
from qwenpaw.providers.model_info import ModelInfo
from qwenpaw.providers.openai_provider import OpenAIProvider
from qwenpaw.providers.provider import agent_thinking_level
from qwenpaw.providers.provider_catalog import PROVIDER_AGENTSCOPE_PLATFORM
from qwenpaw.providers.provider_model_state import (
    restore_model_state,
    serialize_model_state,
)
from qwenpaw.providers.thinking import ThinkingControl


async def test_platform_discovers_cardless_models(monkeypatch):
    provider = PROVIDER_AGENTSCOPE_PLATFORM.model_copy(deep=True)
    client = SimpleNamespace(
        models=SimpleNamespace(
            list=AsyncMock(
                return_value=SimpleNamespace(
                    data=[SimpleNamespace(id=f"private-model")],
                )
            )
        ),
        close=AsyncMock(),
    )
    monkeypatch.setattr(type(provider), f"_client", lambda *a, **k: client)
    models = await provider.fetch_models()
    assert [model.id for model in models] == [f"private-model"]
    assert provider.models == []
    assert provider.thinking_control(f"private-model").kind == f"unknown"
    client.close.assert_awaited_once()
    preset = next(
        item for item in provider_presets() if item[f"id"] == provider.id
    )
    assert preset[f"protocol"] == f"chat"
    assert preset[f"api_key_url"] == (
        f"https://platform.agentscope.io/model-calls"
    )


def test_unknown_card_preserves_manual_request_configuration():
    provider = OpenAIProvider(
        id=f"plugin-service",
        name=f"Plugin service",
        models=[
            ModelInfo(
                id=f"private-model",
                name=f"Private model",
                generate_kwargs={f"extra_body": {f"vendor_option": 123}},
            )
        ],
    )
    assert provider.thinking_control(f"private-model").kind == f"unknown"
    assert not provider.supports_agent_thinking(f"private-model")
    with agent_thinking_level(f"high"):
        assert provider.get_effective_generate_kwargs(f"private-model")[
            f"extra_body"
        ] == {f"vendor_option": 123}


def test_manual_thinking_declaration_persists_and_resets():
    model = ModelInfo(id=f"private-model", name=f"Private model")
    provider = OpenAIProvider(
        id=f"plugin-service",
        name=f"Plugin service",
        models=[model],
        default_thinking_control=ThinkingControl(
            kind=f"effort",
            efforts=[f"low", f"high"],
        ),
    )
    declaration = ThinkingControl(
        kind=f"budget",
        budget_min=100,
        budget_max=8000,
        supports_off=True,
    )
    assert provider.update_model_config(
        model.id,
        {
            f"thinking_control": declaration.model_dump(),
            f"supports_image": True,
        },
    )
    assert provider.get_agent_thinking_kwargs(model.id, f"budget", 1200) == {
        f"extra_body": {
            f"enable_thinking": True,
            f"thinking_budget": 1200,
        },
    }
    state = serialize_model_state(model)
    assert isinstance(state[f"thinking_control"], dict)
    restored = ModelInfo(id=model.id, name=model.name)
    restore_model_state(restored, state)
    assert restored.thinking_control == declaration
    assert restored.supports_image is True
    assert f"thinking_control" in restored.config_overrides
    assert provider.update_model_config(model.id, {f"thinking_control": None})
    assert provider.thinking_control(model.id).kind == f"effort"
    assert f"thinking_control" not in serialize_model_state(model)


def test_catalog_control_is_not_pinned_in_user_state():
    model = ModelInfo(
        id=f"private-model",
        name=f"Private model",
        thinking_control=ThinkingControl(kind=f"unsupported"),
    )
    assert f"thinking_control" not in serialize_model_state(model)


@pytest.mark.parametrize(
    f"kind,fields",
    [
        (f"budget", {f"budget_min": 10, f"budget_max": 1}),
        (f"effort", {f"efforts": []}),
    ],
)
def test_invalid_manual_control_is_rejected(kind, fields):
    with pytest.raises(ValueError):
        ThinkingControl(kind=kind, **fields)
