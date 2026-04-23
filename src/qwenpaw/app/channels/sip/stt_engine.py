# -*- coding: utf-8 -*-
"""STT streaming abstraction for the SIP channel."""
from __future__ import annotations

import asyncio
import logging
import os
from typing import (
    Any,
    Awaitable,
    Callable,
    Optional,
    Protocol,
    runtime_checkable,
)

logger = logging.getLogger(__name__)

TranscriptCallback = Callable[[str], Awaitable[None]]
SpeechStartCallback = Callable[[], None]


@runtime_checkable
class STTStreamEngine(Protocol):
    """Protocol for streaming STT engines."""

    on_transcript: Optional[TranscriptCallback]
    on_speech_start: Optional[SpeechStartCallback]

    async def start(self) -> None:
        ...

    async def feed_audio(self, chunk: bytes) -> None:
        ...

    async def stop(self) -> None:
        ...


class AliyunSTTStream:
    """Streaming STT via DashScope Paraformer."""

    def __init__(
        self,
        *,
        api_key: str = "",
        language: str = "zh-CN",
    ) -> None:
        self._api_key = api_key
        self._language = language
        self._asr: Any = None
        self.on_transcript: Optional[TranscriptCallback] = None
        self.on_speech_start: Optional[SpeechStartCallback] = None
        self._speaking = False

    async def start(self) -> None:
        from dashscope_realtime import (
            DashScopeRealtimeASR,
        )
        from dashscope_realtime.asr import ASRConfig

        key = self._api_key or os.environ.get(
            "DASHSCOPE_API_KEY",
            "",
        )
        if not key:
            raise ValueError("DASHSCOPE_API_KEY not set")

        self._transcript_queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def _on_sentence_end(text: str) -> None:
            logger.info("STT sentence_end: %s", text)
            self._speaking = False
            if text:
                loop.call_soon_threadsafe(
                    self._transcript_queue.put_nowait,
                    text,
                )

        def _on_error(e: Exception) -> None:
            logger.error("STT ASR error: %s", e)

        def _on_partial(text: str) -> None:
            if text:
                if not self._speaking:
                    self._speaking = True
                    if self.on_speech_start:
                        self.on_speech_start()
                logger.info("STT partial: %s", text)

        config = ASRConfig(
            sample_rate=16000,
            format="pcm",
            language_hints=["zh", "en"],
        )
        self._asr = DashScopeRealtimeASR(
            api_key=key,
            config=config,
            on_sentence_end=_on_sentence_end,
            on_error=_on_error,
            on_partial=_on_partial,
        )
        await self._asr.__aenter__()
        self._dispatch_task = asyncio.create_task(
            self._dispatch_transcripts(),
        )
        logger.info(
            "STT engine started (lang=%s)",
            self._language,
        )

    async def _dispatch_transcripts(self) -> None:
        """Dispatch transcripts to the callback."""
        try:
            while True:
                text = await self._transcript_queue.get()
                if text is None:
                    break
                if self.on_transcript:
                    asyncio.ensure_future(
                        self.on_transcript(text),
                    )
        except asyncio.CancelledError:
            pass

    async def feed_audio(self, chunk: bytes) -> None:
        if self._asr is not None:
            await self._asr.send_audio(chunk)

    async def stop(self) -> None:
        task = getattr(self, "_dispatch_task", None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if self._asr is not None:
            try:
                await self._asr.finish()
                await self._asr.__aexit__(
                    None,
                    None,
                    None,
                )
            except Exception:
                logger.debug(
                    "Error closing ASR",
                    exc_info=True,
                )
            self._asr = None
