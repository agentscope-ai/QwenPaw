# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Model metadata resolution runs outside the shared Hub event loop."""

import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from qwenpaw.hub.model_service import gateway, provider_setup
from qwenpaw.providers.provider_catalog import PROVIDER_OPENAI
from qwenpaw.providers.model_info import ModelInfo


@pytest.mark.asyncio
async def test_gateway_prepares_catalog_and_thinking_on_worker():
    loop_thread = threading.get_ident()
    original = gateway.ModelGateway._prepare
    calls = []

    def prepare(*args):
        calls.append(threading.get_ident())
        assert calls[-1] != loop_thread
        return original(*args)

    model = {
        f"upstream_model": f"gpt-5.2",
        f"output_limit_field": f"max_tokens",
    }
    connection = {
        f"id": f"openai",
        f"name": f"OpenAI",
        f"protocol": f"chat",
        f"base_url": f"https://api.openai.com/v1",
    }
    attempt = SimpleNamespace(
        request_id=f"r",
        reserve=AsyncMock(return_value=(None, model, connection, 8192)),
        close=AsyncMock(),
    )
    response = httpx.Response(
        200,
        json={
            f"id": f"test",
            f"choices": [],
            f"usage": {f"prompt_tokens": 1, f"completion_tokens": 1},
        },
    )
    instance = gateway.ModelGateway(SimpleNamespace(store=None), None)
    with (
        patch.object(gateway, f"GatewayRequest", return_value=attempt),
        patch.object(gateway.ModelGateway, f"_prepare", side_effect=prepare),
        patch.object(instance, f"_open", AsyncMock(return_value=response)),
    ):
        result = await instance.call(
            {f"user_id": f"u"},
            {
                f"model": f"org-id",
                f"messages": [],
                f"hub_thinking_level": f"high",
            },
        )
    assert result.status_code == 200
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_discovery_merges_capabilities_on_worker():
    loop_thread = threading.get_ident()
    provider = PROVIDER_OPENAI.configuration_snapshot()
    original = provider_setup._merge_discovery
    calls = []

    def merge(*args):
        calls.append(threading.get_ident())
        assert calls[-1] != loop_thread
        return original(*args)

    with (
        patch.object(
            provider_setup,
            f"_discovery_provider",
            return_value=provider,
        ),
        patch.object(
            type(provider),
            f"fetch_models",
            AsyncMock(
                return_value=[
                    ModelInfo(id=f"gpt-5.2", name=f"GPT"),
                ],
            ),
        ),
        patch.object(provider_setup, f"_merge_discovery", side_effect=merge),
    ):
        result = await provider_setup.discover_models(None, f"openai")
    assert result
    assert len(calls) == 1
