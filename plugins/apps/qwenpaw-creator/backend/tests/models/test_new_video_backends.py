# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access
"""New video backends: Veo, MiniMax, and Kling / Vidu (both the official
channels and the Bailian-hosted DashScope variants).

Provider HTTP traffic is stubbed; every asserted parameter mirrors the
official API references quoted in the backend modules.
"""

from __future__ import annotations

import asyncio
import base64

import pytest

from models import config as model_config
from models import video_model
from models.video_backends import kling as kling_backend
from models.video_backends import minimax as minimax_backend
from models.video_backends import veo as veo_backend
from models.video_backends import vidu as vidu_backend
from models.video_capabilities import video_reference_capability
from utils.exceptions import ModelError

pytestmark = pytest.mark.unit

_PNG_B64 = base64.b64encode(b"\x89PNG fake").decode()
_DATA_URL = f"data:image/png;base64,{_PNG_B64}"


class _StubResponse:
    status_code = 200

    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    """Captures the submit POST and answers a Bailian-style task id."""

    def __init__(self, captured: dict, payload: dict | None = None):
        self._captured = captured
        self._payload = payload or {"output": {"task_id": "task-1"}}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, headers=None, json=None):
        self._captured.update({"url": url, "headers": headers, "body": json})
        return _StubResponse(self._payload)

    async def get(self, url, params=None, headers=None):
        self._captured.update(
            {"url": url, "params": params, "headers": headers},
        )
        return _StubResponse(self._payload)


def _bind(
    monkeypatch,
    model: str,
    captured: dict,
    backend: str = "wan",
    payload: dict | None = None,
):
    monkeypatch.setattr(model_config, "get_video_model_name", lambda: model)
    monkeypatch.setattr(model_config, "get_video_backend", lambda: backend)
    monkeypatch.setattr(model_config, "get_video_api_key", lambda: "sk-test")
    monkeypatch.setattr(
        model_config,
        "get_video_base_url",
        lambda: "https://provider.example",
    )
    monkeypatch.setattr(
        model_config,
        "get_video_submit_url",
        lambda: "https://bailian.example/video-synthesis",
    )
    monkeypatch.setattr(model_config, "get_video_submit_timeout", lambda: 5)

    async def fake_resolve(url: str, _backend: str):
        name = url.rsplit("/", 1)[-1]
        kind = "video" if name.endswith((".mp4", ".mov")) else "image"
        if _backend == "wan":
            return f"oss://dashscope-instant/{name}", kind
        return (url if url.startswith("http") else _DATA_URL), kind

    monkeypatch.setattr(
        video_model,
        "_resolve_reference_media_url",
        fake_resolve,
    )
    monkeypatch.setattr(
        video_model.httpx,
        "AsyncClient",
        lambda timeout: _FakeAsyncClient(captured, payload),
    )


# ── capability table ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("model_name", "expected"),
    [
        ("doubao-seedance-2-5-260628", (30, 10, 40)),
        ("veo-3.1-generate-preview", (3, 0, 3)),
        ("veo-3.1-lite-generate-preview", (0, 0, 0)),
        ("kling/kling-v3-omni-video-generation", (7, 1, 7)),
        ("kling-3.0-omni", (7, 1, 7)),  # official channel
        ("kling/kling-v3-video-generation", None),  # no refer support
        ("kling-2.6", None),
        ("S2V-01", (1, 0, 1)),
        ("MiniMax-Hailuo-2.3", None),
        ("vidu/viduq3-mix_reference2video", (7, 0, 7)),
        ("vidu/viduq2-pro_reference2video", (7, 2, 7)),
        ("viduq3-mix", (7, 0, 7)),  # official channel
        ("viduq2-pro", (7, 2, 7)),
    ],
)
def test_video_reference_capabilities(model_name, expected) -> None:
    capability = video_reference_capability(model_name)
    if expected is None:
        assert capability is None
    else:
        assert (
            capability.max_reference_images,
            capability.max_reference_videos,
            capability.max_reference_media,
        ) == expected


# ── Veo ──────────────────────────────────────────────────────────────────────


