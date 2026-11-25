# -*- coding: utf-8 -*-
"""Enforce silent delivery when a video provider cannot disable audio."""

from dataclasses import replace
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile

from domain.errors import ValidationError
from services.runtime_files.media_probe import probe_media
from services.runtime_files.runtime_dependencies import resolve_ffmpeg

from .secure_video_stream import MaterializedVideo


def silence_materialized_video(video: MaterializedVideo) -> MaterializedVideo:
    """Remux a verified task-local copy; never transcode its video frames.

    Native-audio controls are not available on every provider. The authored
    silent intent must hold for published bytes as well as request metadata.
    """
    executable = resolve_ffmpeg() or "ffmpeg"
    if not probe_media(video.path, ffmpeg_path=executable).has_audio:
        return video
    descriptor, name = tempfile.mkstemp(
        prefix="silent-",
        suffix=video.path.suffix,
        dir=video.path.parent,
    )
    os.close(descriptor)
    output = Path(name)
    arguments = [
        executable,
        "-v",
        "error",
        "-nostdin",
        "-y",
        "-i",
        os.fspath(video.path),
        "-map",
        "0:v:0",
        "-c:v",
        "copy",
        "-an",
    ]
    if video.container in {"mp4", "quicktime"}:
        arguments.extend(["-movflags", "+faststart"])
    try:
        subprocess.run(
            [*arguments, os.fspath(output)],
            check=True,
            capture_output=True,
            timeout=60,
        )
        if probe_media(output, ffmpeg_path=executable).has_audio:
            raise ValidationError("静音处理后仍存在音轨，无法发布视频")
        digest = hashlib.sha256()
        with output.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        result = replace(
            video,
            path=output,
            sha256=digest.hexdigest(),
            size_bytes=output.stat().st_size,
        )
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    video.path.unlink()
    return result
