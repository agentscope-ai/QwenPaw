# -*- coding: utf-8 -*-
# pylint: disable=protected-access,use-implicit-booleaness-not-comparison
# flake8: noqa: E501
"""Local media tooling: overlays, audio mixing, beat grid, probe."""

from __future__ import annotations

import asyncio
import io
import json
import struct
import subprocess
import sys
import wave
from pathlib import Path

import pytest
from PIL import Image

from domain.enums import CreatorCommandType
from services import object_grounding
from services.media_files import overlay as overlay_tools
from services.media_files.audio_execution import _wav_duration_seconds
from services.media_files.beat_grid import (
    BeatGrid,
    BeatGridUnavailable,
    extract_beat_grid,
)
from services.media_files.local_execution import (
    FfmpegLocalMediaRunner,
    LocalMediaExecutionSpec,
)
from services.runtime_files import media_probe

pytestmark = pytest.mark.unit


class _Completed:
    returncode = 0
    stdout = ""
    stderr = ""


def _install_render_fakes(monkeypatch, commands: list[list[str]]) -> None:
    def render_png(*args, **_kwargs) -> bool:
        Path(args[-1]).write_bytes(b"png")
        return True

    def run(command, **_kwargs):
        commands.append(command)
        Path(command[-1]).write_bytes(b"video")
        return _Completed()

    monkeypatch.setattr(overlay_tools, "_render_pet_os_png", render_png)
    monkeypatch.setattr(overlay_tools.subprocess, "run", run)


def _loc(**overrides) -> dict:
    return {"anchor_x": 0.5, "anchor_y": 0.5, "opacity": 1} | overrides


def test_overlay_renderers_use_bubble_title_tools_and_timing(
    monkeypatch,
    tmp_path,
) -> None:
    commands: list[list[str]] = []
    _install_render_fakes(monkeypatch, commands)
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")

    pet_out = tmp_path / "pet.mp4"
    result = overlay_tools.render_pet_os_overlay(
        ffmpeg_path="ffmpeg",
        input_path=source,
        output_path=pet_out,
        text="今天也好困啊",
        vibe="chill",
        video_size=(1280, 720),
        appear_at=0.5,
        duration=2.5,
    )
    assert result.success is True
    expression = commands[0][commands[0].index("-filter_complex") + 1]
    assert "overlay=0:0:shortest=1" in expression
    assert "between(t,0.5,3.0)" in expression
    assert not pet_out.with_suffix(".overlay.png").exists()


def test_pet_os_png_uses_the_element_anchor_box(tmp_path) -> None:
    output = tmp_path / "placed.png"
    location = _loc(x=0.9, y=0.29, width=0.18, height=0.53, rotation_degrees=0)
    assert overlay_tools._render_pet_os_png(
        "这里真的安全吗？",
        "curious",
        1280,
        720,
        output,
        location=location,
    )
    alpha_bounds = Image.open(output).getchannel("A").getbbox()
    assert alpha_bounds is not None
    left, top, right, bottom = alpha_bounds
    assert 1037 <= left < right <= 1268
    assert 17 <= top < bottom <= 399


def _spec(
    tmp_path: Path,
    tracks: tuple[dict, ...],
    speech_windows: tuple[tuple[float, float], ...] = (),
) -> LocalMediaExecutionSpec:
    output = tmp_path / "output.mp4"
    output.write_bytes(b"video")
    return LocalMediaExecutionSpec(
        command=CreatorCommandType.COMPOSE_FINAL_VIDEO,
        target_ref="timeline:t1",
        task_id="task-1",
        work_dir=tmp_path,
        output_path=output,
        inputs=(),
        transitions=(),
        audio_plan="",
        expected_duration_seconds=12.5,
        canvas_size=(1280, 720),
        audio_tracks=tracks,
        speech_windows=speech_windows,
    )


