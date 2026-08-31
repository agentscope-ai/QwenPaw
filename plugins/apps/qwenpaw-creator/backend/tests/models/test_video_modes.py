# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access
"""Video generation mode matrix: t2v / i2v / video_edit payloads & gating.

Provider HTTP traffic is stubbed; no real model is ever called.
"""

from __future__ import annotations

import asyncio
import io

from PIL import Image
import pytest

from models import config as model_config
from models import video_model
from models.video_capabilities import (
    configured_mode_segment,
    derive_video_model_name,
    effective_video_model_name,
    validate_video_mode,
    video_backend_key,
    video_model_capability_payload,
    video_model_prompt_guidance,
    video_model_supported_modes,
    video_reference_capability,
)
from utils.exceptions import ModelError


class _FakeResponse:
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"output": {"task_id": "task-mode-1"}}


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
    monkeypatch.setattr(model_config, "get_video_model_name", lambda: model)
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


def test_derive_model_name_appends_or_replaces_mode_segments() -> None:
    for configured, mode, expected in (
        # Base names gain the suffix.
        ("happyhorse-1.1", "t2v", "happyhorse-1.1-t2v"),
        ("happyhorse-1.1", "video_edit", "happyhorse-1.1-video-edit"),
        # An existing mode segment is replaced, not stacked.
        ("happyhorse-1.0-video-edit", "i2v", "happyhorse-1.0-i2v"),
        ("wan2.7-r2v", "i2v", "wan2.7-i2v"),
        # Dated variants keep their tail after the mode segment.
        ("wan2.7-i2v-2026-04-25", "t2v", "wan2.7-t2v-2026-04-25"),
        ("happyhorse-1.1-r2v", "r2v", "happyhorse-1.1-r2v"),
    ):
        assert derive_video_model_name(configured, mode) == expected, (
            configured,
            mode,
        )


def test_configured_mode_segment_detection() -> None:
    assert configured_mode_segment("wan2.7-i2v") == "i2v"
    assert configured_mode_segment("wan2.7-t2v-2026-04-25") == "t2v"
    assert configured_mode_segment("happyhorse-1.0-video-edit") == "video_edit"
    assert configured_mode_segment("happyhorse-1.1") is None
    # A longer hyphen token must not match a shorter mode segment.
    assert configured_mode_segment("wan2.7-r2v2") is None


def test_effective_name_derives_wan_cross_mode_names() -> None:
    """A wan name encoding another mode cannot serve an r2v request as-is."""

    # Review M2: configured wan2.7-i2v + default r2v used to submit the
    # i2v model; it must resolve to the r2v family instead.
    assert (
        effective_video_model_name("wan2.7-i2v", "r2v", "wan") == "wan2.7-r2v"
    )
    assert effective_video_model_name("wan2.7-t2v", "", "wan") == "wan2.7-r2v"
    # Dated variants keep their tail.
    assert (
        effective_video_model_name("wan2.7-i2v-2026-04-25", "r2v", "wan")
        == "wan2.7-r2v-2026-04-25"
    )


def test_effective_name_derives_official_wan_base_for_r2v() -> None:
    assert (
        effective_video_model_name("wan2.7-r2v", "r2v", "wan") == "wan2.7-r2v"
    )
    assert effective_video_model_name("wan2.7", "r2v", "wan") == "wan2.7-r2v"
    # Unknown aliases stay byte-identical and fail closed in mode validation.
    assert (
        effective_video_model_name("wanx-video", "r2v", "wan") == "wanx-video"
    )
    # seedance2 always submits the configured name as-is.
    assert (
        effective_video_model_name(
            "doubao-seedance-2-0-260128",
            "r2v",
            "seedance2",
        )
        == "doubao-seedance-2-0-260128"
    )
    # HappyHorse still derives for every mode, including the default.
    assert (
        effective_video_model_name("happyhorse-1.1", "r2v", "happyhorse")
        == "happyhorse-1.1-r2v"
    )