def _veo_submit(**overrides):
    kwargs = {
        "prompt": "a drone shot",
        "mode": "t2v",
        "media": [],
        "ratio": "16:9",
        "duration": 8,
        "resolution": "720p",
        "model_name": "veo-3.1-generate-preview",
        "api_key": "gm-key",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
    }
    kwargs.update(overrides)
    return veo_backend.build_submit_request(**kwargs)


def test_veo_request_shapes() -> None:
    url, headers, body = _veo_submit(duration=6)
    assert url.endswith("/models/veo-3.1-generate-preview:predictLongRunning")
    assert headers["x-goog-api-key"] == "gm-key"
    assert body["instances"] == [{"prompt": "a drone shot"}]
    assert body["parameters"] == {
        "aspectRatio": "16:9",
        "resolution": "720p",
        "durationSeconds": "6",
    }
    # i2v inlines the first frame; r2v carries asset referenceImages.
    _, _, body = _veo_submit(
        mode="i2v",
        media=[{"type": "first_frame", "url": _DATA_URL}],
    )
    assert body["instances"][0]["image"] == {
        "inlineData": {"mimeType": "image/png", "data": _PNG_B64},
    }
    _, _, body = _veo_submit(
        mode="r2v",
        media=[{"type": "reference_image", "url": _DATA_URL}] * 2,
    )
    references = body["instances"][0]["referenceImages"]
    assert len(references) == 2
    assert references[0]["referenceType"] == "asset"


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"duration": 5}, "must be one of"),
        (
            {
                "mode": "r2v",
                "duration": 4,
                "media": [{"type": "reference_image", "url": _DATA_URL}],
            },
            "must be 8",
        ),
        ({"duration": 6, "resolution": "1080p"}, "must be 8"),
        ({"ratio": "1:1"}, "aspectRatio"),
        (
            {
                "model_name": "veo-3.1-lite-generate-preview",
                "resolution": "4k",
            },
            "4k",
        ),
    ],
)
def test_veo_constraints(overrides, match) -> None:
    with pytest.raises(ModelError, match=match):
        _veo_submit(**overrides)


def test_veo_check_status_keeps_download_key_out_of_durable_result(
    monkeypatch,
) -> None:
    payload = {
        "done": True,
        "response": {
            "generateVideoResponse": {
                "generatedSamples": [
                    {"video": {"uri": "https://dl.example/video.mp4"}},
                ],
            },
        },
    }
    captured: dict = {}
    monkeypatch.setattr(
        veo_backend.httpx,
        "AsyncClient",
        lambda timeout: _FakeAsyncClient(captured, payload),
    )
    result = asyncio.run(
        veo_backend.check_status(
            "models/veo-3.1-generate-preview/operations/op-1",
            api_key="gm-key",
            base_url="https://generativelanguage.googleapis.com/v1beta",
            timeout=10,
            model_name="veo-3.1-generate-preview",
        ),
    )
    assert result["status"] == "SUCCEEDED"
    assert result["result_url"] == "https://dl.example/video.mp4"
    assert result["download_auth"] == "x-goog-api-key"
    assert "gm-key" not in repr(result)


# ── MiniMax ──────────────────────────────────────────────────────────────────


def _minimax_submit(**overrides):
    kwargs = {
        "prompt": "a man rides a horse",
        "mode": "t2v",
        "media": [],
        "duration": 6,
        "resolution": "1080P",
        "model_name": "MiniMax-Hailuo-2.3",
        "api_key": "mm-key",
        "base_url": "https://api.minimax.io",
    }
    kwargs.update(overrides)
    return minimax_backend.build_submit_request(**kwargs)