def _track(path: Path, **overrides) -> dict:
    base = {
        "element_id": "el-1",
        "version_id": "v-1",
        "path": path,
        "offset_seconds": 0.0,
        "max_duration_seconds": 4.0,
        "gain_db": 0.0,
        "pan": 0.0,
    }
    return base | overrides


def _runner_with_capture(monkeypatch, *, has_audio: bool):
    runner = FfmpegLocalMediaRunner(executable="ffmpeg-test")
    calls: list[list[str]] = []
    monkeypatch.setattr(
        runner,
        "_run",
        lambda arguments, *, cwd: calls.append(list(arguments)),
    )
    monkeypatch.setattr(runner, "_probe_has_audio", lambda path: has_audio)
    return runner, calls


def test_mix_overlapping_tracks_with_base_audio(monkeypatch, tmp_path) -> None:
    first = tmp_path / "a.wav"
    second = tmp_path / "b.wav"
    first.write_bytes(b"wav")
    second.write_bytes(b"wav")
    tracks = (
        _track(first, pan=-0.5),
        _track(second, element_id="el-2", offset_seconds=3.0, gain_db=2.0),
    )
    runner, calls = _runner_with_capture(monkeypatch, has_audio=True)
    runner._mix_audio_tracks(_spec(tmp_path, tracks))

    graph = calls[0][calls[0].index("-filter_complex") + 1]
    # Overlapping narration windows (0-4s, 3-7s) merge into one duck window.
    assert (
        "[0:a]aformat=channel_layouts=stereo,"
        "volume=0.35:enable='between(t,0.000,7.000)'[base]" in graph
    )
    assert "amix=inputs=3:duration=longest:normalize=0[aout]" in graph
    assert "pan=stereo|c0=1.000*c0|c1=0.500*c1" in graph
    assert "volume=2.000dB" in graph
    assert "adelay=3000:all=1" in graph
    # Delivery loudness now runs as a separate final pass, not in the mix.
    assert "loudnorm" not in graph
    assert calls[0][calls[0].index("-map") + 3] == "[afinal]"


def test_bgm_plays_as_low_bed_and_ducks_under_speech(
    monkeypatch,
    tmp_path,
) -> None:
    music = tmp_path / "bgm.mp3"
    music.write_bytes(b"mp3")
    tracks = (_track(music, role="bgm", max_duration_seconds=12.5),)
    runner, calls = _runner_with_capture(monkeypatch, has_audio=True)
    runner._mix_audio_tracks(
        _spec(tmp_path, tracks, speech_windows=((2.0, 5.0),)),
    )

    graph = calls[0][calls[0].index("-filter_complex") + 1]
    # Fixed music-bed gain keeps bgm under native dialogue and ambience.
    assert "volume=-12.000dB" in graph
    # BGM ducks itself inside the dialogue window ...
    assert "volume=0.4:enable='between(t,2.000,5.000)'" in graph
    # ... but never ducks the footage audio.
    assert "[0:a]aformat=channel_layouts=stereo[base]" in graph


def test_sfx_neither_ducks_nor_is_ducked(monkeypatch, tmp_path) -> None:
    hit = tmp_path / "hit.wav"
    hit.write_bytes(b"wav")
    tracks = (
        _track(hit, role="sfx", offset_seconds=1.0, max_duration_seconds=2.0),
    )
    runner, calls = _runner_with_capture(monkeypatch, has_audio=True)
    runner._mix_audio_tracks(_spec(tmp_path, tracks))

    graph = calls[0][calls[0].index("-filter_complex") + 1]
    assert "volume=0.35" not in graph
    assert "volume=0.4" not in graph
    assert "volume=-12.000dB" not in graph


