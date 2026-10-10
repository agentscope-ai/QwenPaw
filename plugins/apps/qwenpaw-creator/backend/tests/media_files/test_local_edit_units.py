# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access
"""The published video's real duration drives the element span.

An s2v clip only lasts as long as its driving audio; publishing must
shrink the span to the delivered footage and ripple later elements.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import shutil
import subprocess

import pytest

from domain.enums import CreatorCommandType
from domain.errors import StorageIntegrityError
from services.media_files import keyframe_cache
from services.media_files.element_adapter import reconcile_candidate_span
from services.media_files.local_execution import (
    FfmpegLocalMediaRunner,
    LocalMediaExecutionSpec,
    LocalMediaInput,
    _motion_document_matches_text,
)


def test_motion_copy_match_uses_browser_visible_html_entities() -> None:
    html = "<div><b>GitHub</b><i>&nbsp;</i><b>新手</b></div>"
    assert _motion_document_matches_text(html, "GitHub 新手")
    assert not _motion_document_matches_text(html, "GitHub 高手")


def _candidate(ticks_per_second: int = 1000) -> dict:
    return {
        "timelines": {
            "items": {
                "timeline:main": {
                    "ticks_per_second": ticks_per_second,
                    "elements_by_id": {
                        "el:talk": {
                            "span": {"start_tick": 0, "duration_tick": 5000},
                        },
                        "el:shot2": {
                            "span": {
                                "start_tick": 5000,
                                "duration_tick": 5000,
                            },
                        },
                        "el:narration2": {
                            "span": {
                                "start_tick": 5000,
                                "duration_tick": 5000,
                            },
                        },
                        # Starts inside the shrunk segment: stays put.
                        "el:overlap": {
                            "span": {
                                "start_tick": 1000,
                                "duration_tick": 1000,
                            },
                        },
                    },
                },
            },
        },
    }


def _reconcile(
    candidate: dict,
    seconds: float | None,
    element_id: str = "el:talk",
) -> bool:
    return reconcile_candidate_span(
        candidate,
        element_id=element_id,
        actual_duration_seconds=seconds,
    )


def _elements(candidate: dict) -> dict:
    return candidate["timelines"]["items"]["timeline:main"]["elements_by_id"]


def test_shorter_footage_shrinks_span_and_ripples_later_elements() -> None:
    candidate = _candidate()
    assert _reconcile(candidate, 2.8) is True
    elements = _elements(candidate)
    assert elements["el:talk"]["span"]["duration_tick"] == 2800
    # Everything that started at/after the old end moves forward together.
    assert elements["el:shot2"]["span"]["start_tick"] == 2800
    assert elements["el:narration2"]["span"]["start_tick"] == 2800
    # An element inside the shrunk window keeps its position.
    assert elements["el:overlap"]["span"]["start_tick"] == 1000
    # Replay is idempotent: the span is already reconciled.
    assert _reconcile(candidate, 2.8) is False
    assert elements["el:shot2"]["span"]["start_tick"] == 2800


def _filter(**kwargs: object) -> str:
    return FfmpegLocalMediaRunner._placement_filter(
        None,
        canvas_size=(1280, 720),
        duration_seconds=6.0,
        **kwargs,
    )


def test_freeze_pads_video_and_references_audio_only_when_present():
    chain = _filter(freeze_duration=2.0, freeze_audio=True)
    assert "tpad=stop_mode=clone:stop_duration=2.000000" in chain
    assert "[0:a]apad=pad_dur=2.000000[a]" in chain
    # Generated R2V footage usually has no audio track; referencing [0:a]
    # would make ffmpeg reject the whole filtergraph.
    silent = _filter(freeze_duration=2.0, freeze_audio=False)
    assert "tpad=stop_mode=clone:stop_duration=2.000000" in silent
    assert "[0:a]" not in silent


def test_playback_rate_retimes_picture_and_source_audio() -> None:
    chain = _filter(playback_rate=0.25, retime_audio=True)
    assert "setpts=(PTS-STARTPTS)/0.25" in chain
    assert "[0:a]atempo=0.5,atempo=0.5[a]" in chain


@pytest.mark.parametrize(
    "playback_rate",
    [0.0, -1.0, float("nan"), float("inf")],
)
def test_atempo_filters_reject_invalid_playback_rate(
    playback_rate: float,
) -> None:
    with pytest.raises(ValueError, match="finite and greater than zero"):
        FfmpegLocalMediaRunner._atempo_filters(playback_rate)


@pytest.mark.parametrize(
    "playback_rate",
    [
        float.fromhex("0x0.0000000000001p-1022"),
        float.fromhex("0x1.fffffffffffffp+1023"),
    ],
)
def test_atempo_filters_bound_extreme_finite_rates(
    playback_rate: float,
) -> None:
    with pytest.raises(ValueError, match="supported audio retiming range"):
        FfmpegLocalMediaRunner._atempo_filters(playback_rate)


_FFMPEG = shutil.which("ffmpeg")
_FFPROBE = shutil.which("ffprobe")


@pytest.mark.skipif(
    _FFMPEG is None or _FFPROBE is None,
    reason="ffmpeg is not installed",
)
def test_still_image_input_renders_a_timed_segment(tmp_path) -> None:
    image = tmp_path / "backdrop.png"
    subprocess.run(
        [
            _FFMPEG,
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=orange:s=640x360:d=0.1",
            "-frames:v",
            "1",
            str(image),
        ],
        check=True,
    )
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    output = tmp_path / "output.mp4"
    spec = LocalMediaExecutionSpec(
        command=CreatorCommandType.COMPOSE_FINAL_VIDEO,
        target_ref="timeline:main",
        task_id="task-still",
        work_dir=work_dir,
        output_path=output,
        inputs=(
            LocalMediaInput(
                version_id="artifact-version-still",
                file_id="file-still",
                checksum="sha256:still",
                media_type="image/png",
                path=image,
                source_ref="element:bg-1",
                start_seconds=0.0,
                end_seconds=2.0,
                duration_seconds=None,
            ),
        ),
        transitions=(),
        audio_plan="preserve",
        expected_duration_seconds=2.0,
        canvas_size=(640, 360),
    )
    runner = FfmpegLocalMediaRunner(_FFMPEG)
    result = asyncio.run(runner.render(spec))
    assert result["media_type"] == "video/mp4"

    assert output.exists()
    probe = subprocess.run(
        [
            _FFPROBE,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    duration = float(probe.stdout.strip())
    assert duration == pytest.approx(2.0, abs=0.15)


@pytest.mark.skipif(
    _FFMPEG is None or _FFPROBE is None,
    reason="ffmpeg is not installed",
)
@pytest.mark.parametrize(
    ("playback_rate", "expected_duration"),
    ((0.5, 4.0), (2.0, 1.0)),
)
def test_video_playback_rate_controls_real_output_duration(
    tmp_path,
    playback_rate: float,
    expected_duration: float,
) -> None:
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            _FFMPEG,
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=640x360:rate=30:duration=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=44100:duration=2",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(source),
        ],
        check=True,
    )
    rate_label = str(playback_rate).replace(".", "-")
    work_dir = tmp_path / f"work-{rate_label}"
    work_dir.mkdir()
    output = tmp_path / f"retimed-{rate_label}.mp4"
    spec = LocalMediaExecutionSpec(
        command=CreatorCommandType.COMPOSE_FINAL_VIDEO,
        target_ref="timeline:main",
        task_id=f"task-{rate_label}",
        work_dir=work_dir,
        output_path=output,
        inputs=(
            LocalMediaInput(
                version_id=f"asset-version-{rate_label}",
                file_id=f"file-{rate_label}",
                checksum=f"sha256:rate-{rate_label}-source-v1",
                media_type="video/mp4",
                path=source,
                source_ref=f"element:{rate_label}",
                start_seconds=0.0,
                end_seconds=2.0,
                duration_seconds=2.0,
                playback_rate=playback_rate,
            ),
        ),
        transitions=(),
        audio_plan="preserve",
        expected_duration_seconds=expected_duration,
        canvas_size=(640, 360),
    )

    asyncio.run(FfmpegLocalMediaRunner(_FFMPEG).render(spec))

    probe = subprocess.run(
        [
            _FFPROBE,
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,duration",
            "-of",
            "csv=p=0",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    durations = {
        kind: float(duration)
        for kind, duration in (
            line.split(",") for line in probe.stdout.splitlines()
        )
    }
    assert durations["video"] == pytest.approx(expected_duration, abs=0.15)
    assert durations["audio"] == pytest.approx(expected_duration, abs=0.15)


def _materialize_keyframe(project_root: Path, source: Path, timestamp: float):
    return keyframe_cache.materialize_keyframe(
        project_root,
        source_path=source,
        source_identity="sha256:source",
        timestamp_seconds=timestamp,
        width=640,
        ffmpeg_path="/fake/ffmpeg",
    )


def test_materialize_keyframe_persists_and_reuses_deterministic_jpeg(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project-1"
    project_root.mkdir()
    source = project_root / "source.mp4"
    source.write_bytes(b"source-video")
    calls: list[list[str]] = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        Path(command[-1]).write_bytes(b"JPEG@" + command[6].encode("ascii"))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(keyframe_cache.subprocess, "run", fake_run)
    first = _materialize_keyframe(project_root, source, 4.5004)
    replay = _materialize_keyframe(project_root, source, 4.5)

    assert first == replay
    assert first.path.parent == project_root / "runtime" / "keyframe-cache"
    assert first.path.suffix == ".jpg"
    assert first.path.read_bytes() == b"JPEG@4.500"
    assert first.timestamp_seconds == 4.5
    assert len(calls) == 1
    assert calls[0][0] == "/fake/ffmpeg"
    assert calls[0][5:7] == ["-ss", "4.500"]


def test_materialize_keyframe_rejects_symlink_source(tmp_path: Path) -> None:
    project_root = tmp_path / "project-1"
    project_root.mkdir()
    real_source = project_root / "real.mp4"
    real_source.write_bytes(b"source-video")
    symlink = project_root / "source.mp4"
    symlink.symlink_to(real_source)

    with pytest.raises(StorageIntegrityError, match="安全的普通文件"):
        _materialize_keyframe(project_root, symlink, 1)
