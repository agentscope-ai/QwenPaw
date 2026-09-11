# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access,unused-argument
"""qwen-image mode semantics: generate / edit / translate.

All provider HTTP traffic is stubbed (respx); no real model is ever called.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager

import httpx
import pytest
import respx

from models import config as model_config
from models.image import dashscope_provider
from models.image.dashscope_provider import DashScopeImageModel
from models.image.openai_provider import OpenAIImageModel
from utils.exceptions import ModelError

_BASE_URL = "https://dashscope.test/api/v1/services/aigc/multimodal-generation/generation"
_TRANSLATE_URL = (
    "https://dashscope.test/api/v1/services/aigc/image2image/image-synthesis"
)


def _dashscope_model() -> DashScopeImageModel:
    return DashScopeImageModel(
        model_name="qwen-image-2.0-pro",
        api_key="sk-test",
        base_url=_BASE_URL,
        timeout=30,
    )


def _openai_model() -> OpenAIImageModel:
    return OpenAIImageModel(
        model_name="gpt-image-2",
        api_key="sk-test",
        base_url="https://openai.test/v1",
        quality="low",
        timeout=30,
    )


@contextmanager
def _tool_configs(configs: dict | None = None):
    token = model_config.set_request_tool_configs(configs or {})
    try:
        yield
    finally:
        model_config.reset_request_tool_configs(token)


def _run_translate(**kwargs) -> str:
    with _tool_configs():
        return asyncio.run(
            _dashscope_model().generate(
                "translate",
                mode="translate",
                reference_image_urls=["https://cdn.test/poster.png"],
                **kwargs,
            ),
        )


def test_unknown_mode_is_rejected() -> None:
    with pytest.raises(ModelError, match="Unknown image mode"):
        asyncio.run(_dashscope_model().generate("cat", mode="remix"))


def test_mode_reference_count_validation() -> None:
    model = _dashscope_model()
    with pytest.raises(ModelError, match="1-3 reference images"):
        asyncio.run(model.generate("make it red", mode="edit"))
    with pytest.raises(ModelError, match="exactly 1 reference image"):
        asyncio.run(model.generate("translate", mode="translate"))


def test_openai_provider_rejects_edit_and_translate() -> None:
    model = _openai_model()
    for mode in ("edit", "translate"):
        with pytest.raises(ModelError, match="does not support"):
            asyncio.run(
                model.generate(
                    "poster",
                    mode=mode,
                    reference_image_urls=["https://cdn.test/poster.png"],
                ),
            )


def test_edit_body_keeps_images_first_and_disables_watermark() -> None:
    body = asyncio.run(
        _dashscope_model()._build_body(
            "convert to watercolor style",
            "16:9",
            ["https://cdn.test/a.png", "https://cdn.test/b.png"],
        ),
    )
    assert body["model"] == "qwen-image-2.0-pro"
    assert body["input"]["messages"][0]["content"] == [
        {"image": "https://cdn.test/a.png"},
        {"image": "https://cdn.test/b.png"},
        {"text": "convert to watercolor style"},
    ]
    assert body["parameters"] == {"size": "1664*928", "watermark": False}


@respx.mock
def test_translate_submits_async_task_polls_and_downloads_result(
    monkeypatch,
) -> None:
    monkeypatch.delenv("IMAGE_TRANSLATE_MODEL_NAME", raising=False)
    monkeypatch.setattr(
        dashscope_provider,
        "_TRANSLATE_POLL_INTERVAL_SECONDS",
        0.0,
    )
    submit_route = respx.post(_TRANSLATE_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "output": {"task_id": "task-mt-1", "task_status": "PENDING"},
            },
        ),
    )
    respx.get("https://dashscope.test/api/v1/tasks/task-mt-1").mock(
        side_effect=[
            httpx.Response(200, json={"output": {"task_status": "RUNNING"}}),
            httpx.Response(
                200,
                json={
                    "output": {
                        "task_status": "SUCCEEDED",
                        "image_url": "https://oss.test/translated.png",
                    },
                    "request_id": "req-1",
                },
            ),
        ],
    )
    downloaded: list[str] = []

    async def fake_download(url: str, model_name: str) -> str:
        downloaded.append(url)
        assert model_name == "qwen-mt-image"
        return "/generated/translated.png"

    monkeypatch.setattr(
        dashscope_provider,
        "download_remote_image",
        fake_download,
    )

    result = _run_translate(source_lang="zh", target_lang="en")

    assert result == {"url": "/generated/translated.png", "source_url": ""}
    assert downloaded == ["https://oss.test/translated.png"]
    request = submit_route.calls.last.request
    assert request.headers["X-DashScope-Async"] == "enable"
    assert request.headers["Authorization"] == "Bearer sk-test"
    assert json.loads(request.content) == {
        "model": "qwen-mt-image",
        "input": {
            "image_url": "https://cdn.test/poster.png",
            "source_lang": "zh",
            "target_lang": "en",
            "ext": {"config": {"imageSegment": False}},
        },
    }