def test_bgm_segments_crossfade_via_overlapping_explicit_fades(
    monkeypatch,
    tmp_path,
) -> None:
    first = tmp_path / "bed-a.mp3"
    second = tmp_path / "bed-b.mp3"
    first.write_bytes(b"mp3")
    second.write_bytes(b"mp3")
    # Two bgm segments whose spans overlap by 2s: each fades at its edge
    # while amix sums them, forming the crossfade.
    tracks = (
        _track(
            first,
            role="bgm",
            max_duration_seconds=8.0,
            fade_in_seconds=2.0,
            fade_out_seconds=2.0,
        ),
        _track(
            second,
            element_id="el-2",
            role="bgm",
            offset_seconds=6.0,
            max_duration_seconds=6.5,
            fade_in_seconds=2.0,
            fade_out_seconds=2.0,
        ),
    )
    runner, calls = _runner_with_capture(monkeypatch, has_audio=True)
    runner._mix_audio_tracks(_spec(tmp_path, tracks))

    graph = calls[0][calls[0].index("-filter_complex") + 1]
    assert "afade=t=in:d=2.000" in graph
    assert "afade=t=out:st=6.000:d=2.000" in graph
    assert "afade=t=out:st=4.500:d=2.000" in graph
    assert "adelay=6000:all=1" in graph
    assert "amix=inputs=3" in graph


def test_audio_fades_are_clamped_to_the_span(monkeypatch, tmp_path) -> None:
    short = tmp_path / "sting.wav"
    short.write_bytes(b"wav")
    tracks = (
        _track(
            short,
            role="bgm",
            max_duration_seconds=2.0,
            fade_in_seconds=2.0,
            fade_out_seconds=2.0,
        ),
    )
    runner, calls = _runner_with_capture(monkeypatch, has_audio=True)
    runner._mix_audio_tracks(_spec(tmp_path, tracks))

    graph = calls[0][calls[0].index("-filter_complex") + 1]
    # 2s+2s does not fit a 2s span: both scale down to 1s.
    assert "afade=t=in:d=1.000" in graph
    assert "afade=t=out:st=1.000:d=1.000" in graph


def test_unset_fades_resolve_to_a_span_adaptive_bgm_default() -> None:
    from services.media_files.local_execution import _resolved_fade_seconds
    from services.project_files.models import AudioCreation

    def creation(**overrides) -> AudioCreation:
        return AudioCreation(
            source_asset_version_id="audio-version-1",
            role="bgm",
            **overrides,
        )

    # Long span: the default caps at 2s per edge.
    assert _resolved_fade_seconds(creation(), 20.0) == (2.0, 2.0)
    # Short span: min(2, span/4) keeps ramps from swallowing the bed.
    assert _resolved_fade_seconds(creation(), 3.2) == (0.8, 0.8)
    # Explicit values are authoritative, including an explicit 0.
    assert _resolved_fade_seconds(
        creation(fade_in_seconds=0.0, fade_out_seconds=5.0),
        20.0,
    ) == (0.0, 5.0)
    # Non-bgm roles keep hard edges by default.
    narration = AudioCreation(
        source_asset_version_id="audio-version-1",
        role="narration",
    )
    assert _resolved_fade_seconds(narration, 20.0) == (0.0, 0.0)


def test_explicit_narration_still_ducks_footage(monkeypatch, tmp_path) -> None:
    voice = tmp_path / "vo.wav"
    voice.write_bytes(b"wav")
    tracks = (
        _track(
            voice,
            role="narration",
            offset_seconds=2.0,
            max_duration_seconds=3.0,
        ),
    )
    runner, calls = _runner_with_capture(monkeypatch, has_audio=True)
    runner._mix_audio_tracks(_spec(tmp_path, tracks))

    graph = calls[0][calls[0].index("-filter_complex") + 1]
    assert "volume=0.35:enable='between(t,2.000,5.000)'" in graph
    assert "volume=-12.000dB" not in graph


