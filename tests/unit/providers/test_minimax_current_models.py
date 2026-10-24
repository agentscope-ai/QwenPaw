# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Current presets, compatibility, and real SDK wire serialization."""

import json
from copy import deepcopy
from unittest.mock import AsyncMock

import anthropic

try:
    from anthropic._base_client import httpx2 as httpx
except ImportError:
    from anthropic._base_client import httpx
import pytest

from qwenpaw.providers.model_catalog import CatalogDocument, load_model_catalog
from qwenpaw.providers.model_info import ModelInfo
from qwenpaw.providers.model_metadata import (
    list_model_templates,
    model_metadata,
    provider_catalog_models,
)
from qwenpaw.providers.provider import agent_thinking_level
from qwenpaw.providers.provider_catalog import (
    BUILTIN_PROVIDERS,
    PROVIDER_MINIMAX,
    PROVIDER_MINIMAX_CN,
    PROVIDER_OPENROUTER,
)
from qwenpaw.providers.provider_discovery import normalize_discovered_models
from qwenpaw.providers.provider_discovery_policy import is_legacy_minimax_text

FLASH = f"MiniMax-M3.1-Flash"
M3 = f"MiniMax-M3"
EFFORTS = [f"low", f"medium", f"high", f"xhigh", f"max"]


def test_current_catalogs_and_templates_keep_legacy_lookup():
    catalog = load_model_catalog()
    for provider in (PROVIDER_MINIMAX, PROVIDER_MINIMAX_CN):
        assert [m.id for m in catalog[provider.id]] == [FLASH, M3]
        for model in catalog[provider.id]:
            assert model.max_input_length == 1_000_000
            assert model.max_output_length == 524288
            assert model.supports_image and model.supports_video
        assert provider.thinking_control(FLASH).efforts == EFFORTS
        assert not provider.thinking_control(FLASH).supports_off
        legacy = model_metadata(
            provider.id,
            provider.base_url,
            f"MiniMax-M2.7",
        )
        assert legacy and legacy[0].model.max_input_length == 204800
    templates = [m[f"model_id"] for m in list_model_templates()]
    assert FLASH in templates
    assert not any(is_legacy_minimax_text(m) for m in templates)
    for provider in BUILTIN_PROVIDERS:
        assert not any(is_legacy_minimax_text(m.id) for m in provider.models)
        assert not any(
            is_legacy_minimax_text(m.id)
            for m in provider_catalog_models(provider.id, provider.base_url)
        )
    assert not PROVIDER_OPENROUTER.models  # Remains API-driven.


@pytest.mark.parametrize(f"custom", [False, True])
def test_discovery_filters_old_text_but_preserves_saved_and_custom_ids(custom):
    provider = PROVIDER_OPENROUTER.model_copy(deep=True)
    provider.is_custom = custom
    legacy = ModelInfo(
        id=f"minimax/minimax-m2.7",
        name=f"Saved",
        source=f"user",
    )
    provider.extra_models = [legacy]
    ids = [
        f"minimax/minimax-m3.1-flash:free",
        f"minimax/minimax-m3",
        f"minimax/minimax-m2.5",
        f"other/custom-model",
        f"minimax/speech-02",
    ]
    rows, api_ids = normalize_discovered_models(
        provider,
        [ModelInfo(id=x, name=x) for x in ids],
        f"2026-10-19",
    )
    assert (f"minimax/minimax-m2.5" in api_ids) is custom
    assert {m.id for m in rows} == api_ids
    assert f"minimax/speech-02" in api_ids
    assert f"other/custom-model" in api_ids
    assert provider.extra_models == [legacy]
    assert provider.get_model_info(legacy.id).id == legacy.id


@pytest.mark.parametrize(f"provider", [PROVIDER_MINIMAX, PROVIDER_MINIMAX_CN])
@pytest.mark.parametrize(f"level", [f"inherit", f"off", *EFFORTS])
@pytest.mark.parametrize(f"stream", [False, True])
async def test_flash_efforts_reach_real_sdk_wire(
    monkeypatch,
    provider,
    level,
    stream,
):
    provider = provider.model_copy(deep=True)
    provider.api_key = f"test-only"
    with agent_thinking_level(level):
        model = provider.get_chat_model_instance(FLASH)
    body = await _capture(monkeypatch, model, FLASH, provider.base_url, stream)
    assert body[f"thinking"] == {f"type": f"adaptive"}
    assert body[f"output_config"] == {
        f"effort": level if level in EFFORTS else f"max",
    }
    assert f"service_tier" not in body
    assert body[f"max_tokens"] == 16384  # Capacity is not a request budget.


