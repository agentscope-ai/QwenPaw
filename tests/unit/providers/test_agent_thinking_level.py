# -*- coding: utf-8 -*-
# White-box assertions and pytest fixture parameters are intentional.
# pylint: disable=protected-access
"""Model-card capabilities determine legal provider wire settings."""

from unittest.mock import AsyncMock

import pytest

from qwenpaw.hub.model_service.protocol import upstream_payload
from qwenpaw.providers.adapters.wire_protocol import WireProtocol

from qwenpaw.providers.model_info import ModelInfo
from qwenpaw.providers.provider import agent_thinking_level
from qwenpaw.providers.provider_catalog import (
    PROVIDER_ANTHROPIC,
    PROVIDER_DASHSCOPE,
    PROVIDER_GEMINI,
    PROVIDER_OPENAI,
    PROVIDER_OPENAI_RESPONSE,
)
from qwenpaw.providers.thinking import (
    ThinkingControl,
    ThinkingPreference,
    resolve_thinking,
)


@pytest.mark.parametrize(
    f"provider,model,level,budget,expected",
    [
        (
            PROVIDER_OPENAI,
            f"gpt-5.2",
            f"high",
            None,
            {f"reasoning_effort": f"high"},
        ),
        (
            PROVIDER_OPENAI,
            f"gpt-5.2",
            f"off",
            None,
            {f"reasoning_effort": f"none"},
        ),
        (
            PROVIDER_OPENAI_RESPONSE,
            f"gpt-5.2",
            f"xhigh",
            None,
            {f"reasoning": {f"effort": f"xhigh"}},
        ),
        (
            PROVIDER_DASHSCOPE,
            f"qwen3.8-max",
            f"budget",
            12345,
            {f"thinking_enable": True, f"thinking_budget": 12345},
        ),
        (
            PROVIDER_GEMINI,
            f"gemini-2.5-flash",
            f"off",
            None,
            {f"thinking_config": {f"thinking_budget": 0}},
        ),
        (
            PROVIDER_GEMINI,
            f"gemini-3-flash-preview",
            f"minimal",
            None,
            {f"thinking_config": {f"thinking_level": f"minimal"}},
        ),
        (
            PROVIDER_ANTHROPIC,
            f"claude-sonnet-4-6",
            f"high",
            None,
            {
                f"thinking": {f"type": f"adaptive"},
                f"output_config": {f"effort": f"high"},
                f"thinking_enable": False,
            },
        ),
        (
            PROVIDER_ANTHROPIC,
            f"claude-sonnet-4-5",
            f"budget",
            4097,
            {f"thinking_enable": True, f"thinking_budget": 4097},
        ),
    ],
)
def test_provider_wire_control(provider, model, level, budget, expected):
    provider = provider.model_copy(deep=True)
    with agent_thinking_level(level, budget):
        result = provider.get_effective_generate_kwargs(model)
    for key, value in expected.items():
        assert result[key] == value


@pytest.mark.parametrize(f"provider", [PROVIDER_OPENAI, PROVIDER_DASHSCOPE])
def test_unknown_card_does_not_guess_support(provider):
    provider = provider.model_copy(deep=True)
    provider.extra_models.append(ModelInfo(id=f"unknown", name=f"Unknown"))
    assert not provider.supports_agent_thinking(f"unknown")
    with agent_thinking_level(f"high"):
        assert provider.get_effective_generate_kwargs(f"unknown") == {}


def test_unavailable_off_preserves_model_defaults():
    provider = PROVIDER_OPENAI.model_copy(deep=True)
    assert not provider.thinking_control(f"o3").supports_off
    assert provider.get_agent_thinking_kwargs(f"o3", f"off") == {}


def test_context_does_not_leak_between_constructions():
    provider = PROVIDER_DASHSCOPE.model_copy(deep=True)
    before = provider.get_effective_generate_kwargs(f"qwen3.8-max")
    with agent_thinking_level(f"budget", 1234):
        assert (
            provider.get_effective_generate_kwargs(
                f"qwen3.8-max",
            )[f"thinking_budget"]
            == 1234
        )
    assert provider.get_effective_generate_kwargs(f"qwen3.8-max") == before


def test_numeric_budget_is_not_guessed_as_effort():
    control = ThinkingControl(kind=f"effort", efforts=[f"low", f"high"])
    effective, reason = resolve_thinking(
        ThinkingPreference(level=f"budget", budget_tokens=1234),
        control,
    )
    assert effective.level == f"inherit"
    assert reason == f"incompatible_control"


def test_fallback_budget_is_clamped_without_mutating_preference():
    preference = ThinkingPreference(level=f"budget", budget_tokens=12000)
    control = ThinkingControl(kind=f"budget", budget_min=1024, budget_max=8192)
    effective, reason = resolve_thinking(preference, control)
    assert effective.budget_tokens == 8192
    assert preference.budget_tokens == 12000
    assert reason == f"adapted"