def test_concat_fades_segment_audio_edges(monkeypatch, tmp_path) -> None:
    first = tmp_path / "a.mp4"
    second = tmp_path / "b.mp4"
    first.write_bytes(b"video")
    second.write_bytes(b"video")
    runner, calls = _runner_with_capture(monkeypatch, has_audio=True)
    monkeypatch.setattr(
        runner,
        "_probe_duration_seconds_or_none",
        lambda path: 4.0,
    )
    runner._concat([first, second], tmp_path / "out.mp4", work_dir=tmp_path)

    graph = calls[0][calls[0].index("-filter_complex") + 1]
    # Each voiced segment gets short edge fades so unrelated native
    # ambiences step smoothly at the hard cut.
    assert (
        "[1:a]afade=t=in:d=0.040,afade=t=out:st=3.960:d=0.040[fade0]" in graph
    )
    assert (
        "[2:a]afade=t=in:d=0.040,afade=t=out:st=3.960:d=0.040[fade1]" in graph
    )
    assert "[fade0][fade1]concat=n=2:v=0:a=1" in graph


def test_concat_skips_edge_fades_when_duration_is_unknown(
    monkeypatch,
    tmp_path,
) -> None:
    first = tmp_path / "a.mp4"
    second = tmp_path / "b.mp4"
    first.write_bytes(b"video")
    second.write_bytes(b"video")
    runner, calls = _runner_with_capture(monkeypatch, has_audio=True)
    # Probe failure: better a hard cut than a fade landing mid-clip.
    monkeypatch.setattr(
        runner,
        "_probe_duration_seconds_or_none",
        lambda path: None,
    )
    runner._concat([first, second], tmp_path / "out.mp4", work_dir=tmp_path)

    graph = calls[0][calls[0].index("-filter_complex") + 1]
    assert "afade" not in graph
    assert "[1:a][2:a]concat=n=2:v=0:a=1" in graph


def test_delivery_loudness_applies_measured_linear_pass(
    monkeypatch,
    tmp_path,
) -> None:
    runner, calls = _runner_with_capture(monkeypatch, has_audio=True)
    measured = {
        "input_i": "-23.1",
        "input_tp": "-5.2",
        "input_lra": "6.8",
        "input_thresh": "-33.5",
        "target_offset": "0.3",
    }
    monkeypatch.setattr(runner, "_measure_loudness", lambda path: measured)
    spec = _spec(tmp_path, ())

    warning = runner._normalize_delivery_loudness(spec)

    assert warning is None
    graph = calls[0][calls[0].index("-af") + 1]
    # Two-pass linear loudnorm: one constant gain, no sliding-window
    # pumping of the deliberately quiet music bed.
    assert "loudnorm=I=-16.0:TP=-1.5:LRA=11.0" in graph
    assert "measured_I=-23.1" in graph
    assert "measured_TP=-5.2" in graph
    assert "measured_LRA=6.8" in graph
    assert "measured_thresh=-33.5" in graph
    assert "offset=0.3" in graph
    assert "linear=true" in graph
    assert "aresample=48000" in graph
    assert calls[0][calls[0].index("-c:v") + 1] == "copy"


def test_delivery_loudness_failures_keep_the_unnormalized_film(
    monkeypatch,
    tmp_path,
) -> None:
    # Measurement failure: warn, run nothing, keep the film untouched.
    runner, calls = _runner_with_capture(monkeypatch, has_audio=True)
    monkeypatch.setattr(runner, "_measure_loudness", lambda path: None)
    spec = _spec(tmp_path, ())
    warning = runner._normalize_delivery_loudness(spec)
    assert warning is not None and "响度测量失败" in warning
    assert calls == []
    assert spec.output_path.read_bytes() == b"video"

    # Apply failure: restore the pre-loudnorm film and warn.
    monkeypatch.setattr(
        runner,
        "_measure_loudness",
        lambda path: {
            "input_i": "-23.1",
            "input_tp": "-5.2",
            "input_lra": "6.8",
            "input_thresh": "-33.5",
            "target_offset": "0.3",
        },
    )

    def failing_run(arguments, *, cwd):
        raise RuntimeError("ffmpeg exploded")

    monkeypatch.setattr(runner, "_run", failing_run)
    warning = runner._normalize_delivery_loudness(spec)
    assert warning is not None and "保留未归一" in warning
    assert spec.output_path.read_bytes() == b"video"


