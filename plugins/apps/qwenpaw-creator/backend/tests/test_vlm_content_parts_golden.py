# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long,protected-access,unnecessary-lambda,useless-return

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest

from models import vlm_model

pytestmark = pytest.mark.unit

DASHSCOPE = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def _transport(part, model, base_url):
    coro = vlm_model._transport_local_media_part
    return asyncio.run(coro(part, "vlm-key", model, base_url))


def test_local_media_transport_dashscope_temp_and_data_url_fallback(
    tmp_path,
    monkeypatch,
):
    # Golden: max_frames is accepted but never forwarded; fps survives.
    assert vlm_model.multimodal_media_part(
        "https://cdn.example.com/clip.mp4",
        "video",
        fps=0.5,
        max_frames=12.9,
    ) == {
        "type": "video_url",
        "video_url": {"url": "https://cdn.example.com/clip.mp4"},
        "fps": 0.5,
    }

    image = tmp_path / "reference.png"
    image.write_bytes(b"png")
    observed = {}

    async def fake_upload(path, *, api_key, model_name, media_type):
        observed["call"] = (path, api_key, model_name, media_type)
        return "oss://dashscope-instant/reference.png"

    mc = vlm_model.model_config
    monkeypatch.setattr(mc, "get_vlm_base_url", lambda: DASHSCOPE)
    monkeypatch.setattr(
        vlm_model,
        "upload_local_file_to_dashscope_temp",
        fake_upload,
    )
    part = vlm_model.multimodal_media_part(image.as_uri(), "image")
    transported, uses_temp_oss = _transport(part, "qwen3-vl", DASHSCOPE)
    assert uses_temp_oss is True
    assert transported == {
        "type": "image_url",
        "image_url": {"url": "oss://dashscope-instant/reference.png"},
    }
    expected = (image.resolve(), "vlm-key", "qwen3-vl", "image/png")
    assert observed["call"] == expected

    # Off DashScope the transport inlines a bounded data URL instead.
    off = "https://api.openai.example/v1"
    monkeypatch.setattr(mc, "get_vlm_base_url", lambda: off)
    monkeypatch.setattr(mc, "get_vlm_max_inline_bytes", lambda: 1024)
    transported, uses_temp_oss = _transport(
        part,
        "gpt-vision",
        "https://api.openai.com/v1",
    )
    assert uses_temp_oss is False
    assert transported == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,cG5n"},
    }


def test_chat_completion_preserves_mixed_content_parts_in_request(monkeypatch):
    captured: dict[str, object] = {}
    content = [
        {
            "type": "image_url",
            "image_url": {"url": "https://cdn.example.com/reference.png"},
        },
        {
            "type": "video_url",
            "video_url": {"url": "https://cdn.example.com/clip.mp4"},
            "fps": 1.0,
            "max_frames": 24,
        },
        {"type": "text", "text": "请比较图像和视频。"},
    ]

    class FakeCapabilityCache:
        def get(self, model, capability):
            captured["capability_get"] = (model, capability)
            return None

        def learn(self, model, capability, value):
            captured["capability_learn"] = (model, capability, value)

    class FakeResponse:
        text = ""
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            message = {
                "content": [
                    {"type": "text", "text": "看到了图像"},
                    {"type": "text", "text": "也看到了完整视频"},
                ],
            }
            return {
                "choices": [{"finish_reason": "stop", "message": message}],
            }

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _tb):
            return False

        async def post(self, url, *, headers, json):
            captured.update(url=url, headers=headers, body=json)
            return FakeResponse()

    @asynccontextmanager
    async def fake_model_slot(_kind):
        yield

    monkeypatch.setattr(
        vlm_model,
        "get_capability_cache",
        lambda: FakeCapabilityCache(),
    )
    monkeypatch.setattr(vlm_model, "model_slot", fake_model_slot)
    monkeypatch.setattr(vlm_model.httpx, "AsyncClient", FakeAsyncClient)
    config = {
        "get_vlm_api_key": "test-vlm-key",
        "get_vlm_model_name": "qwen3.7-plus",
        "get_vlm_chat_url": "https://provider.example/v1/chat/completions",
        "get_vlm_timeout_seconds": 31.0,
    }
    for name, value in config.items():
        monkeypatch.setattr(vlm_model.model_config, name, lambda v=value: v)

    result = asyncio.run(
        vlm_model.chat_completion(
            content,
            system_prompt="  仅分析提供的素材。  ",
            temperature=0.1,
            max_tokens=321,
        ),
    )

    assert result == "看到了图像\n也看到了完整视频"
    assert captured["capability_get"] == ("vlm:qwen3.7-plus", "rejects_media")
    video_part = {
        "type": "video_url",
        "video_url": {"url": "https://cdn.example.com/clip.mp4"},
        "fps": 1.0,
    }
    assert captured["body"] == {
        "model": "qwen3.7-plus",
        "messages": [
            {"role": "system", "content": "仅分析提供的素材。"},
            {"role": "user", "content": [content[0], video_part, content[2]]},
        ],
        "temperature": 0.1,
        "max_tokens": 321,
        "enable_thinking": False,
    }
    assert content[1]["max_frames"] == 24
    assert captured["headers"]["Authorization"] == "Bearer test-vlm-key"


def test_invalid_media_payload_does_not_poison_capability_cache() -> None:
    dims_error = (
        "The image length and width do not meet the model restrictions; "
        "width must be larger than 10"
    )
    assert not vlm_model._is_media_related_error(dims_error)
    assert vlm_model._is_media_related_error(
        "This model does not support multimodal input",
    )
