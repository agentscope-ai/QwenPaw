# -*- coding: utf-8 -*-
# pylint: disable=protected-access,unused-argument
# flake8: noqa: E501

from __future__ import annotations

import asyncio
import json

import pytest

from models import config as model_config
from models import tts_model
from models.tts_capabilities import (
    DEFAULT_TTS_MODEL,
    capability_for,
    require_capability,
    supported_models,
)


def _fake_post(captured: dict, response: dict):
    async def fake_post_json(url, *, api_key, payload, timeout_seconds):
        captured["url"] = url
        captured["payload"] = payload
        return response

    return fake_post_json


def test_require_text_rejects_empty_and_overlong() -> None:
    with pytest.raises(ValueError):
        tts_model._require_text("   ")
    with pytest.raises(ValueError, match="split the script"):
        tts_model._require_text("字" * (tts_model.TTS_MAX_TEXT_CHARS + 1))
    assert tts_model._require_text(" 你好 ") == "你好"


def test_synthesize_uses_system_voice_and_flash_model(monkeypatch) -> None:
    captured: dict = {}
    monkeypatch.setenv("TTS_API_KEY", "sk-test")
    monkeypatch.setattr(
        tts_model,
        "_post_json",
        _fake_post(
            captured,
            {
                "output": {"audio": {"url": "https://example.com/a.wav"}},
                "usage": {"characters": 4},
            },
        ),
    )
    monkeypatch.setattr(
        tts_model,
        "_download_audio",
        lambda url: (b"RIFFxxxx", "audio/wav"),
    )

    result = asyncio.run(tts_model.synthesize("你好世界", voice="Serena"))
    assert "multimodal-generation/generation" in captured["url"]
    assert captured["payload"]["model"] == model_config.get_tts_model_name()
    assert captured["payload"]["input"] == {"text": "你好世界", "voice": "Serena"}
    assert result.audio_bytes == b"RIFFxxxx"
    assert result.characters == 4


def test_missing_key_gates_configuration_and_synthesis(monkeypatch) -> None:
    monkeypatch.delenv("TTS_API_KEY", raising=False)
    assert model_config.is_tts_configured() is False
    with pytest.raises(ValueError, match="creator_tts_model"):
        asyncio.run(tts_model.synthesize("你好"))
    monkeypatch.setenv("TTS_API_KEY", "sk-test")
    assert model_config.is_tts_configured() is True


def test_synthesize_rejects_unknown_system_voice(monkeypatch) -> None:
    """A made-up voice must fail before reaching the provider."""

    async def fail_post_json(url, *, api_key, payload, timeout_seconds):
        raise AssertionError("provider must not be called")

    monkeypatch.setenv("TTS_API_KEY", "sk-test")
    monkeypatch.setattr(tts_model, "_post_json", fail_post_json)

    with pytest.raises(ValueError, match="available system voices"):
        asyncio.run(tts_model.synthesize("你好", voice="zh-CN-YunxiNeural"))


def test_enroll_voice_builds_enrollment_payload(monkeypatch) -> None:
    captured: dict = {}

    async def fake_sample_url(sample, api_key, model):
        return "https://example.com/sample.wav"

    monkeypatch.setenv("TTS_API_KEY", "sk-test")
    monkeypatch.setattr(
        tts_model,
        "_post_json",
        _fake_post(
            captured,
            {"output": {"voice_id": "qwen-tts-vc-guanyu-xyz"}},
        ),
    )
    monkeypatch.setattr(tts_model, "_sample_url", fake_sample_url)

    enrollment = asyncio.run(
        tts_model.enroll_voice(
            "https://example.com/raw.wav",
            preferred_name="Guan Yu",
        ),
    )
    assert "audio/tts/customization" in captured["url"]
    body = captured["payload"]
    assert body["model"] == "qwen-voice-enrollment"
    assert body["input"]["action"] == "create"
    assert body["input"]["preferred_name"] == "guanyu"
    assert (
        body["input"]["target_model"] == model_config.get_tts_vc_model_name()
    )
    assert body["input"]["audio"] == {"data": "https://example.com/sample.wav"}
    assert enrollment.voice_id == "qwen-tts-vc-guanyu-xyz"


def test_http_family_validates_speech_rate(monkeypatch) -> None:
    """qwen-tts has no rate parameter, so a non-default rate fails fast
    instead of silently synthesizing at normal speed; out-of-bounds rates
    are rejected for every family."""

    monkeypatch.setenv("TTS_API_KEY", "sk-test")
    with pytest.raises(ValueError, match="CosyVoice"):
        asyncio.run(
            tts_model.synthesize("你好世界", voice="Serena", speech_rate=1.3),
        )
    with pytest.raises(ValueError, match="0.5"):
        asyncio.run(
            tts_model.synthesize("你好世界", voice="Serena", speech_rate=3.0),
        )