def test_measure_loudness_parses_the_loudnorm_json_tail(
    monkeypatch,
    tmp_path,
) -> None:
    from services.media_files import local_execution as local_execution_mod

    stderr = (
        "size=N/A time=00:00:12.50 bitrate=N/A speed=25x\n"
        "[Parsed_loudnorm_0 @ 0x600] \n"
        "{\n"
        '    "input_i" : "-23.10",\n'
        '    "input_tp" : "-5.20",\n'
        '    "input_lra" : "6.80",\n'
        '    "input_thresh" : "-33.50",\n'
        '    "output_i" : "-16.00",\n'
        '    "target_offset" : "0.30"\n'
        "}\n"
    )

    class _Measured:
        returncode = 0
        stdout = ""

    _Measured.stderr = stderr

    monkeypatch.setattr(
        local_execution_mod.subprocess,
        "run",
        lambda *args, **kwargs: _Measured(),
    )
    runner = FfmpegLocalMediaRunner(executable="ffmpeg-test")
    measured = runner._measure_loudness(tmp_path / "film.mp4")
    assert measured == {
        "input_i": "-23.10",
        "input_tp": "-5.20",
        "input_lra": "6.80",
        "input_thresh": "-33.50",
        "target_offset": "0.30",
    }


def test_wav_duration_ignores_streaming_placeholder_header() -> None:
    # 2 real seconds of mono 16-bit 24kHz audio ...
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(24000)
        handle.writeframes(b"\x00\x00" * 24000 * 2)
    honest = buffer.getvalue()
    assert abs(_wav_duration_seconds(honest) - 2.0) < 0.01

    # ... whose header claims 2^30 frames (streaming writer placeholder).
    lying = bytearray(honest)
    data_offset = bytes(lying).find(b"data") + 4
    lying[data_offset : data_offset + 4] = struct.pack("<I", (2**30) * 2)
    duration = _wav_duration_seconds(bytes(lying))
    assert duration is not None
    assert duration < 3.0  # byte-bound wins over the lying header


def test_beat_snapped_span_shifts_decorations_forward_only() -> None:
    from services.media_files.motion_design import _beat_snapped_span
    from services.project_files.models import TimelineSpan

    grid = BeatGrid(beats_ms=(0, 500, 1000), tempo_bpm=120.0)
    span = TimelineSpan(start_tick=880, duration_tick=2000)
    # 880ms → next beat 1000ms; the end (2880) stays fixed.
    snapped = _beat_snapped_span(span, (grid, 0), 1000)
    assert snapped.start_tick == 1000
    assert snapped.duration_tick == 1880
    # A backward-only snap (1100 → 1000) is refused: forward shifts only.
    unchanged = _beat_snapped_span(
        TimelineSpan(start_tick=1100, duration_tick=2000),
        (grid, 0),
        1000,
    )
    assert unchanged.start_tick == 1100
    assert _beat_snapped_span(span, None, 1000) is span


def test_missing_librosa_is_declared(tmp_path, monkeypatch) -> None:
    audio = tmp_path / "bgm.wav"
    audio.write_bytes(b"RIFF")
    monkeypatch.setitem(sys.modules, "librosa", None)
    # ``import librosa`` finds the None sentinel and raises ImportError.
    with pytest.raises(BeatGridUnavailable, match="librosa"):
        extract_beat_grid(audio)