def test_minimax_request_shapes() -> None:
    url, headers, body = _minimax_submit()
    assert url == "https://api.minimax.io/v1/video_generation"
    assert headers["Authorization"] == "Bearer mm-key"
    assert body == {
        "model": "MiniMax-Hailuo-2.3",
        "prompt": "a man rides a horse",
        "duration": 6,
        "resolution": "1080P",
    }
    _, _, body = _minimax_submit(
        mode="i2v",
        media=[{"type": "first_frame", "url": _DATA_URL}],
        resolution="768P",
    )
    assert body["first_frame_image"] == _DATA_URL
    _, _, body = _minimax_submit(
        model_name="MiniMax-Hailuo-02",
        resolution="512P",
        duration=10,
    )
    assert body["resolution"] == "512P"
    _, _, body = _minimax_submit(
        mode="r2v",
        model_name="S2V-01",
        resolution="720P",
        media=[
            {"type": "reference_image", "url": "https://cdn.example/c.png"},
        ],
    )
    assert body["subject_reference"] == [
        {"type": "character", "image": ["https://cdn.example/c.png"]},
    ]
    assert "duration" not in body
    assert "resolution" not in body


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        # 768P allows 6/10s; 1080P allows 6s only; 01-gen is 720P at 6s.
        ({"duration": 10, "resolution": "1080P"}, "1080P"),
        (
            {"model_name": "T2V-01", "resolution": "768P", "duration": 6},
            "720P",
        ),
        ({"prompt": "x" * 2001}, "2000"),
        (
            {
                "mode": "r2v",
                "media": [{"type": "reference_image", "url": _DATA_URL}],
            },
            "不支持 mode=r2v",
        ),
        (
            {"model_name": "MiniMax-Hailuo-2.3-Fast", "mode": "t2v"},
            "不支持 mode=t2v",
        ),
    ],
)
def test_minimax_constraints(overrides, match) -> None:
    with pytest.raises(ModelError, match=match):
        _minimax_submit(**overrides)


# ── Kling: Bailian hosting & official channel ────────────────────────────────


def test_kling_bailian_r2v_payload(monkeypatch) -> None:
    captured: dict = {}
    _bind(monkeypatch, "kling/kling-v3-omni-video-generation", captured)
    task_id = asyncio.run(
        video_model.submit_video_task(
            "<<<image_1>>>中的角色向前走",
            reference_image_url="/generated/anchor.png",
            reference_image_url_list=["/generated/motion.mp4"],
            ratio="16:9",
            duration=10,
            resolution="1080p",
        ),
    )
    assert task_id == "task-1"
    body = captured["body"]
    assert body["model"] == "kling/kling-v3-omni-video-generation"
    media_types = sorted(item["type"] for item in body["input"]["media"])
    assert media_types == ["feature", "refer"]
    # resolution maps onto the documented mode tiers (1080p -> pro); the
    # official contract forbids audio with a reference video.
    assert body["parameters"] == {
        "mode": "pro",
        "duration": 10,
        "audio": False,
        "watermark": False,
        "aspect_ratio": "16:9",
    }
    assert captured["headers"]["X-DashScope-Async"] == "enable"

    with pytest.raises(ModelError, match="3 and 10 seconds"):
        asyncio.run(
            video_model.submit_video_task(
                "<<<video_1>>>",
                reference_image_url="/generated/anchor.png",
                reference_image_url_list=["/generated/motion.mp4"],
                ratio="16:9",
                duration=12,
                resolution="720p",
            ),
        )


