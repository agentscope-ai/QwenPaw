# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access,unused-argument
"""qwen-image mode semantics: generate / edit / translate.

All provider HTTP traffic is stubbed (respx); no real model is ever called.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
import respx

from models import config as model_config
from models.image import dashscope_provider
from models.image.dashscope_provider import DashScopeImageModel
from models.image.openai_provider import OpenAIImageModel
from utils.exceptions import ModelError

_BASE_URL = (
    "https://dashscope.test/api/v1"
    "/services/aigc/multimodal-generation/generation"
)
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


def test_unknown_mode_is_rejected() -> None:
    with pytest.raises(ModelError, match="Unknown image mode"):
        asyncio.run(_dashscope_model().generate("cat", mode="remix"))


def test_edit_mode_requires_one_to_three_references() -> None:
    model = _dashscope_model()
    with pytest.raises(ModelError, match="1-3 reference images"):
        asyncio.run(model.generate("make it red", mode="edit"))
    with pytest.raises(ModelError, match="1-3 reference images"):
        asyncio.run(
            model.generate(
                "make it red",
                mode="edit",
                reference_image_urls=[
                    f"https://cdn.test/{index}.png" for index in range(4)
                ],
            ),
        )


def test_translate_mode_requires_exactly_one_reference() -> None:
    with pytest.raises(ModelError, match="exactly 1 reference image"):
        asyncio.run(_dashscope_model().generate("translate", mode="translate"))


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


def _translate_success_payload(image_url: str) -> dict:
    return {
        "output": {"task_status": "SUCCEEDED", "image_url": image_url},
        "request_id": "req-1",
    }


@respx.mock
def test_translate_submits_async_task_and_downloads_result(
    monkeypatch,
) -> None:
    monkeypatch.delenv("IMAGE_TRANSLATE_MODEL_NAME", raising=False)
    submit_route = respx.post(_TRANSLATE_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "output": {"task_id": "task-mt-1", "task_status": "PENDING"},
            },
        ),
    )
    respx.get("https://dashscope.test/api/v1/tasks/task-mt-1").mock(
        return_value=httpx.Response(
            200,
            json=_translate_success_payload("https://oss.test/translated.png"),
        ),
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
    token = model_config.set_request_tool_configs({})
    try:
        result = asyncio.run(
            _dashscope_model().generate(
                "translate the poster",
                mode="translate",
                reference_image_urls=["https://cdn.test/poster.png"],
                source_lang="zh",
                target_lang="en",
            ),
        )
    finally:
        model_config.reset_request_tool_configs(token)

    assert result == "/generated/translated.png"
    assert downloaded == ["https://oss.test/translated.png"]
    request = submit_route.calls.last.request
    assert request.headers["X-DashScope-Async"] == "enable"
    assert request.headers["Authorization"] == "Bearer sk-test"
    import json

    payload = json.loads(request.content)
    assert payload == {
        "model": "qwen-mt-image",
        "input": {
            "image_url": "https://cdn.test/poster.png",
            "source_lang": "zh",
            "target_lang": "en",
            "ext": {"config": {"imageSegment": False}},
        },
    }


@respx.mock
def test_translate_polls_until_succeeded(monkeypatch) -> None:
    monkeypatch.delenv("IMAGE_TRANSLATE_MODEL_NAME", raising=False)
    monkeypatch.setattr(
        dashscope_provider,
        "_TRANSLATE_POLL_INTERVAL_SECONDS",
        0.0,
    )
    respx.post(_TRANSLATE_URL).mock(
        return_value=httpx.Response(
            200,
            json={"output": {"task_id": "task-mt-2"}},
        ),
    )
    respx.get("https://dashscope.test/api/v1/tasks/task-mt-2").mock(
        side_effect=[
            httpx.Response(
                200,
                json={"output": {"task_status": "RUNNING"}},
            ),
            httpx.Response(
                200,
                json=_translate_success_payload("https://oss.test/late.png"),
            ),
        ],
    )

    async def fake_download(url: str, model_name: str) -> str:
        return "/generated/late.png"

    monkeypatch.setattr(
        dashscope_provider,
        "download_remote_image",
        fake_download,
    )
    token = model_config.set_request_tool_configs({})
    try:
        result = asyncio.run(
            _dashscope_model().generate(
                "translate",
                mode="translate",
                reference_image_urls=["https://cdn.test/poster.png"],
            ),
        )
    finally:
        model_config.reset_request_tool_configs(token)
    assert result == "/generated/late.png"


@respx.mock
def test_translate_failure_surfaces_provider_message(monkeypatch) -> None:
    monkeypatch.delenv("IMAGE_TRANSLATE_MODEL_NAME", raising=False)
    respx.post(_TRANSLATE_URL).mock(
        return_value=httpx.Response(
            200,
            json={"output": {"task_id": "task-mt-3"}},
        ),
    )
    respx.get("https://dashscope.test/api/v1/tasks/task-mt-3").mock(
        return_value=httpx.Response(
            200,
            json={
                "output": {
                    "task_status": "FAILED",
                    "code": "InvalidParameter",
                    "message": "unsupported language pair",
                },
            },
        ),
    )
    token = model_config.set_request_tool_configs({})
    try:
        with pytest.raises(ModelError, match="unsupported language pair"):
            asyncio.run(
                _dashscope_model().generate(
                    "translate",
                    mode="translate",
                    reference_image_urls=["https://cdn.test/poster.png"],
                ),
            )
    finally:
        model_config.reset_request_tool_configs(token)


def test_translate_defaults_to_auto_and_english(monkeypatch) -> None:
    captured: dict = {}

    async def fake_translate(
        self,
        image_url: str,
        *,
        source_lang: str,
        target_lang: str,
    ) -> str:
        captured["image_url"] = image_url
        captured["source_lang"] = source_lang
        captured["target_lang"] = target_lang
        return "/generated/x.png"

    monkeypatch.setattr(DashScopeImageModel, "_translate", fake_translate)
    asyncio.run(
        _dashscope_model().generate(
            "translate",
            mode="translate",
            reference_image_urls=["https://cdn.test/poster.png"],
        ),
    )
    assert captured == {
        "image_url": "https://cdn.test/poster.png",
        "source_lang": "auto",
        "target_lang": "en",
    }


def test_translate_model_name_prefers_configured_override(
    monkeypatch,
) -> None:
    monkeypatch.delenv("IMAGE_TRANSLATE_MODEL_NAME", raising=False)
    monkeypatch.delenv("CREATOR_DATA_ROOT", raising=False)
    monkeypatch.delenv("CREATOR_MODEL_CONFIG_PATH", raising=False)
    token = model_config.set_request_tool_configs({})
    try:
        assert model_config.get_image_translate_model_name() == "qwen-mt-image"
    finally:
        model_config.reset_request_tool_configs(token)
    token = model_config.set_request_tool_configs(
        {"creator_image_model": {"translate_model": "qwen-mt-image-v2"}},
    )
    try:
        assert (
            model_config.get_image_translate_model_name() == "qwen-mt-image-v2"
        )
    finally:
        model_config.reset_request_tool_configs(token)
