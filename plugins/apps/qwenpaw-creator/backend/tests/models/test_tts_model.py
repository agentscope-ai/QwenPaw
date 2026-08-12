# -*- coding: utf-8 -*-
# pylint: disable=protected-access,unused-argument
# flake8: noqa: E501

from __future__ import annotations

import asyncio
import json

import pytest

from models import config as model_config
from models import tts_model


def test_require_text_rejects_empty_and_overlong() -> None:
    with pytest.raises(ValueError):
        tts_model._require_text("   ")
    with pytest.raises(ValueError, match="split the script"):
        tts_model._require_text("字" * (tts_model.TTS_MAX_TEXT_CHARS + 1))
    assert tts_model._require_text(" 你好 ") == "你好"


def test_normalize_preferred_name() -> None:
    assert tts_model._normalize_preferred_name("关 羽 Hero-01!") == "hero01"
    assert tts_model._normalize_preferred_name("Guan Yu!") == "guanyu"
    assert tts_model._normalize_preferred_name("！！！") == "creatorvoice"
    assert len(tts_model._normalize_preferred_name("a" * 64)) == 20


def test_synthesize_uses_system_voice_and_flash_model(monkeypatch) -> None:
    captured: dict = {}

    async def fake_post_json(url, *, api_key, payload, timeout_seconds):
        captured["url"] = url
        captured["payload"] = payload
        return {
            "output": {"audio": {"url": "https://example.com/a.wav"}},
            "usage": {"characters": 4},
        }

    def fake_download(url):
        captured["download"] = url
        return b"RIFFxxxx", "audio/wav"

    monkeypatch.setenv("TTS_API_KEY", "sk-test")
    monkeypatch.setattr(tts_model, "_post_json", fake_post_json)
    monkeypatch.setattr(tts_model, "_download_audio", fake_download)

    result = asyncio.run(tts_model.synthesize("你好世界", voice="Serena"))
    assert "multimodal-generation/generation" in captured["url"]
    assert captured["payload"]["model"] == model_config.get_tts_model_name()
    assert captured["payload"]["input"] == {
        "text": "你好世界",
        "voice": "Serena",
    }
    assert result.audio_bytes == b"RIFFxxxx"
    assert result.characters == 4


def test_synthesize_with_voice_id_switches_to_vc_model(monkeypatch) -> None:
    captured: dict = {}

    async def fake_post_json(url, *, api_key, payload, timeout_seconds):
        captured["payload"] = payload
        return {"output": {"audio": {"url": "https://example.com/a.wav"}}}

    monkeypatch.setenv("TTS_API_KEY", "sk-test")
    monkeypatch.setattr(tts_model, "_post_json", fake_post_json)
    monkeypatch.setattr(
        tts_model,
        "_download_audio",
        lambda url: (b"RIFF", "audio/wav"),
    )

    result = asyncio.run(
        tts_model.synthesize("台词", voice_id="myvoice-abc123"),
    )
    assert captured["payload"]["model"] == model_config.get_tts_vc_model_name()
    assert captured["payload"]["input"]["voice"] == "myvoice-abc123"
    assert result.voice == "myvoice-abc123"


def test_synthesize_without_key_raises(monkeypatch) -> None:
    monkeypatch.delenv("TTS_API_KEY", raising=False)
    with pytest.raises(ValueError, match="creator_tts_model"):
        asyncio.run(tts_model.synthesize("你好"))


def test_synthesize_rejects_unknown_system_voice(monkeypatch) -> None:
    """A made-up voice must fail before reaching the provider."""

    async def fail_post_json(url, *, api_key, payload, timeout_seconds):
        raise AssertionError("provider must not be called")

    monkeypatch.setenv("TTS_API_KEY", "sk-test")
    monkeypatch.setattr(tts_model, "_post_json", fail_post_json)

    with pytest.raises(ValueError, match="available system voices"):
        asyncio.run(
            tts_model.synthesize("你好", voice="zh-CN-YunxiNeural"),
        )


def test_enroll_voice_builds_enrollment_payload(monkeypatch) -> None:
    captured: dict = {}

    async def fake_post_json(url, *, api_key, payload, timeout_seconds):
        captured["url"] = url
        captured["payload"] = payload
        return {"output": {"voice_id": "qwen-tts-vc-guanyu-xyz"}}

    async def fake_sample_url(sample, api_key, model):
        return "https://example.com/sample.wav"

    monkeypatch.setenv("TTS_API_KEY", "sk-test")
    monkeypatch.setattr(tts_model, "_post_json", fake_post_json)
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


def test_is_tts_configured_gates_on_key(monkeypatch) -> None:
    monkeypatch.delenv("TTS_API_KEY", raising=False)
    assert model_config.is_tts_configured() is False
    monkeypatch.setenv("TTS_API_KEY", "sk-test")
    assert model_config.is_tts_configured() is True