def test_effective_name_derives_suffix_for_bare_wan_family() -> None:
    # Bare Wan family names (no mode suffix) must derive the mode suffix for
    # r2v mode, because DashScope only recognizes the full IDs like
    # "wan2.7-r2v", not the bare "wan2.7".
    assert effective_video_model_name("wan2.7", "r2v", "wan") == "wan2.7-r2v"
    assert effective_video_model_name("wan2.6", "r2v", "wan") == "wan2.6-r2v"
    # t2v/i2v derive from the same capability declaration.
    assert effective_video_model_name("wan2.7", "t2v", "wan") == "wan2.7-t2v"
    assert effective_video_model_name("wan2.7", "i2v", "wan") == "wan2.7-i2v"
    # Names with an existing suffix are not re-derived.
    assert (
        effective_video_model_name("wan2.7-r2v", "r2v", "wan") == "wan2.7-r2v"
    )
    assert (
        effective_video_model_name("wan2.7-i2v", "r2v", "wan") == "wan2.7-r2v"
    )
    # Opaque names like "wanx-video" keep the historical byte-identical
    # behaviour (no capability declares them, so nothing derives).
    assert (
        effective_video_model_name("wanx-video", "r2v", "wan") == "wanx-video"
    )


# ── capability matrix ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("backend", "model_name", "expected"),
    [
        ("wan", "wan2.7", {"r2v", "t2v", "i2v"}),
        ("wan", "wan3.0-video", {"r2v", "t2v", "i2v"}),
        ("wan", "happyhorse-1.1", {"r2v", "t2v", "i2v"}),
        ("seedance2", "doubao-seedance-2-5-260628", {"r2v", "t2v", "i2v"}),
        ("seedance2", "doubao-seedance-2-0-260128", {"r2v", "t2v", "i2v"}),
        (
            "seedance2",
            "doubao-seedance-2-0-fast-260128",
            {"r2v", "t2v", "i2v"},
        ),
        (
            "seedance2",
            "doubao-seedance-2-0-mini-260615",
            {"r2v", "t2v", "i2v"},
        ),
        ("veo", "veo-3.1-generate-preview", {"r2v", "t2v", "i2v"}),
        ("veo", "veo-3.1-fast-generate-preview", {"r2v", "t2v", "i2v"}),
        ("veo", "veo-3.1-lite-generate-preview", {"t2v", "i2v"}),
        ("minimax", "MiniMax-Hailuo-2.3", {"t2v", "i2v"}),
        ("minimax", "MiniMax-Hailuo-2.3-Fast", {"i2v"}),
        ("minimax", "MiniMax-Hailuo-02", {"t2v", "i2v"}),
        ("minimax", "S2V-01", {"r2v"}),
        ("kling", "kling-3.0-omni", {"r2v", "t2v", "i2v"}),
        ("kling", "kling-2.6", {"t2v", "i2v"}),
        ("vidu", "viduq3-mix", {"r2v"}),
        ("vidu", "viduq3-turbo", {"r2v", "t2v", "i2v"}),
        ("vidu", "viduq3", {"r2v"}),
        ("vidu", "viduq2-pro", {"r2v", "i2v"}),
        ("vidu", "viduq2", {"r2v", "t2v"}),
    ],
)
def test_exact_preset_capability_matrix(backend, model_name, expected) -> None:
    assert video_model_supported_modes(model_name, backend) == expected


def test_hosted_single_model_capabilities_do_not_inherit_provider_union() -> (
    None
):
    assert video_model_supported_modes(
        "kling/kling-v3-video-generation",
        "wan",
    ) == {"t2v", "i2v"}
    assert video_model_supported_modes(
        "vidu/viduq3-mix_reference2video",
        "wan",
    ) == {"r2v"}
    unknown = video_model_capability_payload("private-video-gateway", "wan")
    assert unknown["known"] is False
    assert unknown["supportedModes"] == []


@pytest.mark.parametrize(
    ("model_name", "wrong_protocol"),
    [
        ("kling-3.0-omni", "wan"),
        ("kling/kling-v3-omni-video-generation", "kling"),
        ("viduq3-turbo", "wan"),
        ("vidu/viduq3-mix_reference2video", "vidu"),
        ("veo-3.1-generate-preview", "wan"),
        ("doubao-seedance-2-5-260628", "wan"),
    ],
)
def test_model_id_on_the_wrong_protocol_fails_closed(
    model_name,
    wrong_protocol,
) -> None:
    capability = video_model_capability_payload(
        model_name,
        wrong_protocol,
    )
    assert capability["known"] is False
    assert capability["supportedModes"] == []


