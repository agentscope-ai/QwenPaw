# -*- coding: utf-8 -*-
"""Tests for inlined media token estimates."""

# pylint: disable=protected-access

from __future__ import annotations

import base64
import io
import math
import wave

from PIL import Image

from qwenpaw.agents.utils import media_token_estimate as mte
from qwenpaw.agents.utils.media_token_estimate import (
    AUDIO_FALLBACK_TOKENS,
    AUDIO_TOKENS_PER_SECOND,
    FILE_FALLBACK_TOKENS,
    IMAGE_COST_SAFETY_MARGIN,
    IMAGE_FALLBACK_TOKENS,
    IMAGE_PATCH_SIZE,
    VIDEO_FALLBACK_TOKENS,
    estimate_inline_media_tokens,
)


def _png_b64(width: int = 32, height: int = 32) -> str:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=(0, 0, 0)).save(
        buf,
        format="PNG",
    )
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _wav_b64(duration: float = 2.0, sample_rate: int = 16000) -> str:
    frames = int(duration * sample_rate)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(b"\x00\x00" * frames)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _expected_image_tokens(width: int, height: int) -> int:
    patches = math.ceil(width / IMAGE_PATCH_SIZE) * math.ceil(
        height / IMAGE_PATCH_SIZE,
    )
    return math.ceil(patches * IMAGE_COST_SAFETY_MARGIN)


def test_empty_payload_is_placeholder():
    assert estimate_inline_media_tokens("image/png", "") == 10


def test_valid_png_uses_patch_formula():
    tokens = estimate_inline_media_tokens("image/png", _png_b64(32, 32))
    assert tokens == _expected_image_tokens(32, 32)
    assert tokens < IMAGE_FALLBACK_TOKENS


def test_wav_uses_duration():
    tokens = estimate_inline_media_tokens("audio/wav", _wav_b64(2.0))
    assert tokens == math.ceil(2.0 * AUDIO_TOKENS_PER_SECOND)


def test_invalid_audio_falls_back_not_bytes():
    payload = base64.b64encode(b"\x00" * 1024).decode("ascii")
    tokens = estimate_inline_media_tokens("audio/mpeg", payload)
    assert tokens == AUDIO_FALLBACK_TOKENS
    assert tokens != len(payload) // 4


def test_same_payload_dispatches_by_mime():
    payload = base64.b64encode(b"\x00" * (2 * 1024 * 1024)).decode("ascii")
    image = estimate_inline_media_tokens("image/png", payload)
    audio = estimate_inline_media_tokens("audio/mpeg", payload)
    video = estimate_inline_media_tokens("video/mp4", payload)
    pdf = estimate_inline_media_tokens("application/pdf", payload)
    byte_tokens = len(payload) // 4
    assert 0 < image < 10_000
    assert 0 < audio < 10_000
    assert video == VIDEO_FALLBACK_TOKENS
    assert pdf == FILE_FALLBACK_TOKENS
    assert video != pdf
    assert image != byte_tokens
    assert audio != byte_tokens
    assert video != byte_tokens
    assert pdf != byte_tokens


def test_text_datablock_counts_decoded_text():
    payload = base64.b64encode(b"hello").decode("ascii")
    tokens = estimate_inline_media_tokens("text/plain", payload)
    assert tokens == int(len(b"hello") / 4 + 0.5)
    assert tokens != FILE_FALLBACK_TOKENS


def test_invalid_base64_image_falls_back():
    assert (
        estimate_inline_media_tokens("image/png", "!!!")
        == IMAGE_FALLBACK_TOKENS
    )


def test_iter_data_url_spans_is_case_insensitive():
    spans = mte.iter_data_url_spans("DATA:image/png;BASE64,AAAA")
    assert len(spans) == 1
    assert spans[0][2].lower() == "image/png"


def test_estimate_data_url_tokens_requires_whole_string():
    url = "data:image/png;base64,AAAA trailing"
    assert mte.estimate_data_url_tokens(url) is None
    assert mte.iter_data_url_spans(url)


def test_estimate_is_cached(monkeypatch):
    calls = {"n": 0}
    original = mte._estimate_uncached

    def wrapped(media_type: str, data: str) -> int:
        calls["n"] += 1
        return original(media_type, data)

    monkeypatch.setattr(mte, "_estimate_uncached", wrapped)
    mte._cache.clear()
    payload = _png_b64(16, 16)
    first = mte.estimate_inline_media_tokens("image/png", payload)
    second = mte.estimate_inline_media_tokens("image/png", payload)
    assert first == second
    assert calls["n"] == 1
