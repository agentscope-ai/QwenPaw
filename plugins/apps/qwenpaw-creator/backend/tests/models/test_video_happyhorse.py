# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access

from __future__ import annotations

import asyncio

import pytest

from models import config as model_config
from models import video_model
from models.video_capabilities import (
    is_happyhorse_model,
    video_model_prompt_guidance,
)
from utils.exceptions import ModelError


class _FakeResponse:
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"output": {"task_id": "task-hh-1"}}


class _FakeAsyncClient:
    def __init__(self, captured: dict):
        self._captured = captured

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    async def post(self, url, headers=None, json=None) -> _FakeResponse:
        self._captured["url"] = url
        self._captured["headers"] = headers
        self._captured["body"] = json
        return _FakeResponse()


def _bind_happyhorse(monkeypatch, captured: dict | None = None) -> None:
    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: "happyhorse-1.1-r2v",
    )
    monkeypatch.setattr(model_config, "get_video_backend", lambda: "wan")
    monkeypatch.setattr(model_config, "get_video_api_key", lambda: "sk-test")
    monkeypatch.setattr(
        model_config,
        "get_video_submit_url",
        lambda: "https://bailian.example/api/v1/services/aigc/video-generation/video-synthesis",
    )
    monkeypatch.setattr(model_config, "get_video_submit_timeout", lambda: 5)

    async def fake_resolve(url: str, backend: str):
        assert backend == "wan"
        return f"oss://dashscope-instant/{url.rsplit('/', 1)[-1]}", "image"

    monkeypatch.setattr(
        video_model,
        "_resolve_reference_media_url",
        fake_resolve,
    )
    if captured is not None:
        monkeypatch.setattr(
            video_model.httpx,
            "AsyncClient",
            lambda timeout: _FakeAsyncClient(captured),
        )


def test_happyhorse_models_route_to_wan_backend(monkeypatch) -> None:
    token = model_config.set_request_tool_configs({})
    try:
        for model in ("happyhorse-1.1-r2v", "HappyHorse-1.0-R2V"):
            monkeypatch.setattr(
                model_config,
                "get_video_model_name",
                lambda value=model: value,
            )
            monkeypatch.setattr(
                model_config,
                "get_video_base_url",
                lambda: "https://dashscope.aliyuncs.com/api/v1",
            )
            assert model_config.get_video_backend() == "wan"
    finally:
        model_config.reset_request_tool_configs(token)


def test_is_happyhorse_model_matches_prefix_case_insensitively() -> None:
    assert is_happyhorse_model("happyhorse-1.1-r2v")
    assert is_happyhorse_model(" HappyHorse-1.0-r2v ")
    assert not is_happyhorse_model("wan2.7-r2v")
    assert not is_happyhorse_model("")


def test_happyhorse_submit_body_omits_prompt_extend(monkeypatch) -> None:
    captured: dict = {}
    _bind_happyhorse(monkeypatch, captured)

    task_id = asyncio.run(
        video_model.submit_video_task(
            "[Image 1]中的角色向前走",
            reference_image_url="/generated/storyboard.png",
            reference_image_url_list=["/generated/anchor.png"],
            ratio="16:9",
            duration=5,
            resolution="720p",
        ),
    )

    assert task_id == "task-hh-1"
    body = captured["body"]
    assert body["model"] == "happyhorse-1.1-r2v"
    assert "prompt_extend" not in body["parameters"]
    assert body["parameters"]["resolution"] == "720P"
    assert body["parameters"]["duration"] == 5
    # Without an explicit watermark argument, no provider watermark is added.
    assert body["parameters"]["watermark"] is False
    assert [item["type"] for item in body["input"]["media"]] == [
        "reference_image",
        "reference_image",
    ]
    assert captured["headers"]["X-DashScope-Async"] == "enable"


def test_wan_submit_body_keeps_prompt_extend(monkeypatch) -> None:
    captured: dict = {}
    _bind_happyhorse(monkeypatch, captured)
    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: "wan2.7-r2v",
    )

    asyncio.run(
        video_model.submit_video_task(
            "角色向前走",
            reference_image_url="/generated/storyboard.png",
            ratio="16:9",
            duration=5,
            resolution="720p",
        ),
    )

    assert captured["body"]["parameters"]["prompt_extend"] is False


def test_happyhorse_rejects_video_reference(monkeypatch) -> None:
    _bind_happyhorse(monkeypatch)

    async def fake_resolve(url: str, backend: str):
        del url, backend
        return "oss://dashscope-instant/clip.mp4", "video"

    monkeypatch.setattr(
        video_model,
        "_resolve_reference_media_url",
        fake_resolve,
    )

    with pytest.raises(ModelError, match="only accepts image references"):
        asyncio.run(
            video_model.submit_video_task(
                "prompt",
                reference_image_url="/generated/clip.mp4",
                ratio="16:9",
                duration=5,
                resolution="720P",
            ),
        )


def test_happyhorse_requires_one_to_nine_references(monkeypatch) -> None:
    _bind_happyhorse(monkeypatch)

    with pytest.raises(ModelError, match="at least 1 reference image"):
        asyncio.run(
            video_model.submit_video_task(
                "prompt",
                ratio="16:9",
                duration=5,
                resolution="720P",
            ),
        )

    too_many = [f"/generated/ref-{index}.png" for index in range(10)]
    with pytest.raises(ModelError, match="at most 9"):
        asyncio.run(
            video_model.submit_video_task(
                "prompt",
                reference_image_url_list=too_many,
                ratio="16:9",
                duration=5,
                resolution="720P",
            ),
        )


def test_happyhorse_validates_resolution_ratio_and_duration(
    monkeypatch,
) -> None:
    _bind_happyhorse(monkeypatch)

    with pytest.raises(ModelError, match="resolution must be one of"):
        asyncio.run(
            video_model.submit_video_task(
                "prompt",
                reference_image_url="/generated/ref.png",
                ratio="16:9",
                duration=5,
                resolution="480P",
            ),
        )

    with pytest.raises(ModelError, match="ratio must be one of"):
        asyncio.run(
            video_model.submit_video_task(
                "prompt",
                reference_image_url="/generated/ref.png",
                ratio="auto",
                duration=5,
                resolution="720P",
            ),
        )

    with pytest.raises(ModelError, match="duration must be an integer"):
        asyncio.run(
            video_model.submit_video_task(
                "prompt",
                reference_image_url="/generated/ref.png",
                ratio="16:9",
                duration=2,
                resolution="720P",
            ),
        )


def test_prompt_guidance_is_model_aware() -> None:
    happyhorse = video_model_prompt_guidance("happyhorse-1.1-r2v")
    assert "[Image N]" in happyhorse
    assert "[Image 1]" in happyhorse
    assert "1–9 张图片" in happyhorse

    generic = video_model_prompt_guidance("wan2.7-r2v")
    assert "[Image N]" not in generic
    assert "wan2.7-r2v" in generic