def test_backend_key_detection() -> None:
    assert video_backend_key("happyhorse-1.1-r2v") == "happyhorse"
    assert video_backend_key("wan2.7-r2v") == "wan"
    assert video_backend_key("doubao-seedance-2-0-260128") == "seedance2"
    assert video_backend_key("doubao-seedance-2-5-260628") == "seedance2"
    assert video_backend_key("wan2.7-r2v", "seedance2") == "seedance2"
    assert video_backend_key("veo-3.1-generate-preview") == "veo"
    assert video_backend_key("MiniMax-Hailuo-2.3") == "minimax"
    assert video_backend_key("S2V-01") == "minimax"
    # Kling/Vidu map onto one family key regardless of the channel.
    assert (
        video_backend_key("kling/kling-v3-omni-video-generation", "wan")
        == "kling"
    )
    assert video_backend_key("kling-3.0-omni", "kling") == "kling"
    assert (
        video_backend_key("vidu/viduq3-mix_reference2video", "wan") == "vidu"
    )
    assert video_backend_key("viduq3-mix", "vidu") == "vidu"


def test_validate_video_mode_rejects_unsupported_pairs() -> None:
    assert (
        validate_video_mode("happyhorse", "happyhorse-1.0", "video_edit")
        == "video_edit"
    )
    assert validate_video_mode("wan", "wan2.7-r2v", "") == "r2v"
    assert (
        validate_video_mode("seedance2", "doubao-seedance-2-5-260628", "t2v")
        == "t2v"
    )
    with pytest.raises(ValueError, match="不支持 mode=video_edit"):
        validate_video_mode("wan", "wan2.7-r2v", "video_edit")
    with pytest.raises(ValueError, match="不支持 mode=t2v"):
        validate_video_mode("vidu", "vidu/viduq3-mix_reference2video", "t2v")
    with pytest.raises(ValueError, match="未知的视频生成 mode"):
        validate_video_mode("wan", "wan2.7-r2v", "remix")


# ── mode payloads ────────────────────────────────────────────────────────────


def test_happyhorse_video_edit_payload_shape(monkeypatch) -> None:
    captured: dict = {}
    _bind(monkeypatch, "happyhorse-1.0-r2v", captured)

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
    assert body["model"] == "happyhorse-1.0-video-edit"
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
    _bind(monkeypatch, "happyhorse-1.0-r2v")
    with pytest.raises(ModelError, match="requires videoRef"):
        asyncio.run(video_model.submit_video_task("prompt", mode="video_edit"))


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


def test_happyhorse_11_video_edit_rejected_before_provider(
    monkeypatch,
) -> None:
    captured: dict = {}
    _bind(monkeypatch, "happyhorse-1.1-r2v", captured)

    with pytest.raises(ModelError, match="不支持 mode=video_edit"):
        asyncio.run(
            video_model.submit_video_task(
                "把场景改成黄昏",
                mode="video_edit",
                video_url="/generated/source.mp4",
                resolution="720P",
            ),
        )
    assert not captured


# ── prompt guidance ──────────────────────────────────────────────────────────


def test_guidance_describes_the_mode_matrix_per_model() -> None:
    happyhorse = video_model_prompt_guidance("happyhorse-1.1-r2v")
    assert "生成模式矩阵" in happyhorse
    assert "不支持的 mode（video_edit）" in happyhorse
    assert "[Image N]" in happyhorse
    assert "1–9 张图片" in happyhorse

    happyhorse_10 = video_model_prompt_guidance("happyhorse-1.0-r2v")
    assert "video_edit：" in happyhorse_10
    assert "只取前 15 秒" in happyhorse_10

    wan = video_model_prompt_guidance("wan2.7-r2v")
    assert "不支持的 mode（video_edit）" in wan
    assert "[Image N]" not in wan

    wan3 = video_model_prompt_guidance("wan3.0-video")
    assert "All-in-One" in wan3
    assert "图1、图2" in wan3
    assert "图片最多 10 张" in wan3
    assert "视频最多 5 个" in wan3
    assert "2–30 秒" in wan3

    seedance = video_model_prompt_guidance("doubao-seedance-2-0-260128")
    assert "图片最多 9 张" in seedance
    assert "视频最多 3 个" in seedance
    assert "合计最多 12 个" in seedance
    assert "不支持的 mode（video_edit）" in seedance

    seedance_25 = video_model_prompt_guidance("doubao-seedance-2-5-260628")
    assert "图片最多 30 张" in seedance_25
    assert "[4, 30] 秒" in seedance_25

    veo = video_model_prompt_guidance("veo-3.1-generate-preview")
    assert "4/6/8 秒" in veo
    assert "仅支持 1–3 张图片" in veo
    veo_lite = video_model_prompt_guidance("veo-3.1-lite-generate-preview")
    assert "官方不支持 r2v" in veo_lite

    # Kling guidance follows the configured channel's contract.
    kling_bailian = video_model_prompt_guidance(
        "kling/kling-v3-omni-video-generation",
    )
    assert "<<<image_N>>>" in kling_bailian
    assert "图片最多 7 张" in kling_bailian
    kling_direct = video_model_prompt_guidance("kling-3.0-omni")
    assert "@image_N" in kling_direct
    assert "720p/1080p/4k" in kling_direct

    minimax = video_model_prompt_guidance("S2V-01")
    assert "S2V-01" in minimax

    vidu_bailian = video_model_prompt_guidance(
        "vidu/viduq3-mix_reference2video",
    )
    assert "[1, 16] 秒" in vidu_bailian
    assert "不支持的 mode（t2v, i2v, video_edit）" in vidu_bailian
    vidu_direct = video_model_prompt_guidance("viduq3-mix")
    assert "720p/1080p" in vidu_direct


