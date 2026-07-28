# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long,protected-access,unnecessary-lambda
# pylint: disable=useless-return

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest

from models import vlm_model


pytestmark = pytest.mark.unit


def test_remote_image_and_video_content_parts_are_provider_compatible():
    assert vlm_model.multimodal_media_part(
        "https://cdn.example.com/reference.png",
        "image",
    ) == {
        "type": "image_url",
        "image_url": {"url": "https://cdn.example.com/reference.png"},
    }
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


def test_local_image_and_video_keep_urls_for_request_time_transport(
    tmp_path,
):
    image = tmp_path / "reference.png"
    video = tmp_path / "clip.mp4"
    image.write_bytes(b"png")
    video.write_bytes(b"mp4")

    assert vlm_model.multimodal_media_part(image.as_uri(), "image") == {
        "type": "image_url",
        "image_url": {"url": image.as_uri()},
    }
    assert vlm_model.multimodal_media_part(
        video.as_uri(),
        "video",
        fps=1.0,
    ) == {
        "type": "video_url",
        "video_url": {"url": video.as_uri()},
        "fps": 1.0,
    }


def test_local_media_transport_uploads_to_dashscope_temp(
    tmp_path,
    monkeypatch,
):
    image = tmp_path / "reference.png"
    image.write_bytes(b"png")
    observed = {}

    async def fake_upload(path, *, api_key, model_name, media_type):
        observed["call"] = (path, api_key, model_name, media_type)
        return "oss://dashscope-instant/reference.png"

    monkeypatch.setattr(
        vlm_model.model_config,
        "get_vlm_base_url",
        lambda: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    monkeypatch.setattr(
        vlm_model,
        "upload_local_file_to_dashscope_temp",
        fake_upload,
    )

    part = vlm_model.multimodal_media_part(image.as_uri(), "image")
    transported, uses_temp_oss = asyncio.run(
        vlm_model._transport_local_media_part(part, "vlm-key", "qwen3-vl"),
    )

    assert uses_temp_oss is True
    assert transported == {
        "type": "image_url",
        "image_url": {"url": "oss://dashscope-instant/reference.png"},
    }
    assert observed["call"] == (
        image.resolve(),
        "vlm-key",
        "qwen3-vl",
        "image/png",
    )


def test_local_media_transport_falls_back_to_data_url_off_dashscope(
    tmp_path,
    monkeypatch,
):
    image = tmp_path / "reference.png"
    image.write_bytes(b"png")
    monkeypatch.setattr(
        vlm_model.model_config,
        "get_vlm_base_url",
        lambda: "https://api.openai.example/v1",
    )
    monkeypatch.setattr(
        vlm_model.model_config,
        "get_vlm_max_inline_bytes",
        lambda: 1024,
    )

    part = vlm_model.multimodal_media_part(image.as_uri(), "image")
    transported, uses_temp_oss = asyncio.run(
        vlm_model._transport_local_media_part(part, "vlm-key", "gpt-vision"),
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
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": [
                                {"type": "text", "text": "看到了图像"},
                                {"type": "text", "text": "也看到了完整视频"},
                            ],
                        },
                    },
                ],
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
    monkeypatch.setattr(
        vlm_model.model_config,
        "get_vlm_api_key",
        lambda: "test-vlm-key",
    )
    monkeypatch.setattr(
        vlm_model.model_config,
        "get_vlm_model_name",
        lambda: "qwen3.7-plus",
    )
    monkeypatch.setattr(
        vlm_model.model_config,
        "get_vlm_chat_url",
        lambda: "https://provider.example.com/compatible-mode/v1/chat/completions",
    )
    monkeypatch.setattr(
        vlm_model.model_config,
        "get_vlm_timeout_seconds",
        lambda: 31.0,
    )

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
    assert captured["body"] == {
        "model": "qwen3.7-plus",
        "messages": [
            {"role": "system", "content": "仅分析提供的素材。"},
            {
                "role": "user",
                "content": [
                    content[0],
                    {
                        "type": "video_url",
                        "video_url": {
                            "url": "https://cdn.example.com/clip.mp4",
                        },
                        "fps": 1.0,
                    },
                    content[2],
                ],
            },
        ],
        "temperature": 0.1,
        "max_tokens": 321,
        "enable_thinking": False,
    }
    assert content[1]["max_frames"] == 24
    assert captured["headers"] == {
        "Authorization": "Bearer test-vlm-key",
        "Content-Type": "application/json",
    }
    assert captured["timeout"] == 31.0


def test_invalid_media_payload_does_not_poison_model_capability_cache() -> (
    None
):
    assert not vlm_model._is_media_related_error(
        "The image length and width do not meet the model restrictions; width must be larger than 10",
    )
    assert vlm_model._is_media_related_error(
        "This model does not support multimodal input",
    )
