# -*- coding: utf-8 -*-
# pylint: disable=protected-access,unused-argument
"""The reuse key of a narrated asset must name the voice that was spoken.

``execute_file_tts_command`` looks for an already synthesized version of the
same text before paying the provider again. A stored version records the voice
the runner actually spoke with, while the lookup builds its key from the
request plus the deployment default - two resolutions of one decision. When
they differ, the reuse check compares a voice against a name the model never
received, misses its own cache on every retry, and silently bills the same
narration twice.
"""

from __future__ import annotations

import asyncio

import pytest

from models import tts_model
from models.tts_capabilities import capability_for, supported_models
from services.media_files import audio_execution


def _identity(**kwargs):
    return audio_execution._requested_tts_identity(
        voice=kwargs.get("voice", ""),
        voice_id=kwargs.get("voice_id"),
        voice_model=kwargs.get("voice_model", ""),
    )


def test_reuse_key_matches_the_voice_the_runner_actually_speaks(
    monkeypatch,
) -> None:
    """A deployment left on a default voice this model does not publish falls
    back to one of its own. The key has to follow the same substitution, or the
    asset is stored under one name and looked up under another."""

    spoken: dict = {}

    def fake_ws(*, model, voice, text, api_key, speech_rate=1.0):
        spoken.update(model=model, voice=voice)
        return b"MP3xxxx", "audio/mpeg"

    monkeypatch.setenv("TTS_API_KEY", "sk-test")
    monkeypatch.setenv("TTS_MODEL_NAME", "qwen-audio-3.1-tts-flash")
    monkeypatch.setenv("TTS_VOICE", "Cherry")
    monkeypatch.setattr(tts_model, "_synthesize_over_websocket", fake_ws)

    asyncio.run(tts_model.synthesize("同一句旁白"))

    assert spoken["voice"] != "Cherry"
    assert _identity() == (spoken["model"], spoken["voice"])


def test_reuse_key_never_names_a_voice_the_model_cannot_speak(
    monkeypatch,
) -> None:
    """Every model that publishes voices gets checked, not only the one that
    exposed the bug: the configured default is shared across the table, and a
    key naming an unspeakable voice can never match a stored asset."""

    monkeypatch.setenv("TTS_API_KEY", "sk-test")
    monkeypatch.setenv("TTS_VOICE", "Cherry")
    for capability in supported_models():
        if not capability.has_system_voices:
            # Nothing can be stored under this row: plain synthesis is
            # refused until a character voice is created.
            continue
        monkeypatch.setenv("TTS_MODEL_NAME", capability.model)
        _, voice = _identity()
        assert voice in capability.system_voices, capability.model


def test_a_made_up_voice_is_keyed_as_requested(monkeypatch) -> None:
    """The fail-fast path stays honest: a name the caller typed is never
    quietly rewritten in the key, even though the call will be refused."""

    monkeypatch.setenv("TTS_API_KEY", "sk-test")
    monkeypatch.setenv("TTS_MODEL_NAME", "qwen-audio-3.1-tts-flash")
    monkeypatch.setenv("TTS_VOICE", "Cherry")

    assert _identity(voice="NotAVoice") == (
        "qwen-audio-3.1-tts-flash",
        "NotAVoice",
    )
    with pytest.raises(ValueError, match="unknown voice"):
        asyncio.run(tts_model.synthesize("旁白", voice="NotAVoice"))


def test_a_created_voice_keeps_its_own_identity(monkeypatch) -> None:
    """A cloned voice is identified by its id and the model it was created
    against, which is the rule this function had before the fallback existed.
    """

    monkeypatch.setenv("TTS_MODEL_NAME", "qwen-audio-3.1-tts-flash")
    monkeypatch.setenv("TTS_VOICE", "Cherry")

    model, voice = _identity(voice_id="vc-abc")
    assert voice == "vc-abc"
    assert model == capability_for("qwen-audio-3.1-tts-flash").clone_model()


def test_no_system_voices_identity_is_honest(monkeypatch) -> None:
    """A model with no published list has no name to substitute, so the
    passthrough path returns the configured name — empty when nothing is set.

    ``test_reuse_key_never_names_a_voice_the_model_cannot_speak`` skips this
    row because plain synthesis is refused without a created character voice,
    but ``_requested_tts_identity`` has no such guard: the function must not
    crash and must produce a key that matches nothing (empty voice).
    """

    monkeypatch.setenv("TTS_MODEL_NAME", "cosyvoice-v3.5-plus")
    monkeypatch.setenv("TTS_VOICE", "")

    model, voice = _identity()
    assert model == "cosyvoice-v3.5-plus"
    assert voice == ""
