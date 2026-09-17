# -*- coding: utf-8 -*-
# pylint: disable=protected-access
# flake8: noqa: E501
"""Capability-driven routing of the supported speech-synthesis models."""

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


def test_voice_design_requires_a_long_enough_preview(
    tmp_path,
    monkeypatch,
) -> None:
    _write_config(tmp_path, monkeypatch, "qwen3-tts-flash")
    with pytest.raises(ValueError, match="at least"):
        asyncio.run(
            tts_model.design_voice(
                voice_prompt="低沉的男声",
                preview_text="太短",
                preferred_name="hero",
            ),
        )
    with pytest.raises(ValueError, match="voice_prompt"):
        asyncio.run(
            tts_model.design_voice(
                voice_prompt="   ",
                preview_text="这是一段足够长的试听文本内容。",
                preferred_name="hero",
            ),
        )


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
