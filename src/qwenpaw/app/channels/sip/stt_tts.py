# -*- coding: utf-8 -*-
"""STT/TTS factory functions for the SIP voice channel."""
from __future__ import annotations

import asyncio
import logging
import os
import queue as thread_queue
import threading
from typing import AsyncIterator

from .stt_engine import AliyunSTTStream, STTStreamEngine

logger = logging.getLogger(__name__)

# Enough for short scheduling jitter without allowing a whole response to sit
# in memory when the audio output blocks.
_TTS_QUEUE_MAX_CHUNKS = 64


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

    queue: thread_queue.Queue[bytes | None] = thread_queue.Queue(
        maxsize=_TTS_QUEUE_MAX_CHUNKS,
    )
    stopped = threading.Event()

    def _enqueue(chunk: bytes | None) -> None:
        """Block the SDK callback until playback makes room or is cancelled."""
        while not stopped.is_set():
            try:
                queue.put(chunk, timeout=0.1)
                return
            except thread_queue.Full:
                pass

    class _Callback(ResultCallback):
        def on_data(self, data: bytes) -> None:
            _enqueue(data)

        def on_complete(self) -> None:
            _enqueue(None)

        def on_error(self, message: str) -> None:
            logger.error("TTS stream error: %s", message)
            _enqueue(None)

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

    completed = False
    try:
        # ``Queue.get`` is synchronous because DashScope invokes callbacks
        # from its own thread. A timed get also lets us notice a producer that
        # exited without delivering its terminal callback.
        while True:
            try:
                chunk = await asyncio.to_thread(queue.get, True, 0.1)
            except thread_queue.Empty:
                if synth_task.done():
                    break
                continue
            if chunk is None:
                break
            yield chunk
        completed = True
    finally:
        stopped.set()

    # Surface synthesis failures after normal completion. On cancellation the
    # callback observes ``stopped`` and the executor future finishes itself.
    if completed:
        await synth_task
