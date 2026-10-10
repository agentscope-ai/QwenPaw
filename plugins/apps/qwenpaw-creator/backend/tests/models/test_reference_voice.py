# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access
"""Reference voice (enrolled character voice) riding along R2V references.

Provider HTTP traffic is stubbed; no real model is ever called.
"""

from __future__ import annotations

import asyncio
from array import array
from contextlib import asynccontextmanager
import math
from pathlib import Path
import wave

import pytest

from models import config as model_config
from models import video_model
from models.reference_audio import wan_voice_excerpt
from models.video_capabilities import (
    REFERENCE_VOICE_PER_MEDIA,
    REFERENCE_VOICE_STANDALONE,
    video_reference_voice_support,
)
from services.runtime_files.runtime_dependencies import resolve_ffmpeg
from utils.exceptions import ModelError


class _FakeResponse:
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"output": {"task_id": "task-voice-1"}}


class _FakeAsyncClient:
    def __init__(self, captured: dict):
        self._captured = captured

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    async def post(self, url, headers=None, json=None):
        self._captured["url"] = url
        self._captured["headers"] = headers
        self._captured["body"] = json
        return _FakeResponse()


def _bind(
    monkeypatch,
    model: str,
    captured: dict,
    *,
    backend: str = "wan",
) -> None:
    monkeypatch.setattr(model_config, "get_video_model_name", lambda: model)
    monkeypatch.setattr(model_config, "get_video_backend", lambda: backend)
    monkeypatch.setattr(model_config, "get_video_api_key", lambda: "sk-test")
    monkeypatch.setattr(
        model_config,
        "get_video_submit_url",
        lambda: "https://provider.example/video-synthesis",
    )
    monkeypatch.setattr(model_config, "get_video_submit_timeout", lambda: 5)

    async def fake_resolve(url: str, _backend: str):
        name = url.rsplit("/", 1)[-1]
        if name.endswith((".mp3", ".wav")):
            kind = "audio"
        elif name.endswith((".mp4", ".mov")):
            kind = "video"
        else:
            kind = "image"
        return f"resolved://{name}", kind

    monkeypatch.setattr(
        video_model,
        "_resolve_reference_media_url",
        fake_resolve,
    )

    @asynccontextmanager
    async def fake_excerpt(url, *, voice_count):
        captured.setdefault("excerpt_counts", []).append(voice_count)
        yield url

    monkeypatch.setattr(video_model, "wan_voice_excerpt", fake_excerpt)
    monkeypatch.setattr(
        video_model.httpx,
        "AsyncClient",
        lambda timeout: _FakeAsyncClient(captured),
    )


# ── capability table ─────────────────────────────────────────────────────────


def test_reference_voice_support_matches_official_contracts() -> None:
    assert video_reference_voice_support("wan2.7-r2v") == (
        REFERENCE_VOICE_PER_MEDIA,
        5,
    )
    assert video_reference_voice_support("wan2.7-r2v-2026-06-12") == (
        REFERENCE_VOICE_PER_MEDIA,
        5,
    )
    assert video_reference_voice_support("wan3.0-video") == (
        REFERENCE_VOICE_STANDALONE,
        5,
    )
    assert video_reference_voice_support(
        "doubao-seedance-2-5-260628",
        "seedance2",
    ) == (REFERENCE_VOICE_STANDALONE, 10)
    assert video_reference_voice_support(
        "doubao-seedance-2-0-260128",
        "seedance2",
    ) == (REFERENCE_VOICE_STANDALONE, 3)
    # Families whose contracts document no audio input.
    assert video_reference_voice_support("wan2.6-r2v") is None
    assert video_reference_voice_support("happyhorse-1.1-r2v") is None
    assert (
        video_reference_voice_support(
            "kling/kling-v3-omni-video-generation",
        )
        is None
    )
    assert video_reference_voice_support("") is None


# ── request-body shapes ──────────────────────────────────────────────────────


def _submit(monkeypatch, model, *, backend="wan"):
    captured: dict = {}
    _bind(monkeypatch, model, captured, backend=backend)
    asyncio.run(
        video_model.submit_video_task(
            prompt="两个角色对话",
            reference_image_url_list=[
                "https://cdn.example/rusty.png",
                "https://cdn.example/scene.png",
            ],
            reference_voice_urls=["https://cdn.example/rusty-voice.mp3", ""],
            ratio="16:9",
            duration=5,
            resolution="720P",
        ),
    )
    return captured["body"]


