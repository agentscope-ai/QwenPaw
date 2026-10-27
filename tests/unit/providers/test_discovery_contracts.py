# -*- coding: utf-8 -*-
# White-box assertions and pytest fixture parameters are intentional.
# pylint: disable=unused-argument
"""Exercise each service's listing path through its concrete adapter."""

import httpx
import pytest
from openai import AsyncOpenAI

from qwenpaw.providers.openai_provider import OpenAIProvider
from qwenpaw.providers.provider_catalog import BUILTIN_PROVIDERS
from qwenpaw.providers.provider_manager import ProviderManager

REMOTE_OPENAI_SERVICES = [
    provider.id
    for provider in BUILTIN_PROVIDERS
    if isinstance(provider, OpenAIProvider)
    and provider.support_model_discovery
    and not provider.is_local
    and provider.id != f"dashscope"
]


@pytest.mark.parametrize(f"provider_id", REMOTE_OPENAI_SERVICES)
async def test_service_lists_models_using_its_own_endpoint(
    provider_id,
    isolated_secret_dir,
    monkeypatch,
):
    manager = ProviderManager()
    provider = manager.materialize_discovery_provider(provider_id)
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                f"data": [
                    {
                        f"id": f"qwen-chat",
                        f"name": f"Chat",
                        f"created": 1700000000,
                        f"object": f"model",
                        f"owned_by": f"test",
                        f"context_length": 128000,
                        f"architecture": {
                            f"input_modalities": [f"text", f"image"],
                        },
                        f"pricing": {f"prompt": f"0", f"completion": f"0"},
                        f"supported_parameters": [f"tools"],
                    },
                ],
            },
        )

    client = AsyncOpenAI(
        api_key=f"test-key",
        base_url=provider.base_url,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    monkeypatch.setattr(provider, f"_client", lambda **kwargs: client)
    models = await provider.fetch_models()
    assert [model.id for model in models] == [f"qwen-chat"]
    assert len(requests) == 1
    assert str(requests[0].url) == f"{provider.base_url.rstrip('/')}/models"
    assert requests[0].headers[f"authorization"] == f"Bearer test-key"
    assert client.is_closed()


@pytest.mark.parametrize(f"provider_id", REMOTE_OPENAI_SERVICES)
async def test_service_does_not_turn_failed_requests_into_empty_models(
    provider_id,
    isolated_secret_dir,
    monkeypatch,
):
    provider = ProviderManager().materialize_discovery_provider(provider_id)
    client = AsyncOpenAI(
        api_key=f"test-key",
        base_url=provider.base_url,
        max_retries=0,
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    401,
                    json={
                        f"error": {
                            f"message": f"Invalid API key",
                            f"type": f"authentication",
                        },
                    },
                ),
            ),
        ),
    )
    monkeypatch.setattr(provider, f"_client", lambda **kwargs: client)
    with pytest.raises(Exception) as error:
        await provider.fetch_models()
    assert error.value.status_code == 401
    assert client.is_closed()


@pytest.mark.parametrize(
    f"provider_id",
    [
        provider.id
        for provider in BUILTIN_PROVIDERS
        if provider.discovery_strategy == f"catalog_only"
    ],
)
async def test_catalog_only_services_preserve_cards_and_explain_limit(
    provider_id,
    isolated_secret_dir,
    monkeypatch,
):
    manager = ProviderManager()
    provider = manager.get_provider(provider_id)

    async def unexpected(_self, **kwargs):
        raise AssertionError(f"Do not invent an unsupported list endpoint")

    monkeypatch.setattr(type(provider), f"fetch_models", unexpected)
    result = await manager.discover_provider_models(provider_id)
    assert result.success is False
    assert result.error_kind == f"unsupported"
    assert result.error
    assert result.used_static_fallback
    assert result.models
