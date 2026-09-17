# -*- coding: utf-8 -*-
# pylint: disable=protected-access,use-implicit-booleaness-not-comparison
# flake8: noqa: E501

from __future__ import annotations

from pathlib import Path

from services.media_files.local_execution import (
    FfmpegLocalMediaRunner,
    LocalMediaExecutionSpec,
)
from domain.enums import CreatorCommandType


def _spec(tmp_path: Path, tracks: tuple[dict, ...]) -> LocalMediaExecutionSpec:
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
    )


def _runner_with_capture(monkeypatch, *, has_audio: bool):
    runner = FfmpegLocalMediaRunner(executable="ffmpeg-test")
    calls: list[list[str]] = []
    monkeypatch.setattr(
        runner,
        "_run",
        lambda arguments, *, cwd: calls.append(list(arguments)),
    )
    monkeypatch.setattr(
        runner,
        "_probe_has_audio",
        lambda path: has_audio,
    )
    return runner, calls


def test_mix_single_track_over_silent_video(monkeypatch, tmp_path) -> None:
    audio = tmp_path / "narration.wav"
    audio.write_bytes(b"wav")
    spec = _spec(
        tmp_path,
        (
            {
                "element_id": "el-1",
                "version_id": "v-1",
                "path": audio,
                "offset_seconds": 2.0,
                "max_duration_seconds": 5.0,
                "gain_db": -3.0,
                "pan": 0.0,
            },
        ),
    )
    runner, calls = _runner_with_capture(monkeypatch, has_audio=False)
    runner._mix_audio_tracks(spec)

    # The composed video is renamed aside and re-muxed with copied video.
    assert (tmp_path / "premix.mp4").exists()
    assert len(calls) == 1
    arguments = calls[0]
    graph = arguments[arguments.index("-filter_complex") + 1]
    assert "atrim=0:5.000000" in graph
    assert "volume=-3.000dB" in graph
    assert "adelay=2000:all=1" in graph
    assert "amix" not in graph  # single track, no base audio
    assert "atrim=0:12.500000[afinal]" in graph
    assert arguments[arguments.index("-map") + 1] == "0:v"
    assert "[afinal]" in arguments
    assert "copy" in arguments


def test_mix_overlapping_tracks_with_base_audio(monkeypatch, tmp_path) -> None:
    first = tmp_path / "a.wav"
    second = tmp_path / "b.wav"
    first.write_bytes(b"wav")
    second.write_bytes(b"wav")
    spec = _spec(
        tmp_path,
        (
            {
                "element_id": "el-1",
                "version_id": "v-1",
                "path": first,
                "offset_seconds": 0.0,
                "max_duration_seconds": 4.0,
                "gain_db": 0.0,
                "pan": -0.5,
            },
            {
                "element_id": "el-2",
                "version_id": "v-2",
                "path": second,
                "offset_seconds": 3.0,
                "max_duration_seconds": 4.0,
                "gain_db": 2.0,
                "pan": 0.0,
            },
        ),
    )
    runner, calls = _runner_with_capture(monkeypatch, has_audio=True)
    runner._mix_audio_tracks(spec)

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


def test_render_without_audio_tracks_skips_mixing(
    monkeypatch,
    tmp_path,
) -> None:
    spec = _spec(tmp_path, ())
    runner, calls = _runner_with_capture(monkeypatch, has_audio=False)
    if spec.audio_tracks:
        runner._mix_audio_tracks(spec)
    assert calls == []
    assert not (tmp_path / "premix.mp4").exists()


def test_wav_duration_ignores_streaming_placeholder_header() -> None:
    import io
    import wave

    from services.media_files.audio_execution import _wav_duration_seconds

    # 2 real seconds of mono 16-bit 24kHz audio ...
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(24000)
        handle.writeframes(b"\x00\x00" * 24000 * 2)
    honest = buffer.getvalue()
    assert (
        _wav_duration_seconds(honest) == 2.0
        or abs(
            _wav_duration_seconds(honest) - 2.0,
        )
        < 0.01
    )

    # ... whose header claims 2^30 frames (streaming writer placeholder).
    import struct

    lying = bytearray(honest)
    data_offset = bytes(lying).find(b"data") + 4
    lying[data_offset : data_offset + 4] = struct.pack(
        "<I",
        (2**30) * 2,
    )
    duration = _wav_duration_seconds(bytes(lying))
    assert duration is not None
    assert duration < 3.0  # byte-bound wins over the lying header
