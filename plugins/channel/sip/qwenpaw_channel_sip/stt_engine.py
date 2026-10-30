# -*- coding: utf-8 -*-
"""Lazy DashScope ASR with bounded thread-to-loop transcript dispatch."""
from __future__ import annotations

import asyncio
import os
import queue
import threading
from typing import Awaitable, Callable, Protocol


class STTStreamEngine(Protocol):
    on_transcript: Callable[[str], Awaitable[None]] | None
    on_speech_start: Callable[[], None] | None

    async def start(self):
        ...

    async def feed_audio(self, chunk):
        ...

    async def stop(self):
        ...


class AliyunSTTStream:
    TRANSCRIPT_LIMIT = 32

    def __init__(self, *, api_key="", language="zh-CN"):
        self._api_key, self._language = api_key, language
        self._asr = None
        self._dispatch_task = None
        self._error_task = None
        self._speaking = False
        self._stopped = threading.Event()
        self._failed = threading.Event()
        self._transcript_queue = queue.Queue(maxsize=self.TRANSCRIPT_LIMIT)
        self.on_transcript = None
        self.on_speech_start = None
        self.on_error = None
        self._error_reason = None

    async def start(self):
        from dashscope_realtime import DashScopeRealtimeASR
        from dashscope_realtime.asr import ASRConfig

        key = self._api_key or os.environ.get("DASHSCOPE_API_KEY", "")
        if not key:
            raise ValueError("DASHSCOPE_API_KEY not set")
        self._loop = asyncio.get_running_loop()
        self._wake = asyncio.Event()
        self._stopped.clear()

        def fatal(reason):
            if not self._stopped.is_set() and not self._failed.is_set():
                self._error_reason = reason
                self._failed.set()
                self._loop.call_soon_threadsafe(self._notify_failure)

        def sentence(text):
            self._speaking = False
            if not text or self._stopped.is_set() or self._failed.is_set():
                return
            if len(text) > 65536:
                fatal("STT_TRANSCRIPT_BACKPRESSURE")
                return
            try:
                self._transcript_queue.put_nowait(text)
            except queue.Full:
                fatal("STT_TRANSCRIPT_BACKPRESSURE")
                return
            self._loop.call_soon_threadsafe(self._wake.set)

        def partial(text):
            if (
                text
                and not self._speaking
                and not self._stopped.is_set()
                and not self._failed.is_set()
            ):
                self._speaking = True
                self._loop.call_soon_threadsafe(speech)

        def speech():
            if not self._stopped.is_set() and self.on_speech_start:
                self.on_speech_start()

        self._asr = DashScopeRealtimeASR(
            api_key=key,
            config=ASRConfig(
                sample_rate=16000,
                format="pcm",
                language_hints=["zh", "en"],
            ),
            on_sentence_end=sentence,
            on_error=lambda error: fatal("STT_STREAM_FAILED"),
            on_partial=partial,
        )
        await self._asr.__aenter__()
        self._dispatch_task = asyncio.create_task(self._dispatch_transcripts())

    def _notify_failure(self):
        if self._stopped.is_set():
            return
        self._wake.set()
        if self._error_task is None:
            self._error_task = asyncio.create_task(self._dispatch_failure())

    async def _dispatch_failure(self):
        if self.on_error:
            await self.on_error(self._error_reason)
        else:
            raise RuntimeError(self._error_reason)

    async def _dispatch_transcripts(self):
        while not self._stopped.is_set():
            await self._wake.wait()
            self._wake.clear()
            if self._failed.is_set():
                return
            while not self._stopped.is_set():
                try:
                    text = self._transcript_queue.get_nowait()
                except queue.Empty:
                    break
                if self.on_transcript:
                    await self.on_transcript(text)
                if self._failed.is_set():
                    self._wake.set()
                    break

    async def feed_audio(self, chunk):
        if self._asr is not None and not self._stopped.is_set():
            await self._asr.send_audio(chunk)

    async def stop(self):
        self._stopped.set()
        failures = []
        for name in ("_dispatch_task", "_error_task"):
            task = getattr(self, name)
            if task is not None and task is not asyncio.current_task():
                if not task.done():
                    task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    setattr(self, name, None)
                except Exception as exc:
                    failures.append(exc)
                else:
                    setattr(self, name, None)
        if self._asr is not None:
            closed = True
            try:
                await self._asr.finish()
            except Exception as exc:
                failures.append(exc)
                closed = False
            try:
                await self._asr.__aexit__(None, None, None)
            except Exception as exc:
                failures.append(exc)
                closed = False
            if closed:
                self._asr = None
        if failures:
            raise RuntimeError("SIP_STT_STOP_INCOMPLETE") from failures[0]
