# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from domain.errors import StorageIntegrityError
from services.media_files import keyframe_cache


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
    first = keyframe_cache.materialize_keyframe(
        project_root,
        source_path=source,
        source_identity="sha256:source",
        timestamp_seconds=4.5004,
        width=640,
        ffmpeg_path="/fake/ffmpeg",
    )
    replay = keyframe_cache.materialize_keyframe(
        project_root,
        source_path=source,
        source_identity="sha256:source",
        timestamp_seconds=4.5,
        width=640,
        ffmpeg_path="/fake/ffmpeg",
    )

    assert first == replay
    assert first.path.parent == project_root / "runtime" / "keyframe-cache"
    assert first.path.suffix == ".jpg"
    assert first.path.read_bytes() == b"JPEG@4.500"
    assert first.timestamp_seconds == 4.5
    assert first.width == 640
    assert len(calls) == 1
    assert calls[0][:7] == [
        "/fake/ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-ss",
        "4.500",
    ]


def test_materialize_keyframe_rejects_symlink_source(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project-1"
    project_root.mkdir()
    real_source = project_root / "real.mp4"
    real_source.write_bytes(b"source-video")
    symlink = project_root / "source.mp4"
    symlink.symlink_to(real_source)

    with pytest.raises(StorageIntegrityError, match="安全的普通文件"):
        keyframe_cache.materialize_keyframe(
            project_root,
            source_path=symlink,
            source_identity="sha256:source",
            timestamp_seconds=1,
            width=640,
            ffmpeg_path="/fake/ffmpeg",
        )
