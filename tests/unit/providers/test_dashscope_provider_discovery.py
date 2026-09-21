# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

import httpx
import pytest

from qwenpaw.providers import dashscope_discovery
from qwenpaw.providers.dashscope_provider import DashScopeProvider
from qwenpaw.providers.provider import ModelInfo


def test_dashscope_excludes_non_chat_catalog_entries() -> None:
    assert DashScopeProvider._is_non_chat_model("qwen-image-plus")
    assert DashScopeProvider._is_non_chat_model("fun-asr-realtime")
    assert DashScopeProvider._is_non_chat_model("MiniMax/speech-2.8-turbo")
    assert DashScopeProvider._is_non_chat_model("test-sre-gpu-auto-handle")
    assert not DashScopeProvider._is_non_chat_model("MiniMax/MiniMax-M3")
    assert not DashScopeProvider._is_non_chat_model("qwen3-max")


async def test_dashscope_fetch_models_filters_non_chat_entries(
    monkeypatch,
) -> None:
    provider = DashScopeProvider(
        id="dashscope",
        name="DashScope",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key="sk-test",
    )

    async def unavailable(*args):
        response = httpx.Response(404, request=httpx.Request(f"GET", args[0]))
        response.raise_for_status()

    monkeypatch.setattr(
        f"qwenpaw.providers.dashscope_provider.fetch_directory",
        unavailable,
    )

    async def fetch_models(_self, timeout=5):
        _ = timeout
        return [
            ModelInfo(id="qwen3-max", name="Qwen3 Max"),
            ModelInfo(id="qwen-image-plus", name="Qwen Image Plus"),
            ModelInfo(id="fun-asr-realtime", name="Fun ASR"),
        ]

    monkeypatch.setattr(
        "qwenpaw.providers.openai_provider.OpenAIProvider.fetch_models",
        fetch_models,
    )

    models = await provider.fetch_models()

    assert [model.id for model in models] == ["qwen3-max"]


async def test_native_directory_paginates_and_reads_capabilities(monkeypatch):
    requests = []

    def respond(request):
        requests.append(request)
        page = int(request.url.params[f"page_no"])
        return httpx.Response(
            200,
            json={
                f"success": True,
                f"output": {
                    f"total": 2,
                    f"models": [
                        {
                            f"model": f"chat-{page}",
                            f"capabilities": [f"TG"],
                            f"features": [f"function-calling"],
                            f"inference_metadata": {
                                f"request_modality": [f"Text", f"Image"],
                            },
                            f"model_info": {
                                f"context_window": 1000000,
                                f"max_output_tokens": 32000,
                            },
                        },
                    ],
                },
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    monkeypatch.setattr(
        dashscope_discovery.httpx,
        f"AsyncClient",
        lambda **kwargs: client,
    )
    cards = await dashscope_discovery.fetch_directory(
        f"https://dashscope.aliyuncs.com/api/v1/models",
        {},
        5,
    )
    assert len(requests) == 2
    assert [card.id for card in cards] == [f"chat-1", f"chat-2"]
    assert cards[0].supports_image is True
    assert cards[0].supports_audio is False
    assert cards[0].supports_tool_calling is True
    assert cards[0].max_input_length_auto_detected == 1000000
    assert cards[0].max_output_length == 32000
    assert client.is_closed


async def test_native_directory_rejects_partial_pagination(monkeypatch):
    def respond(request):
        page = int(request.url.params[f"page_no"])
        return httpx.Response(
            200,
            json={
                f"output": {
                    f"total": 2,
                    f"models": [{f"model": f"first"}] if page == 1 else [],
                },
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    monkeypatch.setattr(
        dashscope_discovery.httpx,
        f"AsyncClient",
        lambda **kwargs: client,
    )
    with pytest.raises(ValueError, match=f"incomplete"):
        await dashscope_discovery.fetch_directory(
            f"https://dashscope.aliyuncs.com/api/v1/models",
            {},
            5,
        )
    assert client.is_closed
