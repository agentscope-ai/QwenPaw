# -*- coding: utf-8 -*-
"""Tests for ModelScope model catalog filtering."""

# pylint: disable=protected-access

from qwenpaw.providers.modelscope_provider import ModelScopeProvider
from qwenpaw.providers.provider import ModelInfo


def test_modelscope_filters_non_chat_catalog_entries() -> None:
    assert ModelScopeProvider._is_non_chat_model("Qwen/Qwen-Image-Edit")
    assert ModelScopeProvider._is_non_chat_model("Paddle/ERNIE-4.5-21B-PT")
    assert ModelScopeProvider._is_non_chat_model("OpenCompass/CompassJudger")
    assert ModelScopeProvider._is_non_chat_model(
        "XGenerationLab/XiYanSQL-Qwen",
    )
    assert not ModelScopeProvider._is_non_chat_model("Qwen/Qwen3-VL-235B")
    assert not ModelScopeProvider._is_non_chat_model("Shanghai/Intern-S1")


async def test_modelscope_fetch_models_filters_catalog(monkeypatch) -> None:
    provider = ModelScopeProvider(
        id="modelscope",
        name="ModelScope",
        base_url="https://api-inference.modelscope.cn/v1",
        api_key="ms-test",
    )

    async def fetch_models(_self, timeout=5):
        _ = timeout
        return [
            ModelInfo(id="Qwen/Qwen3-VL-235B", name="VL"),
            ModelInfo(id="Qwen/Qwen-Image-Edit", name="Image"),
            ModelInfo(id="Paddle/ERNIE-4.5-21B-PT", name="PT"),
        ]

    monkeypatch.setattr(
        "qwenpaw.providers.openai_provider.OpenAIProvider.fetch_models",
        fetch_models,
    )
    models = await provider.fetch_models()
    assert [model.id for model in models] == ["Qwen/Qwen3-VL-235B"]
