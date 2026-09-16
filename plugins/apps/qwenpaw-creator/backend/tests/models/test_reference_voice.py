# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access
"""Reference voice (enrolled character voice) riding along R2V references.

Provider HTTP traffic is stubbed; no real model is ever called.
"""

from __future__ import annotations

import asyncio

import pytest

from models import config as model_config
from models import video_model
from models.video_capabilities import (
    REFERENCE_VOICE_PER_MEDIA,
    REFERENCE_VOICE_STANDALONE,
    video_reference_voice_support,
)


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
    media = _submit(monkeypatch, "wan3.0-video")["input"]["media"]
    assert {
        "type": "reference_audio",
        "url": "resolved://rusty-voice.mp3",
    } in media
    assert all("reference_voice" not in item for item in media)
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