def test_tts_api_key_falls_back_to_the_text_credential(
    tmp_path,
    monkeypatch,
) -> None:
    """TTS reuses the LLM key by default so it needs no separate entry."""

    monkeypatch.delenv("TTS_API_KEY", raising=False)
    monkeypatch.delenv("TEXT_API_KEY", raising=False)
    config_path = tmp_path / "config" / "model_config.json"
    config_path.parent.mkdir(parents=True)
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    monkeypatch.setenv("CREATOR_MODEL_CONFIG_PATH", str(config_path))

    def write(tts_section: dict) -> None:
        config_path.write_text(
            json.dumps(
                {
                    "llm": {
                        "enabled": True,
                        "api_key": "sk-shared",
                        "base_url": "https://example.test/v1",
                        "model_name": "qwen",
                    },
                    "tts": tts_section,
                },
            ),
            encoding="utf-8",
        )
        model_config._clear_user_config_cache()

    write({"enabled": True, "model_name": "qwen3-tts-flash"})
    assert model_config.get_tts_api_key() == "sk-shared"
    assert model_config.is_tts_configured()

    write(
        {
            "enabled": True,
            "model_name": "qwen3-tts-flash",
            "reuse_llm_key": False,
        },
    )
    assert model_config.get_tts_api_key() == ""

    write(
        {
            "enabled": True,
            "model_name": "qwen3-tts-flash",
            "reuse_llm_key": False,
            "api_key": "sk-own",
        },
    )
    assert model_config.get_tts_api_key() == "sk-own"


def test_http_family_rejects_non_default_speech_rate(monkeypatch) -> None:
    """qwen-tts has no rate parameter, so a non-default rate fails fast
    instead of silently synthesizing at normal speed."""

    monkeypatch.setenv("TTS_API_KEY", "sk-test")
    with pytest.raises(ValueError, match="CosyVoice"):
        asyncio.run(
            tts_model.synthesize(
                "你好世界",
                voice="Serena",
                speech_rate=1.3,
            ),
        )


def test_websocket_family_forwards_speech_rate(monkeypatch) -> None:
    captured: dict = {}

    def fake_ws(*, model, voice, text, api_key, speech_rate=1.0):
        captured["model"] = model
        captured["speech_rate"] = speech_rate
        return b"MP3xxxx", "audio/mpeg"

    monkeypatch.setenv("TTS_API_KEY", "sk-test")
    monkeypatch.setenv("TTS_MODEL_NAME", "cosyvoice-v3.5-plus")
    monkeypatch.setattr(tts_model, "_synthesize_over_websocket", fake_ws)

    result = asyncio.run(
        tts_model.synthesize(
            "你好世界",
            voice_id="cosyvoice-v3-designed",
            voice_model="cosyvoice-v3.5-plus",
            speech_rate=0.8,
        ),
    )
    assert captured["model"] == "cosyvoice-v3.5-plus"
    assert captured["speech_rate"] == 0.8
    assert result.media_type == "audio/mpeg"


def test_speech_rate_bounds_are_validated(monkeypatch) -> None:
    monkeypatch.setenv("TTS_API_KEY", "sk-test")
    with pytest.raises(ValueError, match="0.5"):
        asyncio.run(
            tts_model.synthesize(
                "你好世界",
                voice="Serena",
                speech_rate=3.0,
            ),
        )


def test_created_voice_uses_its_own_models_transport(monkeypatch) -> None:
    """A CosyVoice-bound voice must ride WebSocket even when the configured
    default model is qwen-tts (HTTP): transport follows the speaking model."""

    captured: dict = {}

    def fake_ws(*, model, voice, text, api_key, speech_rate=1.0):
        captured["model"] = model
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
        ),
    )
    assert captured["model"] == "cosyvoice-v3.5-plus"
    assert result.media_type == "audio/mpeg"


def test_malformed_voice_id_fails_fast(monkeypatch) -> None:
    """An empty or garbage voice_id must not burn a provider round-trip."""

    monkeypatch.setenv("TTS_API_KEY", "sk-test")
    for bad in ("   ", "全角音色名", "-starts-with-dash", "a b c"):
        with pytest.raises(ValueError, match="voice_id"):
            asyncio.run(tts_model.synthesize("你好世界", voice_id=bad))


def test_provider_failures_raise_model_error(monkeypatch) -> None:
    """Provider-facing failures carry ModelError retry semantics: a 4xx is
    permanent, so pollers fail fast instead of waiting out the budget."""

    from utils.exceptions import ModelError

    async def fail_post(url, *, api_key, payload, timeout_seconds):
        raise ModelError("TTS request failed (HTTP 400): bad", retryable=False)

    monkeypatch.setenv("TTS_API_KEY", "sk-test")
    monkeypatch.setattr(tts_model, "_post_json", fail_post)
    with pytest.raises(ModelError) as caught:
        asyncio.run(tts_model.synthesize("你好世界", voice="Serena"))
    assert caught.value.retryable is False