# ---------------------------------------------------------------------------
# Backend channel selection follows the user configuration
# ---------------------------------------------------------------------------


def _bind_selection(monkeypatch, *, model="", base_url="", section=None):
    monkeypatch.setattr(
        model_config,
        "get_request_tool_config",
        lambda tool: {},
    )
    monkeypatch.setattr(model_config, "get_video_model_name", lambda: model)
    monkeypatch.setattr(model_config, "get_video_base_url", lambda: base_url)
    monkeypatch.setattr(
        model_config,
        "_get_user_config",
        lambda: {"video": section or {}},
    )


@pytest.mark.parametrize(
    ("protocol", "expected"),
    [
        ("DashScope（百炼）", "wan"),
        ("Aliyun Token Plan", "wan"),
        ("Volcano Engine（火山引擎）", "seedance2"),
        ("Google Gemini（Veo）", "veo"),
        ("MiniMax（海螺）", "minimax"),
        ("Kling（可灵官方）", "kling"),
        ("Vidu（官方）", "vidu"),
    ],
)
def test_backend_follows_the_saved_protocol(
    monkeypatch,
    protocol,
    expected,
) -> None:
    """The channel is the user's protocol choice, never the model name."""

    _bind_selection(
        monkeypatch,
        # A Kling model name must not override the configured protocol.
        model="kling-3.0-omni",
        section={"enabled": True, "protocol": protocol},
    )
    assert model_config.get_video_backend() == expected


def test_kling_and_vidu_names_do_not_select_a_channel(monkeypatch) -> None:
    # Without a protocol, the configured endpoint host decides — and
    # without either hint the DashScope default wins even for kling/vidu
    # model names.
    _bind_selection(
        monkeypatch,
        model="kling-3.0-omni",
        base_url="https://api-singapore.klingai.com",
    )
    assert model_config.get_video_backend() == "kling"
    _bind_selection(
        monkeypatch,
        model="viduq3-mix",
        base_url="https://api.vidu.com",
    )
    assert model_config.get_video_backend() == "vidu"
    _bind_selection(
        monkeypatch,
        model="kling/kling-v3-omni-video-generation",
        base_url="https://dashscope.aliyuncs.com/api/v1",
    )
    assert model_config.get_video_backend() == "wan"
    _bind_selection(monkeypatch, model="viduq3-mix", base_url="")
    assert model_config.get_video_backend() == "wan"


# ---------------------------------------------------------------------------
# HappyHorse r2v provider
# ---------------------------------------------------------------------------


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


def test_happyhorse_submit_body_omits_prompt_extend(monkeypatch) -> None:
    captured: dict = {}
    _bind(monkeypatch, "happyhorse-1.1-r2v", captured)

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

    assert task_id == "task-mode-1"
    body = captured["body"]
    assert body["model"] == "happyhorse-1.1-r2v"
    assert "prompt_extend" not in body["parameters"]
    assert body["parameters"]["resolution"] == "720P"
    assert body["parameters"]["ratio"] == "16:9"
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
    _bind(monkeypatch, "wan2.7-r2v", captured)

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