@pytest.mark.parametrize(
    f"value",
    [
        {f"level": f"budget"},
        {f"level": f"high", f"budget_tokens": 1234},
        {f"level": f"budget", f"budget_tokens": 0},
    ],
)
def test_invalid_preference_rejected(value):
    with pytest.raises(ValueError):
        ThinkingPreference.model_validate(value)


def test_hub_native_protocols_keep_thinking_and_bound_budget():
    model = {
        f"upstream_model": f"claude-sonnet-4-5",
        f"output_limit_field": f"max_tokens",
    }
    connection = {
        f"provider_id": f"anthropic",
        f"base_url": f"https://api.anthropic.com",
        f"protocol": f"anthropic",
    }
    body = {
        f"messages": [{f"role": f"user", f"content": f"Hello"}],
        f"hub_thinking_level": f"budget",
        f"hub_thinking_budget": 12000,
    }
    payload = upstream_payload(body, model, 8192, connection)
    wire = WireProtocol(f"anthropic").request(payload)
    assert wire[f"thinking"] == {
        f"type": f"enabled",
        f"budget_tokens": 8191,
    }
    assert f"hub_thinking_budget" not in wire
    assert wire[f"max_tokens"] == 8192


def test_session_override_preserves_shared_provider_kwargs():
    provider = PROVIDER_DASHSCOPE.model_copy(deep=True)
    provider.generate_kwargs = {
        f"extra_body": {
            f"thinking_budget": 8000,
            f"unrelated": True,
        },
    }
    with agent_thinking_level(f"budget", 1234):
        result = provider.get_effective_generate_kwargs(f"qwen3.8-max")
    assert result[f"thinking_budget"] == 1234
    assert provider.generate_kwargs[f"extra_body"][f"thinking_budget"] == 8000
    assert result[f"extra_body"][f"unrelated"] is True


@pytest.mark.parametrize(
    f"model,kind,maximum,efforts,off",
    [
        (f"qwen3.8-max-0902", f"budget", 262144, [], True),
        (f"qwen3.8-flash", f"budget", 262144, [], True),
        (f"deepseek-v4-flash", f"effort", None, [f"high", f"max"], True),
        (
            f"deepseek-v4.1-flash",
            f"effort",
            None,
            [f"low", f"high", f"max"],
            True,
        ),
        (
            f"deepseek-v4-pro-0813",
            f"effort",
            None,
            [f"low", f"high", f"max"],
            True,
        ),
        (
            f"glm-5.3",
            f"effort",
            None,
            [f"low", f"high", f"max"],
            False,
        ),
    ],
)
def test_dashscope_documented_controls(model, kind, maximum, efforts, off):
    provider = PROVIDER_DASHSCOPE.model_copy(deep=True)
    control = provider.thinking_control(model)
    assert control.kind == kind
    assert control.budget_max == maximum
    assert control.efforts == efforts
    assert control.supports_off is off
    if kind == f"effort":
        assert provider.get_agent_thinking_kwargs(model, f"high") == {
            f"thinking_enable": True,
            f"reasoning_effort": f"high",
        }
    else:
        provider.generate_kwargs = {f"reasoning_effort": f"xhigh"}
        with agent_thinking_level(f"budget", 200000):
            kwargs = provider.get_effective_generate_kwargs(model)
        assert kwargs[f"thinking_budget"] == 200000
        assert f"reasoning_effort" not in kwargs


def test_dashscope_model_defaults_do_not_restore_conflicting_effort():
    provider = PROVIDER_DASHSCOPE.model_copy(deep=True)
    model = provider.get_model_info(f"qwen3.8-max")
    model.reasoning_effort = f"high"
    with agent_thinking_level(f"budget", 12000):
        kwargs = provider.get_effective_generate_kwargs(model.id)
        provider._apply_thinking_config(model.id, kwargs)
    assert kwargs[f"thinking_budget"] == 12000
    assert f"reasoning_effort" not in kwargs


@pytest.mark.asyncio
@pytest.mark.parametrize(
    f"model,level,budget,body,effort",
    [
        (
            f"qwen3.8-max-0902",
            f"budget",
            200000,
            {f"enable_thinking": True, f"thinking_budget": 200000},
            None,
        ),
        (
            f"deepseek-v4.1-flash",
            f"low",
            None,
            {f"enable_thinking": True},
            f"low",
        ),
        (
            f"deepseek-v4.1-flash",
            f"off",
            None,
            {f"enable_thinking": False},
            None,
        ),
    ],
)
async def test_dashscope_wire_request(
    monkeypatch,
    model,
    level,
    budget,
    body,
    effort,
):
    provider = PROVIDER_DASHSCOPE.model_copy(deep=True)
    provider.api_key = f"test-only"
    with agent_thinking_level(level, budget):
        client = provider.get_chat_model_instance(model)
    send = AsyncMock(side_effect=RuntimeError(f"captured"))
    monkeypatch.setattr(client.client.chat.completions, f"create", send)
    with pytest.raises(RuntimeError, match=f"captured"):
        await client._call_api(model, [])
    request = send.call_args.kwargs
    assert request[f"extra_body"] == body
    assert request.get(f"reasoning_effort") == effort
