# -*- coding: utf-8 -*-
"""Bounded voice-identity excerpts for video providers.

The enrolled sample remains intact. Wan3 accepts at most 15 seconds across
all reference audio, whereas an enrollment audition can be much longer.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import tempfile
import wave

from models.media_transport import read_reference_media
from services.runtime_files.runtime_dependencies import resolve_ffmpeg
from utils.exceptions import ModelError


@asynccontextmanager
async def wan_voice_excerpt(url: str, *, voice_count: int):
    """Yield a local WAV URL valid until its provider upload completes."""

    if not 1 <= voice_count <= 5:
        raise ValueError("Wan3 reference voice count must be between 1 and 5")
    executable = resolve_ffmpeg()
    if not executable:
        raise ModelError(
            "FFmpeg is required to prepare reference voices",
            retryable=False,
        )
    content, filename = await read_reference_media(url)
    # Leave room for container/sample rounding in the provider's duration
    # check. Each character keeps the same share of the total voice budget.
    duration = 14.5 / voice_count
    with tempfile.TemporaryDirectory(prefix="creator-reference-voice-") as tmp:
        source = Path(tmp) / f"source{Path(filename).suffix}"
        output = Path(tmp) / "voice.wav"
        source.write_bytes(content)
        process = await asyncio.create_subprocess_exec(
            executable,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-protocol_whitelist",
            "file,pipe",
            "-i",
            str(source),
            "-map",
            "0:a:0",
            "-vn",
            "-af",
            "silenceremove=start_periods=1:start_duration=0.05:"
            "start_threshold=-45dB",
            "-t",
            str(duration),
            "-ar",
            "24000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(output),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=30,
            )
        except BaseException:
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise
        if process.returncode != 0:
            raise ModelError(
                "Reference voice could not be decoded: "
                + stderr.decode("utf-8", errors="replace")[-500:],
                retryable=False,
            )
        with wave.open(str(output), "rb") as audio:
            seconds = audio.getnframes() / audio.getframerate()
        if seconds < 1:
            raise ModelError(
                "Reference voice needs at least 1 second of audible speech; "
                "select or generate a longer character sample",
                retryable=False,
            )
        yield output.as_uri()