def test_kling_direct_request_shapes(monkeypatch) -> None:
    captured: dict = {}
    _bind(
        monkeypatch,
        "kling-3.0-omni",
        captured,
        backend="kling",
        payload={"code": 0, "data": {"id": "task-1"}},
    )
    asyncio.run(
        video_model.submit_video_task(
            "@image_1 中的角色向前走",
            reference_image_url="/generated/anchor.png",
            ratio="16:9",
            duration=8,
            resolution="1080p",
        ),
    )
    assert captured["url"] == (
        "https://provider.example/omni-video/kling-3.0-omni"
    )
    assert captured["headers"]["Authorization"] == "Bearer sk-test"
    body = captured["body"]
    contents = body["contents"]
    assert contents[0] == {"type": "prompt", "text": "@image_1 中的角色向前走"}
    # Inlined local media is sent as bare Base64 (no data: prefix).
    assert contents[1] == {
        "type": "refer_image",
        "url": _PNG_B64,
        "id": "image_1",
    }
    assert body["settings"] == {
        "resolution": "1080p",
        "duration": 8,
        "audio": "native",
        "multi_shot": False,
        "aspect_ratio": "16:9",
    }
    assert body["options"] == {"watermark_info": {"enabled": False}}

    # kling-2.6 serves t2v/i2v only, at 5s or 10s.
    _bind(
        monkeypatch,
        "kling-2.6",
        captured,
        backend="kling",
        payload={"code": 0, "data": {"id": "task-1"}},
    )
    asyncio.run(
        video_model.submit_video_task(
            "一只小猫在雨夜的街头奔跑",
            mode="t2v",
            ratio="16:9",
            duration=10,
            resolution="720p",
        ),
    )
    assert (
        captured["url"] == "https://provider.example/text-to-video/kling-2.6"
    )
    assert captured["body"]["prompt"] == "一只小猫在雨夜的街头奔跑"
    # r2v on kling-2.6 is blocked by the capability gate before any
    # upload (no registered reference contract for the model).
    with pytest.raises(ModelError, match="不支持 mode=r2v"):
        asyncio.run(
            video_model.submit_video_task(
                "prompt",
                reference_image_url="/generated/anchor.png",
                ratio="16:9",
                duration=10,
                resolution="720p",
            ),
        )
    with pytest.raises(ModelError, match="duration must be one of"):
        asyncio.run(
            video_model.submit_video_task(
                "prompt",
                mode="t2v",
                ratio="16:9",
                duration=7,
                resolution="720p",
            ),
        )


def test_kling_direct_check_status(monkeypatch) -> None:
    captured: dict = {}
    payload = {
        "code": 0,
        "data": [
            {
                "status": "succeeded",
                "outputs": [
                    {"type": "video", "url": "https://dl.kling/video.mp4"},
                ],
            },
        ],
    }
    monkeypatch.setattr(
        kling_backend.httpx,
        "AsyncClient",
        lambda timeout: _FakeAsyncClient(captured, payload),
    )
    result = asyncio.run(
        kling_backend.check_status(
            "task-9",
            api_key="k",
            base_url="https://api-singapore.klingai.com",
            timeout=10,
            model_name="kling-3.0-omni",
        ),
    )
    assert result["status"] == "SUCCEEDED"
    assert result["result_url"] == "https://dl.kling/video.mp4"
    assert captured["params"] == {"task_ids": "task-9"}


# ── Vidu: Bailian hosting & official channel ─────────────────────────────────


def test_vidu_bailian_r2v_payload(monkeypatch) -> None:
    captured: dict = {}
    _bind(monkeypatch, "vidu/viduq3-mix_reference2video", captured)
    asyncio.run(
        video_model.submit_video_task(
            "男人坐在靠窗的椅子上弹吉他",
            reference_image_url="/generated/role.png",
            reference_image_url_list=["/generated/scene.png"],
            ratio="16:9",
            duration=5,
            resolution="720p",
        ),
    )
    body = captured["body"]
    assert body["input"]["media"] == [
        {"type": "image", "url": "oss://dashscope-instant/role.png"},
        {"type": "image", "url": "oss://dashscope-instant/scene.png"},
    ]
    # Official 720P/16:9 size from the Bailian tier table.
    assert body["parameters"] == {
        "duration": 5,
        "resolution": "720P",
        "size": "1280*720",
        "watermark": False,
        "audio": True,
    }
    # viduq3-drama only documents 16:9 and 9:16.
    _bind(monkeypatch, "vidu/viduq3-drama_reference2video", captured)
    with pytest.raises(ModelError, match="aspect ratios"):
        asyncio.run(
            video_model.submit_video_task(
                "prompt",
                reference_image_url="/generated/role.png",
                ratio="1:1",
                duration=5,
                resolution="1080p",
            ),
        )