@pytest.mark.parametrize("mode", ["t2v", "i2v", "r2v"])
def test_wan3_all_in_one_payload_uses_official_shared_parameters(
    monkeypatch,
    mode,
) -> None:
    captured: dict = {}
    _bind(monkeypatch, "wan3.0-video", captured)
    kwargs = {
        "mode": mode,
        "ratio": "adaptive",
        "duration": 30,
        "resolution": "480p",
        "generate_audio": False,
    }
    if mode == "i2v":
        kwargs["first_frame_url"] = "/generated/storyboard.png"
    elif mode == "r2v":
        kwargs["reference_image_url_list"] = [
            "/generated/storyboard.png",
            "/generated/anchor.png",
        ]

    asyncio.run(video_model.submit_video_task("镜头缓慢推进", **kwargs))

    body = captured["body"]
    assert body["model"] == "wan3.0-video"
    assert body["parameters"] == {
        "resolution": "480P",
        "ratio": "adaptive",
        "watermark": False,
        "duration": 30,
        "audio": False,
        "prompt_extend": True,
    }
    assert body["parameters"]["prompt_extend"] is True


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"duration": 31}, "duration must"),
        ({"resolution": "4K"}, "resolution must"),
        ({"ratio": "21:9"}, "ratio must"),
    ],
)
def test_wan3_rejects_unsupported_parameters_before_submission(
    monkeypatch,
    kwargs,
    message,
) -> None:
    _bind(monkeypatch, "wan3.0-video")
    with pytest.raises(ModelError, match=message):
        asyncio.run(
            video_model.submit_video_task(
                "prompt",
                mode="t2v",
                **kwargs,
            ),
        )


def test_happyhorse_rejects_video_reference(monkeypatch) -> None:
    _bind(monkeypatch, "happyhorse-1.1-r2v")

    async def fake_resolve(url: str, backend: str):
        del url, backend
        return "oss://dashscope-instant/clip.mp4", "video"

    monkeypatch.setattr(
        video_model,
        "_resolve_reference_media_url",
        fake_resolve,
    )

    with pytest.raises(ModelError, match="不支持参考视频"):
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
    _bind(monkeypatch, "happyhorse-1.1-r2v")

    with pytest.raises(ModelError, match="至少需要 1 个参考图像或参考视频"):
        asyncio.run(
            video_model.submit_video_task(
                "prompt",
                ratio="16:9",
                duration=5,
                resolution="720P",
            ),
        )

    too_many = [f"/generated/ref-{index}.png" for index in range(10)]
    with pytest.raises(ModelError, match="参考图像最多 9"):
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
    _bind(monkeypatch, "happyhorse-1.1-r2v")

    for match, kwargs in (
        (
            "resolution must be one of",
            {"ratio": "16:9", "duration": 5, "resolution": "480P"},
        ),
        (
            "ratio must be one of",
            {"ratio": "auto", "duration": 5, "resolution": "720P"},
        ),
        (
            "duration must be an integer",
            {"ratio": "16:9", "duration": 2, "resolution": "720P"},
        ),
    ):
        with pytest.raises(ModelError, match=match):
            asyncio.run(
                video_model.submit_video_task(
                    "prompt",
                    reference_image_url="/generated/ref.png",
                    **kwargs,
                ),
            )


# ---------------------------------------------------------------------------
# Reference media transport
# ---------------------------------------------------------------------------


def _png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (8, 8), color="red").save(output, format="PNG")
    return output.getvalue()


def test_seedance_reference_media_becomes_base64_data_url(
    monkeypatch,
    tmp_path,
) -> None:
    image = tmp_path / "ref.png"
    image.write_bytes(_png_bytes())
    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: "seedance-2.0",
    )

    url, kind = asyncio.run(
        video_model._resolve_reference_media_url(image.as_uri(), "seedance2"),
    )

    assert url.startswith("data:image/png;base64,")
    assert kind == "image"


def test_seedance_local_reference_video_is_rejected(
    monkeypatch,
    tmp_path,
) -> None:
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"mp4")
    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: "seedance-2.0",
    )

    with pytest.raises(ModelError, match="public HTTP\\(S\\) URLs"):
        asyncio.run(
            video_model._resolve_reference_media_url(
                clip.as_uri(),
                "seedance2",
            ),
        )


