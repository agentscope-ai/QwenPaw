# -*- coding: utf-8 -*-
"""FFmpeg-based audio conversion helpers for QQ voice messages."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import tempfile
from typing import Optional

LOGGER = logging.getLogger(__name__)

AUDIO_EXTENSIONS = {"aac", "amr", "flac", "m4a", "mp3", "ogg", "opus", "silk", "wav"}
SILK_EXTENSION = "silk"


def _extension(path: str) -> str:
    return os.path.splitext(os.fspath(path))[1].lower().lstrip(".")


def is_audio_file(path) -> bool:
    """Return ``True`` when *path* has a supported audio extension."""

    return _extension(os.fspath(path)) in AUDIO_EXTENSIONS


def should_transcode_voice(path) -> bool:
    """Return ``True`` when *path* is audio and not already SILK."""

    return is_audio_file(path) and _extension(os.fspath(path)) != SILK_EXTENSION


def _find_binary(name: str) -> Optional[str]:
    binary = shutil.which(name)
    if not binary:
        LOGGER.error("%s executable not found in PATH", name)
    return binary


async def get_audio_duration(path: str) -> float:
    """Return the audio duration in seconds using ffprobe."""

    ffprobe = _find_binary("ffprobe")
    if not ffprobe or not os.path.isfile(path):
        LOGGER.warning("Unable to probe duration for missing file: %s", path)
        return 0.0
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
    except Exception:
        LOGGER.exception("ffprobe failed for %s", path)
        return 0.0
    if process.returncode != 0:
        LOGGER.error("ffprobe returned %s for %s: %s", process.returncode, path, stderr.decode().strip())
        return 0.0
    try:
        return float(stdout.decode().strip() or 0.0)
    except ValueError:
        LOGGER.error("Invalid ffprobe duration output for %s: %r", path, stdout)
        return 0.0


def _run_ffmpeg_pipeline(ffmpeg: str, input_path: str, output_path: str) -> bool:
    decode_cmd = [
        ffmpeg,
        "-y",
        "-v",
        "error",
        "-i",
        input_path,
        "-ar",
        "24000",
        "-ac",
        "1",
        "-acodec",
        "pcm_s16le",
        "-f",
        "s16le",
        "-",
    ]
    encode_cmd = [
        ffmpeg,
        "-y",
        "-v",
        "error",
        "-f",
        "s16le",
        "-ar",
        "24000",
        "-ac",
        "1",
        "-i",
        "-",
        "-acodec",
        "silk",
        "-ar",
        "24000",
        output_path,
    ]
    try:
        first = subprocess.Popen(decode_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        second = subprocess.Popen(
            encode_cmd, stdin=first.stdout, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
        )
        if first.stdout:
            first.stdout.close()
        _, first_stderr = first.communicate()
        _, second_stderr = second.communicate()
    except Exception:
        LOGGER.exception("FFmpeg conversion pipeline failed for %s", input_path)
        return False
    if first.returncode != 0 or second.returncode != 0:
        LOGGER.error(
            "FFmpeg conversion failed for %s: decode=%s (%s), encode=%s (%s)",
            input_path,
            first.returncode,
            first_stderr.decode().strip(),
            second.returncode,
            second_stderr.decode().strip(),
        )
        return False
    if not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
        LOGGER.error("FFmpeg conversion produced no output for %s", input_path)
        return False
    return True


async def audio_to_silk(input_path: str, output_dir: str) -> Optional[str]:
    """Convert *input_path* to a SILK file inside *output_dir*."""

    ffmpeg = _find_binary("ffmpeg")
    if not ffmpeg or not os.path.isfile(input_path) or not is_audio_file(input_path):
        LOGGER.warning("Cannot convert unsupported or missing audio file: %s", input_path)
        return None
    os.makedirs(output_dir, exist_ok=True)
    final_path = os.path.join(output_dir, f"{os.path.splitext(os.path.basename(input_path))[0]}.silk")
    if _extension(input_path) == SILK_EXTENSION:
        try:
            if os.path.abspath(input_path) != os.path.abspath(final_path):
                shutil.copy2(input_path, final_path)
            return final_path
        except OSError:
            LOGGER.exception("Failed to copy SILK file from %s to %s", input_path, final_path)
            return None
    with tempfile.TemporaryDirectory(prefix="qq-audio-", dir=output_dir) as temp_dir:
        temp_output = os.path.join(temp_dir, "voice.silk")
        if not await asyncio.to_thread(_run_ffmpeg_pipeline, ffmpeg, input_path, temp_output):
            return None
        try:
            os.replace(temp_output, final_path)
            return final_path
        except OSError:
            LOGGER.exception("Failed to move converted SILK file into place: %s", final_path)
            return None


async def convert_to_silk(input_path: str, output_dir: str) -> Optional[str]:
    """Alias for :func:`audio_to_silk`."""

    return await audio_to_silk(input_path, output_dir)
