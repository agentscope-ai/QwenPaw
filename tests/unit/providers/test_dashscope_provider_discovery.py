# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

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