def test_wan_reference_media_uses_dashscope_temp_upload(
    monkeypatch,
    tmp_path,
) -> None:
    image = tmp_path / "ref.png"
    image.write_bytes(_png_bytes())
    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: "wan2.7-r2v",
    )
    monkeypatch.setattr(model_config, "get_video_api_key", lambda: "video-key")

    observed = {}

    async def fake_upload(
        path,
        *,
        api_key: str,
        model_name: str,
        media_type: str,
    ) -> str:
        assert path.read_bytes() == _png_bytes()
        observed["call"] = (path.name, api_key, model_name, media_type)
        return "oss://dashscope-instant/ref.png"

    monkeypatch.setattr(
        video_model,
        "upload_local_file_to_dashscope_temp",
        fake_upload,
    )

    url, kind = asyncio.run(
        video_model._resolve_reference_media_url(image.as_uri(), "wan"),
    )

    assert url == "oss://dashscope-instant/ref.png"
    assert kind == "image"
    assert observed["call"] == (
        "ref.png",
        "video-key",
        "wan2.7-r2v",
        "image/png",
    )


# ---------------------------------------------------------------------------
# Official reference-media capability table (fail-closed)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("model_name", "expected", "duration_budget"),
    [
        ("happyhorse-1.1-r2v", (9, 0, 9), (None, None)),
        ("wan3.0-video", (10, 5, 15), (15, 30)),
        ("wan2.7-r2v-2026-06-12", (5, 5, 5), (None, None)),
        ("wan2.6-r2v-flash", (5, 3, 5), (None, None)),
        ("doubao-seedance-2-0-260128", (9, 3, 12), (None, None)),
    ],
)
def test_video_reference_capabilities_follow_official_model_limits(
    model_name,
    expected,
    duration_budget,
) -> None:
    capability = video_reference_capability(model_name)

    assert capability is not None
    assert (
        capability.max_reference_images,
        capability.max_reference_videos,
        capability.max_reference_media,
    ) == expected
    assert (
        capability.max_reference_video_duration_seconds,
        capability.max_input_output_duration_seconds,
    ) == duration_budget
    assert capability.documentation_url.startswith("https://")

    # Unknown aliases must stay unknown instead of inheriting Wan guesses.
    assert video_reference_capability("") is None
    assert video_reference_capability("private-video-gateway") is None
    assert video_reference_capability("wan2.8-r2v") is None


@pytest.mark.parametrize(
    ("model_name", "backend", "references", "message"),
    [
        (
            "wan2.7-r2v",
            "wan",
            [f"https://cdn.test/image-{index}.png" for index in range(6)],
            "参考图像最多 5",
        ),
        (
            "wan2.6-r2v",
            "wan",
            [f"https://cdn.test/video-{index}.mp4" for index in range(4)],
            "参考视频最多 3",
        ),
        (
            "doubao-seedance-2-0-260128",
            "seedance2",
            [f"https://cdn.test/video-{index}.mp4" for index in range(4)],
            "参考视频最多 3",
        ),
    ],
)
def test_provider_rejects_video_reference_overflow_before_upload(
    monkeypatch,
    model_name,
    backend,
    references,
    message,
) -> None:
    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: model_name,
    )
    monkeypatch.setattr(model_config, "get_video_backend", lambda: backend)
    monkeypatch.setattr(model_config, "get_video_api_key", lambda: "sk-test")

    async def unexpected_upload(*_args, **_kwargs):
        raise AssertionError("reference upload must not run")

    monkeypatch.setattr(
        video_model,
        "_resolve_reference_media_url",
        unexpected_upload,
    )

    with pytest.raises(ModelError, match=message):
        asyncio.run(
            video_model.submit_video_task(
                "prompt",
                reference_image_url_list=references,
            ),
        )


def test_provider_fails_closed_for_unknown_video_model_alias(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: "private-video-gateway",
    )
    monkeypatch.setattr(model_config, "get_video_backend", lambda: "wan")
    monkeypatch.setattr(model_config, "get_video_api_key", lambda: "sk-test")

    with pytest.raises(ModelError, match="VIDEO_MODEL_CAPABILITY_UNKNOWN"):
        asyncio.run(
            video_model.submit_video_task(
                "prompt",
                reference_image_url="https://cdn.test/reference.png",
            ),
        )


def test_wan_remote_reference_passes_through_public_url(monkeypatch) -> None:
    """Public HTTP(S) media is no longer downloaded and re-uploaded.

    DashScope resolves it server-side via X-DashScope-OssResourceResolve,
    which keeps Token Plan API keys (no uploads endpoint access) working.
    """
    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: "wan2.7-r2v",
    )
    monkeypatch.setattr(model_config, "get_video_api_key", lambda: "video-key")

    url, kind = asyncio.run(
        video_model._resolve_reference_media_url(
            "https://public.example/remote.mp4",
            "wan",
        ),
    )

    assert url == "https://public.example/remote.mp4"
    assert kind == "video"
