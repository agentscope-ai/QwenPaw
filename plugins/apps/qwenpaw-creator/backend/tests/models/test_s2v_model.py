# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access,unused-argument
"""wan2.2-s2v protocol client: detect / submit / poll (all HTTP stubbed)."""

from __future__ import annotations

import asyncio
import io
import json

import httpx
import pytest
import respx
from PIL import Image

from models import config as model_config
from models import s2v_model
from utils.exceptions import ModelError

_BASE = "https://dashscope.test/api/v1"


@pytest.fixture(name="s2v_env")
def _s2v_env(monkeypatch):
    monkeypatch.setenv("S2V_API_KEY", "sk-s2v-test")
    monkeypatch.setenv("S2V_BASE_URL", _BASE)
    monkeypatch.delenv("S2V_MODEL_NAME", raising=False)
    monkeypatch.delenv("S2V_DETECT_MODEL_NAME", raising=False)
    monkeypatch.delenv("CREATOR_DATA_ROOT", raising=False)
    monkeypatch.delenv("CREATOR_MODEL_CONFIG_PATH", raising=False)
    token = model_config.set_request_tool_configs({})
    yield
    model_config.reset_request_tool_configs(token)


def _png_bytes(width: int, height: int) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (width, height), color="blue").save(output, format="PNG")
    return output.getvalue()


# ── configuration gating ─────────────────────────────────────────────────────


def test_is_s2v_configured_gates_on_key(monkeypatch) -> None:
    monkeypatch.delenv("S2V_API_KEY", raising=False)
    monkeypatch.delenv("TEXT_API_KEY", raising=False)
    monkeypatch.delenv("CREATOR_DATA_ROOT", raising=False)
    monkeypatch.delenv("CREATOR_MODEL_CONFIG_PATH", raising=False)
    token = model_config.set_request_tool_configs({})
    try:
        assert model_config.is_s2v_configured() is False
        monkeypatch.setenv("S2V_API_KEY", "sk-test")
        assert model_config.is_s2v_configured() is True
    finally:
        model_config.reset_request_tool_configs(token)


def test_s2v_api_key_falls_back_to_the_text_credential(monkeypatch) -> None:
    """S2V reuses the LLM key by default, mirroring the TTS pattern."""

    monkeypatch.delenv("S2V_API_KEY", raising=False)
    monkeypatch.setenv("TEXT_API_KEY", "sk-shared")
    monkeypatch.delenv("CREATOR_DATA_ROOT", raising=False)
    monkeypatch.delenv("CREATOR_MODEL_CONFIG_PATH", raising=False)
    token = model_config.set_request_tool_configs({})
    try:
        assert model_config.get_s2v_api_key() == "sk-shared"
        assert model_config.is_s2v_configured()
    finally:
        model_config.reset_request_tool_configs(token)


def test_s2v_default_model_names(s2v_env) -> None:
    assert model_config.get_s2v_model_name() == "wan2.2-s2v"
    assert model_config.get_s2v_detect_model_name() == "wan2.2-s2v-detect"


# ── portrait constraints ─────────────────────────────────────────────────────


def test_portrait_dimension_bounds() -> None:
    with pytest.raises(ValueError, match="400-7000px"):
        s2v_model.validate_portrait_image_bytes(_png_bytes(100, 600))
    s2v_model.validate_portrait_image_bytes(_png_bytes(480, 640))
    with pytest.raises(ValueError, match="cannot be decoded"):
        s2v_model.validate_portrait_image_bytes(b"not-an-image")


def test_resolution_normalization(s2v_env) -> None:
    assert s2v_model.normalize_s2v_resolution("480p") == "480P"
    assert s2v_model.normalize_s2v_resolution("") == "480P"
    with pytest.raises(ModelError, match="resolution must be one of"):
        s2v_model.normalize_s2v_resolution("1080P")


