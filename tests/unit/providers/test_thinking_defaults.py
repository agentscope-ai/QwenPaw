# -*- coding: utf-8 -*-
"""Model defaults and request preferences must agree with the wire request."""
# pylint: disable=protected-access

from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from qwenpaw.providers.model_info import ModelInfo
from qwenpaw.providers.openai_provider import OpenAIProvider
from qwenpaw.providers.provider import agent_thinking_level
from qwenpaw.providers.thinking import ThinkingControl
from qwenpaw.services.session_thinking import _model_default_thinking


def make_provider(**model_defaults):
    """Use a declared native endpoint without inferring from its name."""
    return OpenAIProvider(
        id="local",
        name="Local",
        base_url="http://localhost:9000/v1",
        api_key="test-only",
        is_custom=True,
        chat_model="OpenAIChatModel",
        extra_models=[
            ModelInfo(
                id="local-model",
                name="Local model",
                thinking_control=ThinkingControl(
                    kind="effort",
                    efforts=["low", "medium", "xhigh"],
                    supports_off=True,
                    wire="native",
                ),
                **model_defaults,
            ),
        ],
    )


async def capture_request(provider, monkeypatch, level="inherit", budget=None):
    """Stop at the SDK transport so no model service is contacted."""
    with agent_thinking_level(level, budget):
        client = provider.get_chat_model_instance("local-model")
    send = AsyncMock(side_effect=RuntimeError("captured"))
    monkeypatch.setattr(client.client.chat.completions, "create", send)
    with pytest.raises(RuntimeError, match="captured"):
        await client._call_api("local-model", [])
    return send.call_args.kwargs


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [None, False, True])
@pytest.mark.parametrize("level", ["off", "low", "medium", "xhigh"])
async def test_explicit_native_wire_is_independent_of_default(
    monkeypatch,
    enabled,
    level,
):
    provider = make_provider(thinking_enabled=enabled)
    request = await capture_request(provider, monkeypatch, level)
    assert request["reasoning_effort"] == ("none" if level == "off" else level)
    assert not request.get("extra_body")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "defaults,expected",
    [
        ({"thinking_enabled": False}, "none"),
        ({"reasoning_effort": "low"}, "low"),
        ({"thinking_enabled": True, "reasoning_effort": "xhigh"}, "xhigh"),
    ],
)
async def test_inherited_model_default_matches_display(
    monkeypatch,
    defaults,
    expected,
):
    provider = make_provider(**defaults)
    preference = _model_default_thinking(provider, "local-model")
    assert preference.level == ("off" if expected == "none" else expected)
    request = await capture_request(provider, monkeypatch)
    assert request["reasoning_effort"] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("level", ["off", "low", "medium", "xhigh"])
async def test_preference_replaces_nested_template_settings(
    monkeypatch,
    level,
):
    provider = make_provider(thinking_enabled=False)
    provider.generate_kwargs = {
        "extra_body": {
            "chat_template_kwargs": {
                "enable_thinking": True,
                "reasoning_effort": "medium",
                "preserve_thinking": True,
            },
            "vendor_option": 123,
        },
    }
    before = provider.model_dump()
    request = await capture_request(provider, monkeypatch, level)
    assert request["reasoning_effort"] == ("none" if level == "off" else level)
    assert request["extra_body"] == {
        "chat_template_kwargs": {"preserve_thinking": True},
        "vendor_option": 123,
    }
    assert provider.model_dump() == before


@pytest.mark.asyncio
async def test_reset_reload_and_request_isolation(monkeypatch):
    provider = make_provider(thinking_enabled=False)
    before = deepcopy(provider.model_dump())
    low = await capture_request(provider, monkeypatch, "low")
    reset = await capture_request(provider, monkeypatch)
    reloaded = OpenAIProvider.model_validate(before)
    after_reload = await capture_request(reloaded, monkeypatch)
    assert low["reasoning_effort"] == "low"
    assert reset["reasoning_effort"] == "none"
    assert after_reload["reasoning_effort"] == "none"
    assert provider.model_dump() == before


@pytest.mark.asyncio
async def test_raw_generation_settings_override_metadata(monkeypatch):
    provider = make_provider(thinking_enabled=False)
    provider.generate_kwargs = {"reasoning_effort": "medium"}
    assert _model_default_thinking(provider, "local-model").level == "medium"
    request = await capture_request(provider, monkeypatch)
    assert request["reasoning_effort"] == "medium"


@pytest.mark.asyncio
async def test_undeclared_default_is_not_invented(monkeypatch):
    provider = make_provider()
    request = await capture_request(provider, monkeypatch)
    assert "reasoning_effort" not in request
    assert not request.get("extra_body")


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_default", [False, True])
@pytest.mark.parametrize("wire", ["compat_effort", "compat_budget"])
async def test_compat_defaults_keep_declared_protocol(
    monkeypatch,
    provider_default,
    wire,
):
    provider = make_provider(thinking_enabled=False)
    model = provider.extra_models[0]
    control = ThinkingControl(
        kind="effort" if wire == "compat_effort" else "budget",
        efforts=["low", "medium", "xhigh"],
        budget_min=1,
        budget_max=8192,
        supports_off=True,
        wire=wire,
    )
    if provider_default:
        model.thinking_control = None
        provider.default_thinking_control = control
    else:
        model.thinking_control = control
    request = await capture_request(provider, monkeypatch)
    assert "reasoning_effort" not in request
    assert request["extra_body"] == (
        {"thinking": {"type": "disabled"}}
        if wire == "compat_effort"
        else {"enable_thinking": False}
    )


@pytest.mark.asyncio
async def test_native_provider_declaration_overrides_legacy_metadata(
    monkeypatch,
):
    provider = make_provider(thinking_enabled=False)
    model = provider.extra_models[0]
    provider.default_thinking_control = model.thinking_control
    model.thinking_control = None
    model.thinking_param_style = "effort"
    request = await capture_request(provider, monkeypatch)
    assert request["reasoning_effort"] == "none"
    assert not request.get("extra_body")


@pytest.mark.asyncio
async def test_model_json_and_template_settings_override_defaults(monkeypatch):
    provider = make_provider(thinking_enabled=False)
    provider.generate_kwargs = {"reasoning_effort": "low"}
    provider.extra_models[0].generate_kwargs = {
        "extra_body": {
            "chat_template_kwargs": {
                "enable_thinking": True,
                "reasoning_effort": "xhigh",
            },
        },
    }
    assert _model_default_thinking(provider, "local-model").level == "xhigh"
    request = await capture_request(provider, monkeypatch)
    assert request["reasoning_effort"] == "xhigh"


@pytest.mark.asyncio
async def test_budget_metadata_is_applied_when_inherited(monkeypatch):
    provider = make_provider(thinking_enabled=True, thinking_budget=2048)
    provider.extra_models[0].thinking_control = ThinkingControl(
        kind="budget",
        budget_min=1,
        budget_max=8192,
        supports_off=True,
        wire="compat_budget",
    )
    preference = _model_default_thinking(provider, "local-model")
    assert preference.level == "budget"
    assert preference.budget_tokens == 2048
    request = await capture_request(provider, monkeypatch)
    assert request["extra_body"] == {
        "enable_thinking": True,
        "thinking_budget": 2048,
    }