def _image_bytes(width: int = 1000, height: int = 800) -> bytes:
    image = Image.new("RGB", (width, height), (200, 200, 200))
    # A red target patch at the normalized center-right (600-700, 300-400).
    for x in range(600, 700):
        for y in range(240, 320):
            image.putpixel((x, y), (255, 0, 0))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_crop_region_expands_clamps_and_upscales() -> None:
    content = _image_bytes()
    cropped = object_grounding.crop_region_bytes(content, [600, 300, 700, 400])
    image = Image.open(io.BytesIO(cropped))
    # Upscaled so the short side reaches the observation floor.
    assert min(image.size) >= object_grounding.CROP_MIN_SHORT_SIDE
    edge = object_grounding.crop_region_bytes(content, [0, 0, 100, 100])
    assert Image.open(io.BytesIO(edge)).size[0] > 0


def test_crop_and_observe_uploads_and_asks(monkeypatch) -> None:
    content = _image_bytes()
    uploads: list[bytes] = []

    async def fake_upload(data: bytes) -> str:
        uploads.append(data)
        return "https://example.invalid/crop.jpg"

    async def fake_chat(parts, **_kwargs):
        assert parts[0]["type"] == "video_url" or "image" in str(parts[0])
        return "放大后可见红色标记块。"

    monkeypatch.setattr(
        object_grounding.vlm_model,
        "multimodal_media_part",
        lambda url, kind: {"type": "image_url", "image_url": {"url": url}},
    )
    monkeypatch.setattr(
        object_grounding.vlm_model,
        "chat_completion",
        fake_chat,
    )
    config = object_grounding.model_config
    monkeypatch.setattr(config, "get_vlm_timeout_seconds", lambda: 60)
    monkeypatch.setattr(config, "get_vlm_model_name", lambda: "qwen3.7-plus")

    result = asyncio.run(
        object_grounding.crop_region_and_observe(
            content,
            [600, 300, 700, 400],
            "标记块是什么颜色？",
            upload_url_for=fake_upload,
        ),
    )
    assert uploads, "the cropped bytes must be uploaded"
    assert "红色" in result["answer"]
    assert result["bbox2d"] == [600, 300, 700, 400]


def _probe_run(monkeypatch, *, code: int, out: str = "", err: str = ""):
    monkeypatch.setattr(
        media_probe.subprocess,
        "run",
        lambda *_a, **_k: subprocess.CompletedProcess(
            ["probe"],
            code,
            out,
            err,
        ),
    )


def test_ffprobe_json_is_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "streams": [
            {"codec_type": "video", "width": 1920, "height": 1080},
            {"codec_type": "audio", "sample_rate": "48000", "channels": 2},
        ],
        "format": {"duration": "12.345"},
    }
    _probe_run(monkeypatch, code=0, out=json.dumps(payload))

    result = media_probe.probe_media(
        "clip.mp4",
        ffmpeg_path="/tools/ffmpeg",
        ffprobe_path="/tools/ffprobe",
    )

    assert result == media_probe.MediaProbe(
        duration_seconds=12.345,
        width=1920,
        height=1080,
        sample_rate_hz=48000,
        channels=2,
        has_audio=True,
        source="ffprobe",
    )


def test_ffmpeg_fallback_runs_after_ffprobe_rejects_media(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def run(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        calls.append(command[0])
        if command[0].endswith("ffprobe"):
            return subprocess.CompletedProcess(command, 1, "", "probe error")
        return subprocess.CompletedProcess(
            command,
            1,
            "",
            "Duration: 00:00:03.00\nStream #0:0: Video: h264, 640x360",
        )

    monkeypatch.setattr(media_probe.subprocess, "run", run)

    result = media_probe.probe_media(
        "clip.mp4",
        ffmpeg_path="/tools/ffmpeg",
        ffprobe_path="/tools/ffprobe",
    )

    assert calls == ["/tools/ffprobe", "/tools/ffmpeg"]
    assert result.duration_seconds == 3.0
    assert result.source == "ffmpeg"


def test_probe_reports_when_both_executables_are_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(media_probe, "resolve_ffprobe", lambda **_kwargs: None)
    monkeypatch.setattr(media_probe, "resolve_ffmpeg", lambda: None)

    with pytest.raises(media_probe.MediaProbeUnavailable):
        media_probe.probe_media("clip.mp4")