def test_local_media_uploads_to_dashscope_temp(
    s2v_env,
    monkeypatch,
    tmp_path,
) -> None:
    portrait = tmp_path / "hero.png"
    portrait.write_bytes(_png_bytes(480, 640))

    async def fake_upload(path, *, api_key, model_name, media_type):
        assert path == portrait
        assert api_key == "sk-s2v-test"
        assert model_name == "wan2.2-s2v"
        assert media_type == "image/png"
        return "oss://dashscope-instant/hero.png"

    monkeypatch.setattr(
        s2v_model,
        "upload_local_file_to_dashscope_temp",
        fake_upload,
    )
    resolved = asyncio.run(
        s2v_model.resolve_s2v_media_url(
            portrait.as_uri(),
            validate_portrait=True,
            model_name="wan2.2-s2v",
        ),
    )
    assert resolved == "oss://dashscope-instant/hero.png"


def test_local_portrait_below_bounds_is_rejected_before_upload(
    s2v_env,
    tmp_path,
) -> None:
    portrait = tmp_path / "small.png"
    portrait.write_bytes(_png_bytes(120, 200))
    with pytest.raises(ModelError, match="400-7000px"):
        asyncio.run(
            s2v_model.resolve_s2v_media_url(
                portrait.as_uri(),
                validate_portrait=True,
                model_name="wan2.2-s2v",
            ),
        )


# ── detect (free, synchronous) ───────────────────────────────────────────────


@respx.mock
def test_detect_face_payload_and_pass(s2v_env) -> None:
    route = respx.post(f"{_BASE}/services/aigc/image2video/face-detect").mock(
        return_value=httpx.Response(
            200,
            json={"output": {"check_pass": True, "humanoid": True}},
        ),
    )
    result = asyncio.run(
        s2v_model.detect_face("https://cdn.test/portrait.png"),
    )
    assert result.passed is True
    assert result.humanoid is True
    assert result.reason == ""
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer sk-s2v-test"
    assert json.loads(request.content) == {
        "model": "wan2.2-s2v-detect",
        "input": {"image_url": "https://cdn.test/portrait.png"},
    }


@respx.mock
def test_detect_face_failure_surfaces_reason(s2v_env) -> None:
    respx.post(f"{_BASE}/services/aigc/image2video/face-detect").mock(
        return_value=httpx.Response(
            200,
            json={
                "output": {
                    "check_pass": False,
                    "humanoid": False,
                    "code": "InvalidFace.SideFace",
                    "message": "side face detected",
                },
            },
        ),
    )
    result = asyncio.run(
        s2v_model.detect_face("https://cdn.test/portrait.png"),
    )
    assert result.passed is False
    assert "InvalidFace.SideFace" in result.reason
    assert "side face detected" in result.reason


@respx.mock
def test_detect_rejection_arrives_as_http_400(s2v_env) -> None:
    """Measured live behaviour: an unusable portrait is a 400, not a 200.

    The verdict must stay a verdict (no billing happened), never a raw
    transport error.
    """

    for code, message in (
        ("InvalidFile.NoHuman", "The input image has no human body."),
        (
            "InvalidFile.BodyProportion",
            "The proportion of the detected person is too large or too small.",
        ),
    ):
        respx.post(f"{_BASE}/services/aigc/image2video/face-detect").mock(
            return_value=httpx.Response(
                400,
                json={"code": code, "message": message, "request_id": "r-1"},
            ),
        )
        result = asyncio.run(
            s2v_model.detect_face("https://cdn.test/portrait.png"),
        )
        assert result.passed is False
        assert code in result.reason
        assert message[:20] in result.reason


@respx.mock
def test_detect_still_raises_on_a_real_bad_request(s2v_env) -> None:
    """A non-portrait 400 (bad key/parameter) is a failure, not a verdict."""

    respx.post(f"{_BASE}/services/aigc/image2video/face-detect").mock(
        return_value=httpx.Response(
            400,
            json={
                "code": "InvalidParameter",
                "message": "image_url is required",
            },
        ),
    )
    with pytest.raises(ModelError, match="InvalidParameter"):
        asyncio.run(s2v_model.detect_face("https://cdn.test/portrait.png"))


# ── submit (billed, async task) ──────────────────────────────────────────────


