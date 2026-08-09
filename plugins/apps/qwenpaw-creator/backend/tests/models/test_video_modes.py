# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access
"""Video generation mode matrix: t2v / i2v / video_edit payloads & gating.

Provider HTTP traffic is stubbed; no real model is ever called.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from models import config as model_config
from models import video_model
from models.video_capabilities import (
    VIDEO_MODE_MATRIX,
    configured_mode_segment,
    derive_video_model_name,
    effective_video_model_name,
    validate_video_mode,
    video_backend_key,
    video_model_prompt_guidance,
)
from utils.exceptions import ModelError


class _FakeResponse:
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"output": {"task_id": "task-mode-1"}}


class _ModelNotExistResponse:
    """Provider answer when a derived model name has no such model."""

    status_code = 404
    text = (
        '{"code":"InvalidParameter","message":"Model not exist.",'
        '"request_id":"req-1"}'
    )

    def raise_for_status(self) -> None:
        raise httpx.HTTPStatusError(
            "404",
            request=httpx.Request("POST", "https://bailian.example"),
            response=httpx.Response(404, text=self.text),
        )

    def json(self) -> dict:
        return {"code": "InvalidParameter", "message": "Model not exist."}


class _FakeAsyncClient:
    def __init__(self, captured: dict, response=None):
        self._captured = captured
        self._response = response or _FakeResponse()

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    async def post(self, url, headers=None, json=None):
        self._captured["url"] = url
        self._captured["headers"] = headers
        self._captured["body"] = json
        return self._response


def _bind(
    monkeypatch,
    model: str,
    captured: dict | None = None,
    response=None,
) -> None:
    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: model,
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
        name = url.rsplit("/", 1)[-1]
        kind = "video" if name.endswith((".mp4", ".mov")) else "image"
        return f"oss://dashscope-instant/{name}", kind

    monkeypatch.setattr(
        video_model,
        "_resolve_reference_media_url",
        fake_resolve,
    )
    if captured is not None:
        monkeypatch.setattr(
            video_model.httpx,
            "AsyncClient",
            lambda timeout: _FakeAsyncClient(captured, response),
        )


# ── model name derivation ────────────────────────────────────────────────────


def test_derive_model_name_appends_suffix_to_base_names() -> None:
    assert derive_video_model_name("happyhorse-1.1", "t2v") == (
        "happyhorse-1.1-t2v"
    )
    assert derive_video_model_name("happyhorse-1.1", "video_edit") == (
        "happyhorse-1.1-video-edit"
    )
    assert derive_video_model_name("happyhorse-1.1", "r2v") == (
        "happyhorse-1.1-r2v"
    )


def test_derive_model_name_replaces_existing_mode_segment() -> None:
    assert derive_video_model_name("happyhorse-1.1-r2v", "t2v") == (
        "happyhorse-1.1-t2v"
    )
    assert derive_video_model_name("happyhorse-1.0-video-edit", "i2v") == (
        "happyhorse-1.0-i2v"
    )
    assert derive_video_model_name("wan2.7-r2v", "i2v") == "wan2.7-i2v"
    # Dated variants keep their tail after the mode segment.
    assert derive_video_model_name("wan2.7-i2v-2026-04-25", "t2v") == (
        "wan2.7-t2v-2026-04-25"
    )
    assert derive_video_model_name("happyhorse-1.1-r2v", "r2v") == (
        "happyhorse-1.1-r2v"
    )


def test_configured_mode_segment_detection() -> None:
    assert configured_mode_segment("wan2.7-i2v") == "i2v"
    assert configured_mode_segment("wan2.7-t2v-2026-04-25") == "t2v"
    assert configured_mode_segment("happyhorse-1.0-video-edit") == (
        "video_edit"
    )
    assert configured_mode_segment("happyhorse-1.1") is None
    # A longer hyphen token must not match a shorter mode segment.
    assert configured_mode_segment("wan2.7-r2v2") is None


def test_effective_name_derives_wan_cross_mode_names() -> None:
    """A wan name encoding another mode cannot serve an r2v request as-is."""

    # Review M2: configured wan2.7-i2v + default r2v used to submit the
    # i2v model; it must resolve to the r2v family instead.
    assert effective_video_model_name("wan2.7-i2v", "r2v", "wan") == (
        "wan2.7-r2v"
    )
    assert effective_video_model_name("wan2.7-t2v", "", "wan") == (
        "wan2.7-r2v"
    )
    # Dated variants keep their tail.
    assert (
        effective_video_model_name(
            "wan2.7-i2v-2026-04-25",
            "r2v",
            "wan",
        )
        == "wan2.7-r2v-2026-04-25"
    )


def test_effective_name_keeps_legacy_wan_r2v_behaviour() -> None:
    # The historical byte-identical contract: an r2v or mode-less configured
    # name is submitted untouched for the default mode.
    assert effective_video_model_name("wan2.7-r2v", "r2v", "wan") == (
        "wan2.7-r2v"
    )
    assert effective_video_model_name("wanx-video", "r2v", "wan") == (
        "wanx-video"
    )
    # seedance2 always submits the configured name as-is.
    assert (
        effective_video_model_name(
            "doubao-seedance-2.0-pro",
            "r2v",
            "seedance2",
        )
        == "doubao-seedance-2.0-pro"
    )
    # HappyHorse still derives for every mode, including the default.
    assert (
        effective_video_model_name(
            "happyhorse-1.1",
            "r2v",
            "happyhorse",
        )
        == "happyhorse-1.1-r2v"
    )


# ── capability matrix ────────────────────────────────────────────────────────


def test_matrix_matches_the_finalized_plan() -> None:
    assert VIDEO_MODE_MATRIX["happyhorse"] == {
        "r2v",
        "t2v",
        "i2v",
        "video_edit",
    }
    assert VIDEO_MODE_MATRIX["wan"] == {"r2v", "t2v", "i2v"}
    assert VIDEO_MODE_MATRIX["seedance2"] == {"r2v"}


def test_backend_key_detection() -> None:
    assert video_backend_key("happyhorse-1.1-r2v") == "happyhorse"
    assert video_backend_key("wan2.7-r2v") == "wan"
    assert video_backend_key("doubao-seedance-2.0-pro") == "seedance2"
    assert video_backend_key("wan2.7-r2v", "seedance2") == "seedance2"


def test_validate_video_mode_rejects_unsupported_pairs() -> None:
    assert validate_video_mode("happyhorse", "hh", "video_edit") == (
        "video_edit"
    )
    assert validate_video_mode("wan", "wan2.7-r2v", "") == "r2v"
    with pytest.raises(ValueError, match="不支持 mode=video_edit"):
        validate_video_mode("wan", "wan2.7-r2v", "video_edit")
    with pytest.raises(ValueError, match="不支持 mode=t2v"):
        validate_video_mode("seedance2", "doubao-seedance-2.0-pro", "t2v")
    with pytest.raises(ValueError, match="未知的视频生成 mode"):
        validate_video_mode("wan", "wan2.7-r2v", "remix")


def test_seedance_submit_rejects_t2v(monkeypatch) -> None:
    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: "doubao-seedance-2.0-pro",
    )
    monkeypatch.setattr(
        model_config,
        "get_video_backend",
        lambda: "seedance2",
    )
    monkeypatch.setattr(model_config, "get_video_api_key", lambda: "sk-test")
    with pytest.raises(ModelError, match="不支持 mode=t2v"):
        asyncio.run(video_model.submit_video_task("prompt", mode="t2v"))


# ── happyhorse mode payloads ─────────────────────────────────────────────────


def test_happyhorse_t2v_payload_shape(monkeypatch) -> None:
    captured: dict = {}
    _bind(monkeypatch, "happyhorse-1.1-r2v", captured)

    task_id = asyncio.run(
        video_model.submit_video_task(
            "一只小猫在雨夜的街头奔跑",
            mode="t2v",
            ratio="16:9",
            duration=5,
            resolution="720p",
        ),
    )

    assert task_id == "task-mode-1"
    body = captured["body"]
    assert body["model"] == "happyhorse-1.1-t2v"
    assert body["input"] == {"prompt": "一只小猫在雨夜的街头奔跑"}
    assert body["parameters"] == {
        "resolution": "720P",
        "ratio": "16:9",
        "watermark": False,
        "duration": 5,
    }
    assert captured["headers"]["X-DashScope-Async"] == "enable"


def test_happyhorse_i2v_payload_shape(monkeypatch) -> None:
    captured: dict = {}
    _bind(monkeypatch, "happyhorse-1.1-r2v", captured)

    asyncio.run(
        video_model.submit_video_task(
            "首帧中的角色转身微笑",
            mode="i2v",
            first_frame_url="/generated/first.png",
            duration=6,
            resolution="1080P",
        ),
    )

    body = captured["body"]
    assert body["model"] == "happyhorse-1.1-i2v"
    assert body["input"]["media"] == [
        {"type": "first_frame", "url": "oss://dashscope-instant/first.png"},
    ]
    # ratio follows the first frame, so it is not sent.
    assert body["parameters"] == {
        "resolution": "1080P",
        "watermark": False,
        "duration": 6,
    }


def test_happyhorse_video_edit_payload_shape(monkeypatch) -> None:
    captured: dict = {}
    _bind(monkeypatch, "happyhorse-1.1-r2v", captured)

    asyncio.run(
        video_model.submit_video_task(
            "把场景改成黄昏",
            mode="video_edit",
            video_url="/generated/source.mp4",
            reference_image_url_list=["/generated/style.png"],
            resolution="720P",
            generate_audio=False,
        ),
    )

    body = captured["body"]
    assert body["model"] == "happyhorse-1.1-video-edit"
    assert body["input"]["media"] == [
        {"type": "video", "url": "oss://dashscope-instant/source.mp4"},
        {
            "type": "reference_image",
            "url": "oss://dashscope-instant/style.png",
        },
    ]
    # Duration/ratio follow the input video; audio_setting maps
    # generateAudio=False onto keeping the original track.
    assert body["parameters"] == {
        "resolution": "720P",
        "watermark": False,
        "audio_setting": "origin",
    }


def test_happyhorse_r2v_payload_is_unchanged(monkeypatch) -> None:
    captured: dict = {}
    _bind(monkeypatch, "happyhorse-1.1-r2v", captured)

    asyncio.run(
        video_model.submit_video_task(
            "[Image 1]中的角色向前走",
            reference_image_url="/generated/storyboard.png",
            ratio="16:9",
            duration=5,
            resolution="720p",
        ),
    )

    body = captured["body"]
    assert body["model"] == "happyhorse-1.1-r2v"
    assert "prompt_extend" not in body["parameters"]
    assert body["parameters"]["ratio"] == "16:9"
    assert [item["type"] for item in body["input"]["media"]] == [
        "reference_image",
    ]


# ── wan mode payloads ────────────────────────────────────────────────────────


def test_wan_t2v_payload_shape(monkeypatch) -> None:
    captured: dict = {}
    _bind(monkeypatch, "wan2.7-r2v", captured)

    asyncio.run(
        video_model.submit_video_task(
            "无人机穿越峡谷",
            mode="t2v",
            ratio="16:9",
            duration=10,
            resolution="720P",
        ),
    )

    body = captured["body"]
    assert body["model"] == "wan2.7-t2v"
    assert body["input"] == {"prompt": "无人机穿越峡谷"}
    assert body["parameters"] == {
        "resolution": "720P",
        "ratio": "16:9",
        "watermark": False,
        "duration": 10,
        "prompt_extend": False,
    }


def test_wan_i2v_payload_shape(monkeypatch) -> None:
    captured: dict = {}
    _bind(monkeypatch, "wan2.7-r2v", captured)

    asyncio.run(
        video_model.submit_video_task(
            "画面中的人物睁开眼睛",
            mode="i2v",
            first_frame_url="/generated/frame.png",
            duration=5,
            resolution="720P",
        ),
    )

    body = captured["body"]
    assert body["model"] == "wan2.7-i2v"
    assert body["input"]["media"] == [
        {"type": "first_frame", "url": "oss://dashscope-instant/frame.png"},
    ]
    assert body["parameters"] == {
        "resolution": "720P",
        "watermark": False,
        "duration": 5,
        "prompt_extend": False,
    }


def test_wan_video_edit_is_rejected(monkeypatch) -> None:
    _bind(monkeypatch, "wan2.7-r2v")
    with pytest.raises(ModelError, match="不支持 mode=video_edit"):
        asyncio.run(
            video_model.submit_video_task(
                "改成黄昏",
                mode="video_edit",
                video_url="/generated/source.mp4",
            ),
        )


# ── mode input contracts ─────────────────────────────────────────────────────


def test_t2v_rejects_reference_media(monkeypatch) -> None:
    _bind(monkeypatch, "happyhorse-1.1-r2v")
    with pytest.raises(ModelError, match="text-only"):
        asyncio.run(
            video_model.submit_video_task(
                "prompt",
                mode="t2v",
                reference_image_url="/generated/ref.png",
            ),
        )


def test_i2v_requires_first_frame(monkeypatch) -> None:
    _bind(monkeypatch, "happyhorse-1.1-r2v")
    with pytest.raises(ModelError, match="requires firstFrameRef"):
        asyncio.run(video_model.submit_video_task("prompt", mode="i2v"))


def test_video_edit_requires_video(monkeypatch) -> None:
    _bind(monkeypatch, "happyhorse-1.1-r2v")
    with pytest.raises(ModelError, match="requires videoRef"):
        asyncio.run(
            video_model.submit_video_task("prompt", mode="video_edit"),
        )


def test_video_edit_rejects_video_reference_as_style_image(
    monkeypatch,
) -> None:
    _bind(monkeypatch, "happyhorse-1.1-r2v")
    with pytest.raises(ModelError, match="must be images"):
        asyncio.run(
            video_model.submit_video_task(
                "prompt",
                mode="video_edit",
                video_url="/generated/source.mp4",
                reference_image_url_list=["/generated/extra.mp4"],
            ),
        )


def test_i2v_first_frame_must_be_an_image(monkeypatch) -> None:
    _bind(monkeypatch, "happyhorse-1.1-r2v")
    with pytest.raises(ModelError, match="must be an image"):
        asyncio.run(
            video_model.submit_video_task(
                "prompt",
                mode="i2v",
                first_frame_url="/generated/clip.mp4",
            ),
        )


def test_happyhorse_t2v_validates_duration(monkeypatch) -> None:
    _bind(monkeypatch, "happyhorse-1.1-r2v")
    with pytest.raises(ModelError, match="duration must be an integer"):
        asyncio.run(
            video_model.submit_video_task(
                "prompt",
                mode="t2v",
                duration=2,
                resolution="720P",
            ),
        )


def test_derived_model_not_existing_explains_the_family_mismatch(
    monkeypatch,
) -> None:
    """Measured case: happyhorse-1.1 has no -video-edit model upstream."""

    captured: dict = {}
    _bind(
        monkeypatch,
        "happyhorse-1.1-r2v",
        captured,
        response=_ModelNotExistResponse(),
    )

    with pytest.raises(ModelError, match="happyhorse-1.1-video-edit") as info:
        asyncio.run(
            video_model.submit_video_task(
                "把场景改成黄昏",
                mode="video_edit",
                video_url="/generated/source.mp4",
                resolution="720P",
            ),
        )
    message = str(info.value)
    assert "happyhorse-1.1-r2v" in message
    assert "creator_video_model.model" in message


# ── prompt guidance ──────────────────────────────────────────────────────────


def test_guidance_describes_the_mode_matrix() -> None:
    happyhorse = video_model_prompt_guidance("happyhorse-1.1-r2v")
    assert "生成模式矩阵" in happyhorse
    assert "video_edit" in happyhorse
    assert "只取前 15 秒" in happyhorse

    wan = video_model_prompt_guidance("wan2.7-r2v")
    assert "生成模式矩阵" in wan
    assert "t2v" in wan
    assert "不支持的 mode（video_edit）" in wan

    seedance = video_model_prompt_guidance("doubao-seedance-2.0-pro")
    assert "不支持的 mode（t2v, i2v, video_edit）" in seedance
