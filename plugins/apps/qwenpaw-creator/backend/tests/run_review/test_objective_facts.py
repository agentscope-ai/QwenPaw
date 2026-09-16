# -*- coding: utf-8 -*-
"""Tier-0 objective fact operators: pure math and ffmpeg round-trips."""

from __future__ import annotations

import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from services.run_review.objective import (
    collect_image_facts,
    collect_video_facts,
    render_facts_block,
)
from services.run_review.objective.audio_facts import (
    audio_content_facts,
    av_sync_facts,
)
from services.run_review.objective.machine_params import machine_param_facts
from services.run_review.objective.media_io import GraySamples
from services.run_review.objective.video_index import build_video_index

pytestmark = pytest.mark.unit

_FFMPEG = shutil.which("ffmpeg")
requires_ffmpeg = pytest.mark.skipif(
    _FFMPEG is None,
    reason="ffmpeg is required for objective fact tests",
)


def _samples_from_frames(frames: list[np.ndarray]) -> GraySamples:
    stacked = np.stack(frames).astype(np.uint8)
    timestamps = tuple(index * 125 for index in range(stacked.shape[0]))
    return GraySamples(timestamps_ms=timestamps, frames=stacked)


def test_cut_detection_finds_the_hard_cut() -> None:
    # 20 near-identical dark frames, then 20 bright ones: one cut.
    rng = np.random.default_rng(7)
    dark = [(rng.normal(40, 1.0, (36, 64))).clip(0, 255) for _ in range(20)]
    bright = [(rng.normal(200, 1.0, (36, 64))).clip(0, 255) for _ in range(20)]
    index = build_video_index(_samples_from_frames(dark + bright))
    assert index["cut_count"] == 1
    # diffs[19] sits between frame 19 and 20 -> cut at frame 20 (2500ms).
    assert index["cut_points_ms"] == [2500]
    assert len(index["scenes"]) == 2


