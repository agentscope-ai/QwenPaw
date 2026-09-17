# -*- coding: utf-8 -*-
"""Manual (real-key) integration checks for the qwen3-asr branch.

Billed DashScope calls, so this is skipped unless CREATOR_ASR_REAL_TEST is set
and audio paths are provided. Run from an environment where the ASR model
resolves to qwen3-asr-flash (creator model_config.json or ASR_* env vars).

    CREATOR_ASR_REAL_TEST=1 \
    CREATOR_ASR_REAL_AUDIO=/path/short.mp3 \
    CREATOR_ASR_REAL_AUDIO_LONG=/path/long.mp3 \
    CREATOR_ASR_REAL_VIDEO=/path/clip.mp4 \
    QWENPAW_WORKING_DIR=~/.qwenpaw-asr \
    CREATOR_DATA_ROOT=~/.qwenpaw-asr/creator-runtime \
    QWENPAW_KEYRING_ACCOUNT=<account> \
    python -m pytest -m manual_real tests/manual/test_real_asr_qwen3.py -s

Covers A1 (short), A2 (long chunking), A3 (video container). A4 (empty audio),
A5 (language payload) and A6 (oss:// URL) are deterministically covered by the
respx unit suite, which is the right place to assert request payloads/branches.
Per the acceptance rule, transcript correctness is confirmed by reading the
printed text; the assertions only guard structural invariants.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from models import asr_model, config
from services.runtime_files.media_probe import probe_media

_ENABLED = os.environ.get("CREATOR_ASR_REAL_TEST", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

pytestmark = [
    pytest.mark.manual_real,
    pytest.mark.skipif(
        not _ENABLED,
        reason="set CREATOR_ASR_REAL_TEST=1 to run billed qwen3-asr checks",
    ),
]


def _require_media(env_name: str) -> Path:
    raw = os.environ.get(env_name, "").strip()
    if not raw or not Path(raw).is_file():
        pytest.skip(f"{env_name} must point to an existing media file")
    return Path(raw).resolve()


def _assert_qwen3_configured() -> None:
    # Preflight the config before any billed call so a misconfigured model or
    # provider fails without spending money.
    assert config.get_asr_model_name().casefold().startswith("qwen3-asr")
    assert config.get_asr_provider() == "fun-asr"


def _assert_qwen3(result: asr_model.ASRResult) -> None:
    assert result.model.casefold().startswith("qwen3-asr")
    assert result.provider == "fun-asr"
    assert result.segments, "expected at least one transcript segment"


def test_real_short_audio_transcribes() -> None:
    _assert_qwen3_configured()
    path = _require_media("CREATOR_ASR_REAL_AUDIO")
    result = asyncio.run(asr_model.transcribe(path.as_uri()))
    _assert_qwen3(result)
    for previous, current in zip(result.segments, result.segments[1:]):
        assert current.start_ms >= previous.start_ms
    print("\n[short] " + " / ".join(seg.text for seg in result.segments))


def test_real_video_container_transcribes() -> None:
    _assert_qwen3_configured()
    path = _require_media("CREATOR_ASR_REAL_VIDEO")
    result = asyncio.run(asr_model.transcribe(path.as_uri()))
    _assert_qwen3(result)
    print("\n[video] " + " / ".join(seg.text for seg in result.segments))


def test_real_long_audio_chunks_are_contiguous() -> None:
    _assert_qwen3_configured()
    path = _require_media("CREATOR_ASR_REAL_AUDIO_LONG")
    # Probe the real path (no URI round-trip) so spaces / non-ASCII names work.
    duration = probe_media(str(path)).duration_seconds or 0.0
    if duration <= 300:
        pytest.skip(
            f"CREATOR_ASR_REAL_AUDIO_LONG must exceed 5min to exercise "
            f"chunking (got {duration:.1f}s)",
        )
    result = asyncio.run(asr_model.transcribe(path.as_uri()))
    _assert_qwen3(result)
    # More than one segment proves the chunking branch ran; cross-chunk
    # offsets must join without gaps/overlaps so no boundary word drops (A2).
    assert len(result.segments) >= 2
    for previous, current in zip(result.segments, result.segments[1:]):
        assert current.start_ms == previous.end_ms
    joined = "".join(seg.text for seg in result.segments)
    print(f"\n[long] {len(result.segments)} segments, {len(joined)} chars")
    print(joined)