@pytest.mark.parametrize(f"provider", [PROVIDER_MINIMAX, PROVIDER_MINIMAX_CN])
@pytest.mark.parametrize(
    f"model_id,overrides,thinking,effort",
    [
        (FLASH, {f"disable_thinking": True}, f"adaptive", f"max"),
        (
            FLASH,
            {f"thinking": {f"type": f"enabled", f"budget_tokens": 1000}},
            f"adaptive",
            f"max",
        ),
        (
            FLASH,
            {
                f"extra_body": {
                    f"thinking": {f"type": f"disabled"},
                    f"output_config": {f"effort": f"none"},
                    f"service_tier": f"priority",
                },
            },
            f"adaptive",
            f"max",
        ),
        (M3, {}, f"disabled", None),
        (
            M3,
            {f"thinking_enable": True, f"thinking_budget": 1000},
            f"adaptive",
            None,
        ),
        (
            M3,
            {
                f"thinking": {f"type": f"enabled", f"budget_tokens": 1000},
                f"output_config": {f"effort": f"high"},
            },
            f"adaptive",
            None,
        ),
        (
            M3,
            {f"thinking": {f"type": f"adaptive"}, f"disable_thinking": True},
            f"disabled",
            None,
        ),
        (
            M3,
            {f"thinking_enable": True, f"thinking": {f"type": f"disabled"}},
            f"disabled",
            None,
        ),
    ],
)
async def test_direct_runtime_normalizes_legacy_controls(
    monkeypatch,
    provider,
    model_id,
    overrides,
    thinking,
    effort,
):
    provider = provider.model_copy(deep=True)
    provider.api_key = f"test-only"
    model = provider.get_chat_model_instance(model_id)
    original = deepcopy(overrides)
    body = await _capture(
        monkeypatch,
        model,
        model_id,
        provider.base_url,
        False,
        overrides,
    )
    assert body.get(f"thinking", {f"type": f"disabled"}) == {
        f"type": thinking,
    }
    assert body.get(f"output_config", {}).get(f"effort") == effort
    assert f"thinking_budget" not in body
    assert f"thinking_enable" not in body
    assert f"disable_thinking" not in body
    assert overrides == original


async def _capture(
    monkeypatch,
    model,
    model_id,
    base_url,
    stream,
    kwargs=None,
):
    """Intercept HTTP after the installed Anthropic SDK serializes the body."""
    captured = []

    def respond(request):
        assert str(request.url) == f"{base_url}/v1/messages"
        captured.append(json.loads(request.content))
        if stream:
            return httpx.Response(
                200,
                headers={f"content-type": f"text/event-stream"},
                content=b"",
            )
        return httpx.Response(
            200,
            json={
                f"id": f"fixture",
                f"type": f"message",
                f"role": f"assistant",
                f"model": model_id,
                f"content": [{f"type": f"text", f"text": f"OK"}],
                f"stop_reason": f"end_turn",
                f"stop_sequence": None,
                f"usage": {f"input_tokens": 1, f"output_tokens": 1},
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond),
    ) as transport:
        async with anthropic.AsyncAnthropic(
            api_key=f"test-only",
            base_url=base_url,
            http_client=transport,
        ) as client:
            monkeypatch.setattr(
                model,
                f"_request_client",
                AsyncMock(return_value=client),
            )
            model.stream = stream
            response = await model._call_api(model_id, [], **(kwargs or {}))
            if stream:
                async for _ in response:
                    pass
    assert len(captured) == 1
    assert captured[0][f"model"] == model_id
    assert captured[0][f"stream"] is stream
    return captured[0]


def test_user_catalog_keeps_explicit_legacy_templates(monkeypatch):
    document = CatalogDocument.model_validate(
        {
            "catalog_version": "user",
            "providers": {
                "saved": {
                    "template_owner": True,
                    "models": [{"id": "MiniMax-M2.7", "name": "Saved model"}],
                },
            },
        },
    )
    monkeypatch.setattr(
        "qwenpaw.providers.model_metadata.catalog_documents",
        lambda *args: [(document, "user")],
    )
    assert list_model_templates()[0]["model_id"] == "MiniMax-M2.7"
    assert provider_catalog_models("saved", "")[0].id == "MiniMax-M2.7"


def test_legacy_and_custom_request_options_are_not_rewritten():
    original = {f"thinking": {f"type": f"enabled", f"budget_tokens": 1000}}
    for model_id in (
        f"MiniMax-M2.7",
        f"custom-saved-model",
        f"claude-sonnet-4-5",
    ):
        assert (
            PROVIDER_MINIMAX._current_model_kwargs(model_id, original)
            == original
        )