def test_collect_video_facts_reuses_predecoded_gray_samples(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.run_review.objective import facts as facts_module

    samples = _samples_from_frames(
        [np.full((36, 64), 40), np.full((36, 64), 200)],
    )
    monkeypatch.setattr(
        facts_module,
        "is_operator_enabled",
        lambda key: key == "video_index",
    )

    def unexpected_decode(_path):
        raise AssertionError("predecoded frames must not be decoded again")

    monkeypatch.setattr(facts_module, "sample_gray_frames", unexpected_decode)
    result = collect_video_facts(
        Path("unused.mp4"),
        predecoded_gray_samples=samples,
    )
    assert result["video_index"]["sampled_frames"] == 2


def test_easyocr_reader_is_initialized_once_under_concurrency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.run_review.objective import ocr_check

    calls: list[int] = []

    def fake_reader(*_args, **_kwargs):
        calls.append(1)
        time.sleep(0.02)
        return object()

    monkeypatch.setattr(
        ocr_check,
        "easyocr",
        SimpleNamespace(Reader=fake_reader),
    )
    monkeypatch.setattr(ocr_check, "_READER", None)
    reader_factory = ocr_check._reader  # pylint: disable=protected-access
    with ThreadPoolExecutor(max_workers=8) as pool:
        readers = list(pool.map(lambda _index: reader_factory(), range(8)))
    assert len(calls) == 1
    assert all(reader is readers[0] for reader in readers)


def test_freeze_segments_require_sustained_stillness() -> None:
    rng = np.random.default_rng(3)
    moving = [(rng.normal(128, 30, (36, 64))).clip(0, 255) for _ in range(10)]
    frozen = [np.full((36, 64), 90.0) for _ in range(10)]
    index = build_video_index(_samples_from_frames(moving + frozen))
    assert index["freeze_segments"], "sustained stillness must be recorded"
    assert index["freeze_segments"][-1]["end_ms"] == 19 * 125


def test_machine_params_report_only_when_declared() -> None:
    info = {"width": 1920, "height": 1080, "duration": 30.0}
    undeclared = machine_param_facts(info)
    assert undeclared["duration_check"] == {"declared": False}
    assert undeclared["aspect_check"] == {"declared": False}
    declared = machine_param_facts(
        info,
        expected_duration_seconds=20.0,
        expected_aspect="9:16",
    )
    assert declared["duration_check"]["deviation_ratio"] == 0.5
    assert declared["duration_check"]["tier_score"] == 0.0
    assert declared["aspect_check"]["tier_score"] == 0.0


def test_av_sync_tiers_and_worst_sentences() -> None:
    facts = av_sync_facts(
        [
            {"start_ms": 3050, "end_ms": 4000, "text": "on the cut"},
            {"start_ms": 9000, "end_ms": 9500, "text": "far away"},
        ],
        cut_points_ms=[3000],
    )
    assert facts["measured"] is True
    assert facts["max_offset_seconds"] == 6.0
    assert facts["worst_sentences"][0]["text"] == "far away"


def test_av_sync_unmeasurable_without_cuts() -> None:
    facts = av_sync_facts([{"start_ms": 100, "text": "hi"}], [])
    assert facts["measured"] is False


def test_audio_content_facts_flag_missing_track_as_fact() -> None:
    facts = audio_content_facts(None, 16000)
    assert facts["has_audio_track"] is False
    # The absence is framed as context, never as a defect.
    assert "计划" in facts["note"]


def test_audio_content_facts_detect_tonal_music() -> None:
    sample_rate = 16000
    t = np.arange(sample_rate * 3) / sample_rate
    tone = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    facts = audio_content_facts(tone, sample_rate)
    assert facts["has_audio_track"] is True
    assert facts["music_votes"]["harmonic"] is True


@requires_ffmpeg
def test_collect_video_facts_end_to_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Simulate an ASR-capable environment so the av_sync operator's
    # auto (能开尽开) resolution keeps it on.
    from models import config as model_config

    monkeypatch.setattr(model_config, "get_asr_api_key", lambda: "test-key")
    video = tmp_path / "clip.mp4"
    subprocess.run(
        [
            _FFMPEG,
            "-y",
            "-hide_banner",
            "-nostats",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x180:rate=12:duration=3",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x180:r=12:d=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=5",
            "-filter_complex",
            "[0:v][1:v]concat=n=2:v=1:a=0[v]",
            "-map",
            "[v]",
            "-map",
            "2:a",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(video),
        ],
        check=True,
        capture_output=True,
    )
    facts = collect_video_facts(
        video,
        expected_duration_seconds=5.0,
        expected_aspect="16:9",
        transcript_sentences=[
            {"start_ms": 3050, "end_ms": 4000, "text": "hello"},
        ],
    )
    assert facts["machine_params"]["duration_check"]["tier_score"] == 1.0
    assert facts["video_index"]["cut_count"] == 1
    assert 2800 <= facts["video_index"]["cut_points_ms"][0] <= 3200
    assert facts["av_sync"]["measured"] is True
    assert facts["av_sync"]["max_offset_seconds"] <= 0.3
    assert facts["audio_content"]["has_audio_track"] is True
    # The testsrc->blue pair must raise a consistency suspicion...
    consistency = facts["cross_shot_consistency"]
    assert consistency["measured"] is True
    assert consistency["suspect_pairs"], "hard subject change must be flagged"
    # ...and every operator either measured or recorded WHY it skipped.
    for key, block in facts.items():
        assert isinstance(block, dict), key
    # cv2 absent in CI: camera motion degrades to partial, never errors.
    camera = facts["camera_motion"]
    assert camera.get("measured") in (True, "partial")
    block = render_facts_block(facts)
    assert "事实提示" in block
    assert "objective facts" in block


@requires_ffmpeg
def test_collect_image_facts(tmp_path: Path) -> None:
    image = tmp_path / "img.png"
    subprocess.run(
        [
            _FFMPEG,
            "-y",
            "-hide_banner",
            "-nostats",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x180:rate=1:duration=1",
            "-frames:v",
            "1",
            str(image),
        ],
        check=True,
        capture_output=True,
    )
    facts = collect_image_facts(image)
    assert facts["light_metrics"]["sharpness"]["measured"] is True
    assert facts["light_metrics"]["color"]["measured"] is True