def test_created_voice_uses_its_own_models_transport(monkeypatch) -> None:
    """A CosyVoice-bound voice must ride WebSocket even when the configured
    default model is qwen-tts (HTTP): transport follows the speaking model,
    and the websocket family forwards the requested speech rate."""

    captured: dict = {}

    def fake_ws(*, model, voice, text, api_key, speech_rate=1.0):
        captured["model"] = model
        captured["speech_rate"] = speech_rate
        return b"MP3xxxx", "audio/mpeg"

    async def fail_post_json(url, **kwargs):
        raise AssertionError("HTTP path must not be used for a ws voice")

    monkeypatch.setenv("TTS_API_KEY", "sk-test")
    monkeypatch.setenv("TTS_MODEL_NAME", "qwen3-tts-flash")
    monkeypatch.setattr(tts_model, "_synthesize_over_websocket", fake_ws)
    monkeypatch.setattr(tts_model, "_post_json", fail_post_json)

    result = asyncio.run(
        tts_model.synthesize(
            "你好世界",
            voice_id="cosyvoice-v3.5-plus-vd-x",
            voice_model="cosyvoice-v3.5-plus",
            speech_rate=0.8,
        ),
    )
    assert captured["model"] == "cosyvoice-v3.5-plus"
    assert captured["speech_rate"] == 0.8
    assert result.media_type == "audio/mpeg"


# ---------------------------------------------------------------------------
# TTS capabilities matrix
# ---------------------------------------------------------------------------


def _write_config(tmp_path, monkeypatch, model: str) -> None:
    config_path = tmp_path / "config" / "model_config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(
            {
                "llm": {"enabled": True, "api_key": "sk-shared"},
                "tts": {"enabled": True, "model_name": model},
            },
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    monkeypatch.setenv("CREATOR_MODEL_CONFIG_PATH", str(config_path))
    model_config._clear_user_config_cache()


def test_every_supported_model_declares_a_usable_voice_source() -> None:
    """A model must offer system voices or a way to create one."""

    for capability in supported_models():
        assert capability.has_system_voices or capability.supports_design, (
            f"{capability.model} can neither speak with a system voice nor "
            "create one, so it would be unusable"
        )
        assert capability.clone_model()
        assert capability.transport in {"http", "websocket"}


def test_unknown_model_falls_back_to_the_default() -> None:
    assert capability_for("no-such-tts-model") is None
    assert require_capability("no-such-tts-model").model == DEFAULT_TTS_MODEL


@pytest.mark.parametrize(
    ("model", "clone_target", "design_target", "system_voices"),
    [
        (
            "qwen3-tts-flash",
            "qwen3-tts-vc-2026-01-22",
            "qwen3-tts-vd-2026-01-26",
            True,
        ),
        (
            "cosyvoice-v3.5-plus",
            "cosyvoice-v3.5-plus",
            "cosyvoice-v3.5-plus",
            False,
        ),
    ],
)
def test_companion_models_are_derived_not_configured(
    tmp_path,
    monkeypatch,
    model,
    clone_target,
    design_target,
    system_voices,
) -> None:
    """Users configure a synthesis model; companions come from the table."""

    monkeypatch.delenv("TTS_VC_MODEL_NAME", raising=False)
    _write_config(tmp_path, monkeypatch, model)
    assert model_config.get_tts_model_name() == model
    assert model_config.get_tts_vc_model_name() == clone_target
    assert model_config.get_tts_vd_model_name() == design_target
    assert model_config.tts_has_system_voices() is system_voices


def test_model_without_system_voices_refuses_plain_synthesis(
    tmp_path,
    monkeypatch,
) -> None:
    """cosyvoice-v3.5-plus can only speak through a created voice."""

    _write_config(tmp_path, monkeypatch, "cosyvoice-v3.5-plus")
    with pytest.raises(ValueError, match="no system voices"):
        asyncio.run(tts_model.synthesize("测试"))


@pytest.mark.parametrize(
    ("target_model", "voice_id", "expected_model", "expected_field"),
    [
        (
            "qwen3-tts-vc-2026-01-22",
            "qwen-tts-vc-hero-voice-1",
            "qwen-voice-enrollment",
            "voice",
        ),
        (
            "qwen3-tts-vd-2026-01-26",
            "qwen-tts-vd-hero-voice-1",
            "qwen-voice-design",
            "voice",
        ),
        (
            "cosyvoice-v3.5-plus",
            "cosyvoice-v3.5-plus-vd-hero-1",
            "voice-enrollment",
            "voice_id",
        ),
    ],
)
def test_deletion_is_routed_by_the_bound_model(
    target_model,
    voice_id,
    expected_model,
    expected_field,
) -> None:
    """Each voice namespace only accepts its own management surface.

    Deleting through the wrong one returns HTTP 400 and leaks the voice
    against the account quota, so the binding's model decides the call.
    """

    payload = tts_model._management_payload("delete", voice_id, target_model)
    assert payload["model"] == expected_model
    assert payload["input"][expected_field] == voice_id
    if expected_model == "voice-enrollment":
        assert payload["input"]["action"] == "delete_voice"
    else:
        assert payload["input"]["action"] == "delete"