def test_request_body_shape_per_family(monkeypatch) -> None:
    # wan2.7: voice rides on its subject media entry; voiceless refs carry
    # no reference_voice key at all.
    media = _submit(monkeypatch, "wan2.7-r2v")["input"]["media"]
    assert media[0] == {
        "type": "reference_image",
        "url": "resolved://rusty.png",
        "reference_voice": "resolved://rusty-voice.mp3",
    }
    assert media[1] == {
        "type": "reference_image",
        "url": "resolved://scene.png",
    }
    # wan3.0: standalone reference_audio entries, never per-media keys.
    body = _submit(monkeypatch, "wan3.0-video")
    media = body["input"]["media"]
    assert {
        "type": "reference_audio",
        "url": "resolved://rusty-voice.mp3",
    } in media
    assert all("reference_voice" not in item for item in media)
    assert "图1中的角色使用音频1的音色" in body["input"]["prompt"]
    assert "不复述试听样本" in body["input"]["prompt"]
    # seedance: audio becomes audio_url content items.
    body = _submit(
        monkeypatch,
        "doubao-seedance-2-0-260128",
        backend="seedance2",
    )
    audio_items = [
        item for item in body["content"] if item["type"] == "audio_url"
    ]
    assert audio_items == [
        {
            "type": "audio_url",
            "role": "reference_audio",
            "audio_url": {"url": "resolved://rusty-voice.mp3"},
        },
    ]
    # Families without documented audio input silently drop voices.
    media = _submit(monkeypatch, "happyhorse-1.1-r2v")["input"]["media"]
    assert all(item["type"] == "reference_image" for item in media)
    assert all("reference_voice" not in item for item in media)


def test_audio_urls_are_rejected_as_plain_references(monkeypatch) -> None:
    # An audio URL counts as neither image nor video, so the pre-upload
    # budget check already fails the request before any transport happens;
    # the in-loop guard stays as defence in depth.
    captured: dict = {}
    _bind(monkeypatch, "wan2.7-r2v", captured)
    with pytest.raises(Exception) as excinfo:
        asyncio.run(
            video_model.submit_video_task(
                prompt="x",
                reference_image_url_list=["https://cdn.example/voice.mp3"],
                ratio="16:9",
                duration=5,
                resolution="720P",
            ),
        )
    assert "VIDEO_REFERENCE_BUDGET_EXCEEDED" in str(excinfo.value)
    assert captured.get("body") is None


def test_voice_mapping_and_budget_follow_deduplicated_wire_order(monkeypatch):
    captured = {}
    _bind(monkeypatch, "wan3.0-video", captured)
    asyncio.run(
        video_model.submit_video_task(
            prompt="两个角色轮流说话",
            reference_image_url_list=[
                "https://cdn.example/storyboard.png",
                "https://cdn.example/rusty.png",
                "https://cdn.example/rusty.png",
                "https://cdn.example/friend.png",
                "https://cdn.example/rusty-closeup.png",
            ],
            reference_voice_urls=[
                "",
                "https://cdn.example/rusty.mp3",
                "https://cdn.example/rusty.mp3",
                "https://cdn.example/friend.wav",
                "https://cdn.example/rusty.mp3",
            ],
            ratio="16:9",
            duration=5,
            resolution="720P",
        ),
    )
    body = captured["body"]["input"]
    assert [
        m["url"] for m in body["media"] if m["type"] == "reference_audio"
    ] == [
        "resolved://rusty.mp3",
        "resolved://friend.wav",
    ]
    assert captured["excerpt_counts"] == [2, 2]
    assert "图2中的角色使用音频1的音色" in body["prompt"]
    assert "图3中的角色使用音频2的音色" in body["prompt"]
    assert "图4中的角色使用音频1的音色" in body["prompt"]
    assert "图1中的角色使用" not in body["prompt"]

    captured.clear()
    with pytest.raises(ModelError, match="at most 5"):
        asyncio.run(
            video_model.submit_video_task(
                prompt="六个说话者",
                reference_image_url_list=[
                    f"https://cdn.example/{i}.png" for i in range(6)
                ],
                reference_voice_urls=[
                    f"https://cdn.example/{i}.wav" for i in range(6)
                ],
                ratio="16:9",
                duration=5,
                resolution="720P",
            ),
        )
    assert "body" not in captured


@pytest.mark.parametrize("voice_count", [1, 2, 5])
def test_voice_excerpt_decodes_and_fits_total_budget(tmp_path, voice_count):
    if not resolve_ffmpeg():
        pytest.skip("FFmpeg is required for the real media boundary probe")
    source = tmp_path / "voice.wav"
    samples = array("h", [0] * 16000)
    samples.extend(
        int(10000 * math.sin(i * math.tau * 220 / 8000)) for i in range(160000)
    )
    with wave.open(str(source), "wb") as audio:
        audio.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        audio.writeframes(samples.tobytes())
    original = source.read_bytes()

    async def inspect():
        async with wan_voice_excerpt(
            source.as_uri(),
            voice_count=voice_count,
        ) as url:
            excerpt = Path(url.removeprefix("file://"))
            with wave.open(str(excerpt), "rb") as audio:
                seconds = audio.getnframes() / audio.getframerate()
                assert audio.getframerate() == 24000
                assert audio.getnchannels() == 1
                assert 1 <= seconds <= 15 / voice_count
                assert seconds == pytest.approx(14.5 / voice_count, abs=0.03)
                assert any(audio.readframes(2400))  # leading silence removed
        assert not excerpt.exists()

    asyncio.run(inspect())
    assert source.read_bytes() == original

    # A silent audition must not become a nominally valid empty sample.
    with wave.open(str(source), "wb") as audio:
        audio.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        audio.writeframes(bytes(32000))
    with pytest.raises(ModelError, match="at least 1 second"):
        asyncio.run(inspect())