def test_vidu_direct_request_shape(monkeypatch) -> None:
    captured: dict = {}
    _bind(
        monkeypatch,
        "viduq3-mix",
        captured,
        backend="vidu",
        payload={"task_id": "task-1", "state": "created"},
    )
    asyncio.run(
        video_model.submit_video_task(
            "Santa Claus and the bear hug by the lakeside.",
            reference_image_url="/generated/role.png",
            reference_image_url_list=["https://cdn.example/scene.png"],
            ratio="16:9",
            duration=5,
            resolution="720p",
        ),
    )
    assert captured["url"] == "https://provider.example/ent/v2/reference2video"
    assert captured["headers"]["Authorization"] == "Token sk-test"
    body = captured["body"]
    assert body["model"] == "viduq3-mix"
    # Local media rides as a data URL; public URLs pass through.
    assert body["images"] == [_DATA_URL, "https://cdn.example/scene.png"]
    assert body["duration"] == 5
    assert body["resolution"] == "720p"
    assert body["aspect_ratio"] == "16:9"
    assert body["audio"] is True
    assert "videos" not in body

    # viduq3-mix supports 720p/1080p only.
    with pytest.raises(ModelError, match="resolutions"):
        asyncio.run(
            video_model.submit_video_task(
                "prompt",
                reference_image_url="/generated/role.png",
                ratio="16:9",
                duration=5,
                resolution="540p",
            ),
        )


def test_vidu_direct_uses_mode_specific_endpoints(monkeypatch) -> None:
    captured: dict = {}
    _bind(
        monkeypatch,
        "viduq3-turbo",
        captured,
        backend="vidu",
        payload={"task_id": "task-t2v", "state": "created"},
    )
    asyncio.run(
        video_model.submit_video_task(
            "A paper boat crosses a puddle.",
            mode="t2v",
            ratio="9:16",
            duration=5,
            resolution="720p",
        ),
    )
    assert captured["url"] == "https://provider.example/ent/v2/text2video"
    assert captured["body"] == {
        "model": "viduq3-turbo",
        "prompt": "A paper boat crosses a puddle.",
        "duration": 5,
        "resolution": "720p",
        "aspect_ratio": "9:16",
        "audio": True,
    }

    captured.clear()
    _bind(
        monkeypatch,
        "viduq2-pro",
        captured,
        backend="vidu",
        payload={"task_id": "task-i2v", "state": "created"},
    )
    asyncio.run(
        video_model.submit_video_task(
            "The subject turns toward camera.",
            mode="i2v",
            first_frame_url="/generated/first.png",
            ratio="1:1",
            duration=5,
            resolution="720p",
        ),
    )
    assert captured["url"] == "https://provider.example/ent/v2/img2video"
    assert captured["body"]["images"] == [_DATA_URL]
    assert "aspect_ratio" not in captured["body"]
    assert "audio" not in captured["body"]

    captured.clear()
    _bind(
        monkeypatch,
        "viduq2-pro",
        captured,
        backend="vidu",
        payload={"task_id": "task-r2v-video", "state": "created"},
    )
    asyncio.run(
        video_model.submit_video_task(
            "Follow the motion of the reference performer.",
            mode="r2v",
            reference_image_url_list=["https://cdn.example/motion.mp4"],
            ratio="16:9",
            duration=5,
            resolution="720p",
        ),
    )
    assert captured["url"].endswith("/ent/v2/reference2video")
    assert captured["body"]["videos"] == [
        "https://cdn.example/motion.mp4",
    ]
    assert captured["body"]["images"] == []


def test_vidu_direct_check_status(monkeypatch) -> None:
    captured: dict = {}
    payload = {
        "state": "success",
        "err_code": "",
        "creations": [{"id": "c1", "url": "https://dl.vidu/video.mp4"}],
    }
    monkeypatch.setattr(
        vidu_backend.httpx,
        "AsyncClient",
        lambda timeout: _FakeAsyncClient(captured, payload),
    )
    result = asyncio.run(
        vidu_backend.check_status(
            "task-3",
            api_key="k",
            base_url="https://api.vidu.com",
            timeout=10,
            model_name="viduq3-mix",
        ),
    )
    assert result["status"] == "SUCCEEDED"
    assert result["result_url"] == "https://dl.vidu/video.mp4"
    assert (
        captured["url"] == "https://api.vidu.com/ent/v2/tasks/task-3/creations"
    )