@respx.mock
def test_submit_payload_shape(s2v_env) -> None:
    route = respx.post(
        f"{_BASE}/services/aigc/image2video/video-synthesis/",
    ).mock(
        return_value=httpx.Response(
            200,
            json={"output": {"task_id": "task-s2v-1"}},
        ),
    )
    task_id = asyncio.run(
        s2v_model.submit_s2v_task(
            "https://cdn.test/portrait.png",
            "https://cdn.test/voice.wav",
            resolution="720P",
        ),
    )
    assert task_id == "task-s2v-1"
    request = route.calls.last.request
    assert request.headers["X-DashScope-Async"] == "enable"
    assert request.headers["X-DashScope-OssResourceResolve"] == "enable"
    assert json.loads(request.content) == {
        "model": "wan2.2-s2v",
        "input": {
            "image_url": "https://cdn.test/portrait.png",
            "audio_url": "https://cdn.test/voice.wav",
        },
        "parameters": {"resolution": "720P"},
    }


def test_submit_requires_audio(s2v_env) -> None:
    with pytest.raises(ModelError, match="audio_url"):
        asyncio.run(
            s2v_model.submit_s2v_task("https://cdn.test/p.png", ""),
        )


def test_submit_requires_api_key(monkeypatch) -> None:
    monkeypatch.delenv("S2V_API_KEY", raising=False)
    monkeypatch.delenv("TEXT_API_KEY", raising=False)
    monkeypatch.delenv("CREATOR_DATA_ROOT", raising=False)
    monkeypatch.delenv("CREATOR_MODEL_CONFIG_PATH", raising=False)
    token = model_config.set_request_tool_configs({})
    try:
        with pytest.raises(ModelError, match="S2V_API_KEY"):
            asyncio.run(
                s2v_model.submit_s2v_task(
                    "https://cdn.test/p.png",
                    "https://cdn.test/a.wav",
                ),
            )
    finally:
        model_config.reset_request_tool_configs(token)


# ── task status machine ──────────────────────────────────────────────────────


@respx.mock
def test_status_success_reads_results_video_url(s2v_env) -> None:
    respx.get(f"{_BASE}/tasks/task-s2v-2").mock(
        return_value=httpx.Response(
            200,
            json={
                "output": {
                    "task_status": "SUCCEEDED",
                    "results": {"video_url": "https://oss.test/out.mp4"},
                },
            },
        ),
    )
    result = asyncio.run(s2v_model.check_s2v_task_status("task-s2v-2"))
    assert result == {
        "task_id": "task-s2v-2",
        "status": "SUCCEEDED",
        "result_url": "https://oss.test/out.mp4",
    }


@respx.mock
def test_status_success_falls_back_to_flat_video_url(s2v_env) -> None:
    respx.get(f"{_BASE}/tasks/task-s2v-3").mock(
        return_value=httpx.Response(
            200,
            json={
                "output": {
                    "task_status": "SUCCEEDED",
                    "video_url": "https://oss.test/flat.mp4",
                },
            },
        ),
    )
    result = asyncio.run(s2v_model.check_s2v_task_status("task-s2v-3"))
    assert result["result_url"] == "https://oss.test/flat.mp4"


@respx.mock
def test_status_failure_carries_provider_message(s2v_env) -> None:
    respx.get(f"{_BASE}/tasks/task-s2v-4").mock(
        return_value=httpx.Response(
            200,
            json={
                "output": {
                    "task_status": "FAILED",
                    "message": "audio too long",
                },
            },
        ),
    )
    result = asyncio.run(s2v_model.check_s2v_task_status("task-s2v-4"))
    assert result["status"] == "FAILED"
    assert result["error"] == "audio too long"


@respx.mock
def test_status_4xx_is_not_retryable(s2v_env) -> None:
    respx.get(f"{_BASE}/tasks/task-s2v-5").mock(
        return_value=httpx.Response(400, json={"message": "bad task"}),
    )
    with pytest.raises(ModelError) as excinfo:
        asyncio.run(s2v_model.check_s2v_task_status("task-s2v-5"))
    assert excinfo.value.retryable is False
