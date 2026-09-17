# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access
"""Unit tests for the qwen3-asr protocol branch (respx-stubbed, no billing)."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
import respx

from models import config
from models import asr_model
from models.asr_model import ASRResult

ENDPOINT = (
    "https://asr.example/api/v1/services/aigc/"
    "multimodal-generation/generation"
)


def _bind_qwen3(monkeypatch, *, language: str = "") -> None:
    monkeypatch.setattr(config, "get_asr_api_key", lambda: "asr-key")
    monkeypatch.setattr(
        config,
        "get_asr_model_name",
        lambda: "qwen3-asr-flash",
    )
    monkeypatch.setattr(config, "get_asr_provider", lambda: "fun-asr")
    monkeypatch.setattr(config, "get_asr_language", lambda: language)
    monkeypatch.setattr(config, "get_asr_timeout_seconds", lambda: 30)
    monkeypatch.setattr(
        config,
        "get_asr_base_url",
        lambda: "https://asr.example/api/v1/services/audio/asr/transcription",
    )


def _response(sentences: list[str]) -> dict:
    return {
        "output": {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": [{"text": text} for text in sentences],
                    },
                },
            ],
        },
        "request_id": "req-1",
    }


def test_transcribe_dispatches_qwen3_models_to_new_branch(
    monkeypatch,
) -> None:
    _bind_qwen3(monkeypatch)
    observed = {}

    async def fake_qwen3(media_url: str) -> ASRResult:
        observed["url"] = media_url
        return ASRResult("fun-asr", "qwen3-asr-flash", ())

    monkeypatch.setattr(asr_model, "_qwen3_asr", fake_qwen3)
    result = asyncio.run(asr_model.transcribe("https://cdn.test/a.mp3"))

    assert observed["url"] == "https://cdn.test/a.mp3"
    assert result.model == "qwen3-asr-flash"


def test_transcribe_keeps_fun_asr_for_other_models(monkeypatch) -> None:
    _bind_qwen3(monkeypatch)
    monkeypatch.setattr(config, "get_asr_model_name", lambda: "fun-asr")
    observed = {}

    async def fake_fun_asr(media_url: str) -> ASRResult:
        observed["url"] = media_url
        return ASRResult("dashscope", "fun-asr", ())

    monkeypatch.setattr(asr_model, "_fun_asr", fake_fun_asr)
    asyncio.run(asr_model.transcribe("https://cdn.test/a.mp3"))

    assert observed["url"] == "https://cdn.test/a.mp3"


def test_transcribe_keeps_whisper_provider_priority(monkeypatch) -> None:
    _bind_qwen3(monkeypatch)
    monkeypatch.setattr(config, "get_asr_provider", lambda: "whisper")
    observed = {}

    async def fake_whisper(media_url: str) -> ASRResult:
        observed["url"] = media_url
        return ASRResult("openai", "whisper-1", ())

    monkeypatch.setattr(asr_model, "_whisper", fake_whisper)
    asyncio.run(asr_model.transcribe("https://cdn.test/a.mp3"))

    assert observed["url"] == "https://cdn.test/a.mp3"


@respx.mock
def test_qwen3_single_chunk_spreads_estimated_timestamps(
    monkeypatch,
) -> None:
    _bind_qwen3(monkeypatch)
    monkeypatch.setattr(asr_model, "_probe_duration_ms", lambda _s: 10_000)

    async def fake_file_url(_media_url, key, model):
        assert (key, model) == ("asr-key", "qwen3-asr-flash")
        return "oss://dashscope-instant/audio.mp3"

    monkeypatch.setattr(asr_model, "_fun_asr_file_url", fake_file_url)
    route = respx.post(ENDPOINT).mock(
        return_value=httpx.Response(200, json=_response(["你好。", "再见。"])),
    )

    result = asyncio.run(asr_model._qwen3_asr("https://cdn.test/a.mp3"))

    assert result.provider == "fun-asr"
    assert result.model == "qwen3-asr-flash"
    assert [
        (seg.start_ms, seg.end_ms, seg.text, seg.confidence)
        for seg in result.segments
    ] == [
        (0, 5_000, "你好。", 0.0),
        (5_000, 10_000, "再见。", 0.0),
    ]
    request = route.calls.last.request
    assert request.headers["X-DashScope-OssResourceResolve"] == "enable"
    body = json.loads(request.content)
    assert body["model"] == "qwen3-asr-flash"
    assert body["input"]["messages"][0]["content"] == [
        {"audio": "oss://dashscope-instant/audio.mp3"},
    ]
    assert body["parameters"] == {"result_format": "message"}


@respx.mock
def test_qwen3_chunking_applies_cumulative_offsets(
    monkeypatch,
    tmp_path,
) -> None:
    _bind_qwen3(monkeypatch)
    plan_a = asr_model._ChunkPlan(0.0, 270.0, 270_000, False)
    plan_b = asr_model._ChunkPlan(270.0, 270.0, 270_000, False)
    chunks = [
        (tmp_path / "qwen3-chunk-0000.mp3", plan_a),
        (tmp_path / "qwen3-chunk-0001.mp3", plan_b),
    ]
    for chunk, _plan in chunks:
        chunk.write_bytes(b"audio")
    monkeypatch.setattr(
        asr_model,
        "_local_media_path",
        lambda *_args: tmp_path / "source.mp3",
    )
    monkeypatch.setattr(asr_model, "_probe_duration_ms", lambda _s: 540_000)
    monkeypatch.setattr(
        asr_model,
        "_prepare_qwen3_chunks",
        lambda *_args: chunks,
    )

    async def fake_upload(path, *, api_key, model_name, media_type):
        assert (api_key, model_name) == ("asr-key", "qwen3-asr-flash")
        assert media_type == "audio/mpeg"
        return f"oss://dashscope-instant/{path.name}"

    monkeypatch.setattr(
        asr_model,
        "upload_local_file_to_dashscope_temp",
        fake_upload,
    )
    responses = iter(
        [
            httpx.Response(200, json=_response(["第一块前半。", "第一块后半。"])),
            httpx.Response(200, json=_response(["第二块。"])),
        ],
    )
    respx.post(ENDPOINT).mock(side_effect=lambda _request: next(responses))

    result = asyncio.run(
        asr_model._qwen3_asr((tmp_path / "source.mp3").as_uri()),
    )

    assert [
        (seg.start_ms, seg.end_ms, seg.text) for seg in result.segments
    ] == [
        (0, 135_000, "第一块前半。"),
        (135_000, 270_000, "第一块后半。"),
        (270_000, 540_000, "第二块。"),
    ]
    assert all(seg.confidence == 0.0 for seg in result.segments)


def test_plan_chunks_snaps_to_silence_near_balanced_target() -> None:
    # 530s -> 2 balanced ~265s targets; the boundary snaps to the nearest
    # silence (264s) and no chunk lands mid-speech (all soft cuts).
    plans = asr_model._plan_chunks(
        530.0,
        [120.0, 264.0, 400.0],
        max_s=270.0,
        min_s=10.0,
    )
    assert [p.own_duration_ms for p in plans] == [264_000, 266_000]
    assert all(p.dedup_prev is False for p in plans)
    assert all(p.ext_duration_s <= 270.0 for p in plans)


def test_plan_chunks_no_silence_uses_overlap_not_lossy_hard_cut() -> None:
    # No silence anywhere: cuts are balanced (never the full 270s hard split)
    # and every internal boundary is protected by an overlap so no word drops.
    plans = asr_model._plan_chunks(
        540.0,
        [],
        max_s=270.0,
        min_s=10.0,
        overlap_s=3.0,
    )
    assert len(plans) == 2
    # balanced, not a 270 + 270 mid-phoneme fixed cut recreation
    assert plans[0].own_duration_ms == 270_000
    assert plans[1].own_duration_ms == 270_000
    # second chunk re-hears the boundary and is marked for dedup
    assert plans[0].dedup_prev is False
    assert plans[1].dedup_prev is True
    assert plans[1].ext_start_s == 267.0  # 270 - 3s overlap
    assert plans[1].ext_duration_s == 273.0


def test_plan_chunks_has_no_sub_minimum_tail() -> None:
    # Near multiples of max_s must not leave a degenerate final chunk.
    for duration in (270.1, 540.001, 271.0):
        plans = asr_model._plan_chunks(duration, [], max_s=270.0, min_s=10.0)
        seconds = [p.own_duration_ms / 1000 for p in plans]
        assert abs(sum(seconds) - duration) < 0.01  # ms rounding tolerance
        assert all(value >= 10.0 for value in seconds), (duration, seconds)
        assert all(value <= 270.0 + 1e-9 for value in seconds), (
            duration,
            seconds,
        )


def test_plan_chunks_single_window_when_short() -> None:
    plans = asr_model._plan_chunks(120.0, [], max_s=270.0)
    assert len(plans) == 1
    assert plans[0].own_duration_ms == 120_000
    assert plans[0].dedup_prev is False


def test_dedup_sentences_strips_reheard_overlap_seam() -> None:
    # The overlap re-heard "重听部分文字" (6 chars, >= min match) at the next
    # chunk head; only that duplicated prefix is stripped so the joined text
    # reads it exactly once.
    prev = ["前半句内容，重听部分文字"]
    curr = ["重听部分文字后面是新内容。", "下一句。"]
    deduped = asr_model._dedup_sentences(prev, curr)
    assert deduped == ["后面是新内容。", "下一句。"]
    assert (prev[-1] + deduped[0]).endswith("重听部分文字后面是新内容。")


def test_dedup_sentences_drops_fully_duplicated_leading_sentence() -> None:
    prev = ["完整重复的一句话。"]
    curr = ["完整重复的一句话。", "新的内容。"]
    assert asr_model._dedup_sentences(prev, curr) == ["新的内容。"]


def test_dedup_sentences_keeps_genuine_repeat_after_boundary() -> None:
    # The overlap re-heard "谢谢观看。" once, but the speaker genuinely repeats
    # it in the new chunk. Only the single re-heard copy is removed; the
    # genuine repeat must survive (the old while-loop deleted both).
    prev = ["谢谢观看。"]
    curr = ["谢谢观看。", "谢谢观看。", "接下来。"]
    assert asr_model._dedup_sentences(prev, curr) == [
        "谢谢观看。",
        "接下来。",
    ]


def test_dedup_sentences_keeps_consecutive_repeats_when_prev_also_repeats() -> (
    None
):
    # prev already ends with the sentence twice and curr repeats it twice:
    # a concatenated longest-match would strip both, deleting a genuine
    # occurrence. Only one re-heard copy may be removed.
    prev = ["谢谢观看。", "谢谢观看。"]
    curr = ["谢谢观看。", "谢谢观看。", "接下来。"]
    assert asr_model._dedup_sentences(prev, curr) == [
        "谢谢观看。",
        "接下来。",
    ]


def test_dedup_sentences_ignores_incidental_short_match() -> None:
    # A one-character coincidence ('好') must not trim unrelated speech.
    prev = ["天气很好"]
    curr = ["好，我们开始"]
    assert asr_model._dedup_sentences(prev, curr) == ["好，我们开始"]


def test_silence_cut_points_parses_ffmpeg_midpoints(monkeypatch) -> None:
    class _Completed:
        returncode = 0
        stdout = ""
        stderr = "\n".join(
            [
                "[silencedetect @ 0x1] silence_start: 12.0",
                "[silencedetect @ 0x1] silence_end: 13.0 | silence_duration: 1.0",
                "[silencedetect @ 0x1] silence_start: 40.5",
                "[silencedetect @ 0x1] silence_end: 41.5 | silence_duration: 1.0",
            ],
        )

    captured = {}

    def fake_run(cmd, **_kwargs):
        captured["cmd"] = cmd
        return _Completed()

    monkeypatch.setattr(asr_model.subprocess, "run", fake_run)
    from pathlib import Path

    assert asr_model._silence_cut_points("/opt/ffmpeg", Path("a.mp3")) == [
        12.5,
        41.0,
    ]
    # video decoding disabled during the full-file scan (P2)
    assert "-vn" in captured["cmd"]


@respx.mock
def test_qwen3_retries_throttling_with_backoff(monkeypatch) -> None:
    _bind_qwen3(monkeypatch)
    monkeypatch.setattr(asr_model, "_probe_duration_ms", lambda _s: 5_000)

    async def fake_file_url(*_args):
        return "oss://dashscope-instant/audio.mp3"

    monkeypatch.setattr(asr_model, "_fun_asr_file_url", fake_file_url)
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asr_model.asyncio, "sleep", fake_sleep)
    responses = iter(
        [
            httpx.Response(
                429,
                json={"code": "Throttling.RateQuota", "message": "slow down"},
            ),
            httpx.Response(200, json=_response(["成功。"])),
        ],
    )
    route = respx.post(ENDPOINT).mock(
        side_effect=lambda _request: next(responses),
    )

    result = asyncio.run(asr_model._qwen3_asr("https://cdn.test/a.mp3"))

    assert [seg.text for seg in result.segments] == ["成功。"]
    assert route.call_count == 2
    assert len(sleeps) == 1 and sleeps[0] >= 2.0


@respx.mock
def test_qwen3_throttling_exhaustion_raises(monkeypatch) -> None:
    _bind_qwen3(monkeypatch)
    monkeypatch.setattr(asr_model, "_probe_duration_ms", lambda _s: 5_000)

    async def fake_file_url(*_args):
        return "oss://dashscope-instant/audio.mp3"

    monkeypatch.setattr(asr_model, "_fun_asr_file_url", fake_file_url)

    async def fake_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(asr_model.asyncio, "sleep", fake_sleep)
    route = respx.post(ENDPOINT).mock(
        return_value=httpx.Response(
            429,
            json={"code": "Throttling.RateQuota", "message": "slow down"},
        ),
    )

    with pytest.raises(asr_model._ThrottlingError):
        asyncio.run(asr_model._qwen3_asr("https://cdn.test/a.mp3"))
    assert route.call_count == 4


@respx.mock
def test_qwen3_retries_transient_errors_linearly(monkeypatch) -> None:
    _bind_qwen3(monkeypatch)
    monkeypatch.setattr(asr_model, "_probe_duration_ms", lambda _s: 5_000)

    async def fake_file_url(*_args):
        return "oss://dashscope-instant/audio.mp3"

    monkeypatch.setattr(asr_model, "_fun_asr_file_url", fake_file_url)
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asr_model.asyncio, "sleep", fake_sleep)
    responses = iter(
        [
            httpx.Response(500, json={"message": "boom"}),
            httpx.Response(200, json=_response(["恢复。"])),
        ],
    )
    route = respx.post(ENDPOINT).mock(
        side_effect=lambda _request: next(responses),
    )

    result = asyncio.run(asr_model._qwen3_asr("https://cdn.test/a.mp3"))

    assert [seg.text for seg in result.segments] == ["恢复。"]
    assert route.call_count == 2
    assert sleeps == [2.0]


@respx.mock
def test_qwen3_transient_backoff_is_linear_two_then_four(monkeypatch) -> None:
    _bind_qwen3(monkeypatch)
    monkeypatch.setattr(asr_model, "_probe_duration_ms", lambda _s: 5_000)

    async def fake_file_url(*_args):
        return "oss://dashscope-instant/audio.mp3"

    monkeypatch.setattr(asr_model, "_fun_asr_file_url", fake_file_url)
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asr_model.asyncio, "sleep", fake_sleep)
    responses = iter(
        [
            httpx.Response(503, json={"message": "unavailable"}),
            httpx.Response(500, json={"message": "boom"}),
            httpx.Response(200, json=_response(["终于成功。"])),
        ],
    )
    route = respx.post(ENDPOINT).mock(
        side_effect=lambda _request: next(responses),
    )

    result = asyncio.run(asr_model._qwen3_asr("https://cdn.test/a.mp3"))

    assert [seg.text for seg in result.segments] == ["终于成功。"]
    assert route.call_count == 3
    assert sleeps == [2.0, 4.0]


@respx.mock
def test_qwen3_throttling_in_http_200_body_is_retried(monkeypatch) -> None:
    _bind_qwen3(monkeypatch)
    monkeypatch.setattr(asr_model, "_probe_duration_ms", lambda _s: 5_000)

    async def fake_file_url(*_args):
        return "oss://dashscope-instant/audio.mp3"

    monkeypatch.setattr(asr_model, "_fun_asr_file_url", fake_file_url)
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asr_model.asyncio, "sleep", fake_sleep)
    responses = iter(
        [
            httpx.Response(
                200,
                json={"code": "Throttling.RateQuota", "message": "slow"},
            ),
            httpx.Response(200, json=_response(["成功。"])),
        ],
    )
    route = respx.post(ENDPOINT).mock(
        side_effect=lambda _request: next(responses),
    )

    result = asyncio.run(asr_model._qwen3_asr("https://cdn.test/a.mp3"))

    assert [seg.text for seg in result.segments] == ["成功。"]
    assert route.call_count == 2
    assert len(sleeps) == 1 and sleeps[0] >= 2.0


@respx.mock
def test_qwen3_client_errors_do_not_retry(monkeypatch) -> None:
    _bind_qwen3(monkeypatch)
    monkeypatch.setattr(asr_model, "_probe_duration_ms", lambda _s: 5_000)

    async def fake_file_url(*_args):
        return "oss://dashscope-instant/audio.mp3"

    monkeypatch.setattr(asr_model, "_fun_asr_file_url", fake_file_url)
    route = respx.post(ENDPOINT).mock(
        return_value=httpx.Response(400, json={"message": "bad request"}),
    )

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(asr_model._qwen3_asr("https://cdn.test/a.mp3"))
    assert route.call_count == 1


@respx.mock
def test_qwen3_empty_audio_returns_no_segments(monkeypatch) -> None:
    _bind_qwen3(monkeypatch)
    monkeypatch.setattr(asr_model, "_probe_duration_ms", lambda _s: 5_000)

    async def fake_file_url(*_args):
        return "oss://dashscope-instant/silence.mp3"

    monkeypatch.setattr(asr_model, "_fun_asr_file_url", fake_file_url)
    respx.post(ENDPOINT).mock(
        return_value=httpx.Response(200, json=_response([])),
    )

    result = asyncio.run(asr_model._qwen3_asr("https://cdn.test/silence.mp3"))

    assert result.segments == ()
    assert result.provider == "fun-asr"


@respx.mock
def test_qwen3_language_is_forwarded_via_asr_options(monkeypatch) -> None:
    _bind_qwen3(monkeypatch, language="zh")
    monkeypatch.setattr(asr_model, "_probe_duration_ms", lambda _s: 5_000)

    async def fake_file_url(*_args):
        return "oss://dashscope-instant/audio.mp3"

    monkeypatch.setattr(asr_model, "_fun_asr_file_url", fake_file_url)
    route = respx.post(ENDPOINT).mock(
        return_value=httpx.Response(200, json=_response(["你好。"])),
    )

    asyncio.run(asr_model._qwen3_asr("https://cdn.test/a.mp3"))

    body = json.loads(route.calls.last.request.content)
    assert body["parameters"]["asr_options"] == {"language": "zh"}


def test_qwen3_endpoint_derives_from_asr_base_host() -> None:
    assert (
        asr_model._qwen3_endpoint(
            "https://asr.example/api/v1/services/audio/asr/transcription",
        )
        == ENDPOINT
    )
    assert asr_model._qwen3_endpoint(
        "https://dashscope.aliyuncs.com/api/v1",
    ) == (
        "https://dashscope.aliyuncs.com/api/v1/services/aigc/"
        "multimodal-generation/generation"
    )
    with pytest.raises(ValueError):
        asr_model._qwen3_endpoint("not-a-url")


def test_spread_segments_marks_estimates_and_clamps() -> None:
    segments = asr_model._spread_segments(["a", "b", "c"], 1_000, 2)
    assert len(segments) == 3
    assert all(seg.confidence == 0.0 for seg in segments)
    assert all(seg.end_ms > seg.start_ms for seg in segments)
    assert segments[0].start_ms == 1_000
    assert not asr_model._spread_segments([], 0, 1_000)


def test_probe_duration_falls_back_to_ffmpeg_without_ffprobe(
    monkeypatch,
) -> None:
    """qwen3-asr chunking must work when only bundled ffmpeg is present.

    Creator treats ffprobe as optional; probe_media parses ffmpeg's stderr
    metadata when no ffprobe binary exists (imageio-ffmpeg ships no ffprobe).
    """
    from services.runtime_files import media_probe

    monkeypatch.setattr(media_probe, "resolve_ffprobe", lambda **_kw: None)
    monkeypatch.setattr(media_probe, "resolve_ffmpeg", lambda: "/opt/ffmpeg")

    class _Completed:
        returncode = 1
        stdout = ""
        stderr = (
            "Input #0, mp3, from 'a.mp3':\n"
            "  Duration: 00:04:35.10, start: 0.000000, bitrate: 128 kb/s\n"
            "  Stream #0:0: Audio: mp3, 16000 Hz, mono, fltp, 128 kb/s\n"
        )

    def fake_run(cmd, **_kwargs):
        assert cmd[0] == "/opt/ffmpeg"
        return _Completed()

    monkeypatch.setattr(media_probe.subprocess, "run", fake_run)

    assert asr_model._probe_duration_ms("a.mp3") == 275_100
