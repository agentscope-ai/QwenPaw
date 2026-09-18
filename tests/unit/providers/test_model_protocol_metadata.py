# -*- coding: utf-8 -*-
"""Protocol-specific discovery and output budget regression cases."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.providers.anthropic_provider import AnthropicProvider
from qwenpaw.providers.openai_provider import OpenAIProvider
from qwenpaw.providers.openrouter_provider import OpenRouterProvider
from qwenpaw.providers.model_info import ModelInfo


def test_anthropic_reads_native_model_capability_fields():
    rows = SimpleNamespace(
        data=[
            SimpleNamespace(
                id=f"claude-model",
                display_name=f"Claude",
                max_input_tokens=200_000,
                max_tokens=32_000,
            )
        ]
    )
    model = AnthropicProvider._normalize_models_payload(rows)[0]
    assert model.max_input_length_auto_detected == 200_000
    assert model.input_token_limit == 200_000
    assert model.input_token_limit_source == f"api"
    assert model.max_output_length == 32_000
    assert model.max_output_length_source == f"api"


def test_openai_id_only_does_not_invent_capabilities():
    model = OpenAIProvider._normalize_models_payload(
        SimpleNamespace(
            data=[
                SimpleNamespace(id=f"new-model", owned_by=f"openai"),
            ]
        )
    )[0]
    assert model.max_input_length_auto_detected is None
    assert model.max_output_length is None
    assert model.billing == f"unknown"


def test_openrouter_reads_service_output_capacity():
    model = OpenRouterProvider._normalize_models_payload(
        SimpleNamespace(
            data=[
                SimpleNamespace(
                    id=f"vendor/model",
                    context_length=64_000,
                    top_provider={f"max_completion_tokens": 4096},
                    pricing={f"prompt": f"0", f"completion": f"0"},
                ),
            ]
        )
    )[0]
    assert model.max_input_length_auto_detected == 64_000
    assert model.max_output_length == 4096
    assert model.billing == f"free"


def test_anthropic_automatic_budget_respects_known_output_capacity():
    provider = AnthropicProvider(
        id=f"custom",
        name=f"Custom",
        is_custom=True,
        api_key=f"test-key",
        base_url=f"https://gateway.example",
        extra_models=[
            ModelInfo(
                id=f"small-model",
                name=f"Small",
                max_output_length=4096,
                max_output_length_source=f"api",
            )
        ],
    )
    model = provider.get_chat_model_instance(f"small-model")
    assert model.parameters.max_tokens == 4096
    assert provider.extra_models[0].generate_kwargs == {}
    provider.generate_kwargs = {f"max_tokens": 8192}
    with pytest.raises(ValueError, match=f"capacity"):
        provider.get_chat_model_instance(f"small-model")


def test_anthropic_protocol_does_not_assign_claude_thinking_to_qwen():
    provider = AnthropicProvider(
        id=f"gateway",
        name=f"Gateway",
        is_custom=True,
        base_url=f"https://gateway.example",
        extra_models=[ModelInfo(id=f"qwen3.8-max", name=f"Qwen")],
    )
    assert not provider.supports_agent_thinking(f"qwen3.8-max")
    assert provider.get_agent_thinking_kwargs(f"qwen3.8-max", f"high") == {}


async def test_anthropic_discovery_consumes_all_pages(monkeypatch):
    class Pages:
        async def __aiter__(self):
            for model_id in (f"first-page", f"second-page"):
                yield SimpleNamespace(id=model_id)

    client = SimpleNamespace(
        models=SimpleNamespace(list=AsyncMock(return_value=Pages())),
        close=AsyncMock(),
    )
    monkeypatch.setattr(AnthropicProvider, f"_client", lambda *a, **k: client)
    provider = AnthropicProvider(id=f"test", name=f"Test")
    models = await provider.fetch_models()
    assert [model.id for model in models] == [f"first-page", f"second-page"]
    client.close.assert_awaited_once()
