# -*- coding: utf-8 -*-
"""STT/TTS factory functions for the SIP voice channel."""
from __future__ import annotations

import asyncio
import logging
import os
from typing import AsyncIterator

from .stt_engine import AliyunSTTStream, STTStreamEngine

logger = logging.getLogger(__name__)


def _resolve_dashscope_key(api_key: str = "") -> str:
    """Return *api_key* if non-empty, else fall back to env var."""
    return api_key or os.environ.get("DASHSCOPE_API_KEY", "")


def create_stt_engine(
    provider: str,
    language: str,
    api_key: str = "",
) -> STTStreamEngine:
    """Create a streaming STT engine for *provider*."""
    if provider == "aliyun":
        return AliyunSTTStream(
            api_key=_resolve_dashscope_key(api_key),
            language=language,
        )
    raise ValueError(
        f"Unsupported STT provider: {provider}",
    )


# ----------------------------------------------------------
# Non-streaming TTS (legacy, kept for fallback / tests)
# ----------------------------------------------------------


async def synthesize_tts(
    provider: str,
    text: str,
    voice: str,
    api_key: str = "",
) -> bytes:
    """Synthesize *text* and return WAV bytes."""
    if provider == "aliyun":
        return await _synthesize_aliyun(
            text,
            voice,
            _resolve_dashscope_key(api_key),
        )
    raise ValueError(
        f"Unsupported TTS provider: {provider}",
    )


async def _synthesize_aliyun(
    text: str,
    voice: str,
    api_key: str = "",
) -> bytes:
    from dashscope.audio.tts import SpeechSynthesizer

    response = await asyncio.to_thread(
        SpeechSynthesizer.call,
        model=voice or "sambert-zhichu-v1",
        text=text,
        sample_rate=8000,
        format="wav",
        api_key=api_key or None,
    )
    if response and hasattr(response, "get_audio_data"):
        return response.get_audio_data() or b""
    return b""


# ----------------------------------------------------------
# Streaming TTS (tts_v2, unidirectional streaming)
# ----------------------------------------------------------


async def synthesize_tts_stream(
    provider: str,
    text: str,
    voice: str,
    api_key: str = "",
    *,
    sample_rate: int = 8000,
) -> AsyncIterator[bytes]:
    """Yield raw PCM chunks as they arrive from TTS."""
    if provider == "aliyun":
        async for chunk in _stream_aliyun(
            text,
            voice,
            _resolve_dashscope_key(api_key),
            sample_rate=sample_rate,
        ):
            yield chunk
    else:
        raise ValueError(
            f"Unsupported TTS provider: {provider}",
        )


async def _stream_aliyun(
    text: str,
    voice: str,
    api_key: str = "",
    *,
    sample_rate: int = 8000,
) -> AsyncIterator[bytes]:
    from dashscope.audio.tts_v2 import (
        AudioFormat,
        ResultCallback,
        SpeechSynthesizer,
    )

    # tts_v2 SpeechSynthesizer doesn't accept api_key as __init__ arg;
    # set it via the module-level variable instead.
    if api_key:
        import dashscope

        dashscope.api_key = api_key

    fmt_map = {
        8000: AudioFormat.PCM_8000HZ_MONO_16BIT,
        16000: AudioFormat.PCM_16000HZ_MONO_16BIT,
        22050: AudioFormat.PCM_22050HZ_MONO_16BIT,
        24000: AudioFormat.PCM_24000HZ_MONO_16BIT,
    }
    audio_fmt = fmt_map.get(
        sample_rate,
        AudioFormat.PCM_8000HZ_MONO_16BIT,
    )

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    class _Callback(ResultCallback):
        def on_data(self, data: bytes) -> None:
            loop.call_soon_threadsafe(
                queue.put_nowait,
                data,
            )

        def on_complete(self) -> None:
            loop.call_soon_threadsafe(
                queue.put_nowait,
                None,
            )

        def on_error(self, message: str) -> None:
            logger.error("TTS stream error: %s", message)
            loop.call_soon_threadsafe(
                queue.put_nowait,
                None,
            )

        def on_close(self) -> None:
            pass

        def on_open(self) -> None:
            pass

        def on_event(self, message) -> None:
            pass

    callback = _Callback()
    synthesizer = SpeechSynthesizer(
        model="cosyvoice-v1",
        voice=voice or "longxiaochun",
        format=audio_fmt,
        callback=callback,
    )

    # Run call() in a background thread; it blocks until synthesis
    # completes, but on_data callbacks fire in the WS thread and
    # push chunks into the queue in real time.
    synth_task = asyncio.get_running_loop().run_in_executor(
        None,
        synthesizer.call,
        text,
    )

    # Drain the queue concurrently while synthesis is running
    while True:
        chunk = await queue.get()
        if chunk is None:
            break
        yield chunk

    # Ensure the background thread finishes cleanly
    await synth_task
