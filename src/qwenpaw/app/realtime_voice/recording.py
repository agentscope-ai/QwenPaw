# -*- coding: utf-8 -*-
"""Opt-in local replay artifacts; set QWENPAW_VOICE_RECORDING_DIR to enable.

Each connection gets input/output WAVs and events.jsonl. Audio entries index
sample ranges in the WAVs; monotonic elapsed_ms preserves gaps between frames.
Output is audio sent to the browser, not proof it was heard: use the recorded
output.playback feedback and cancellation events when reviewing interruptions.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
import wave
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO

from .contracts import AudioFrame

if TYPE_CHECKING:
    from .service import LiveVoiceSession

logger = logging.getLogger(__name__)


class VoiceRecording:
    """Record the existing relay protocol without changing voice behavior."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._started = time.monotonic()
        self._events = (directory / "events.jsonl").open("x", encoding="utf-8")
        self._audio: dict[str, tuple[BinaryIO, wave.Wave_write]] = {}
        self._closed = False

    @classmethod
    def from_environment(cls, live: LiveVoiceSession) -> VoiceRecording | None:
        root = os.environ.get("QWENPAW_VOICE_RECORDING_DIR", "").strip()
        if not root:
            return None
        try:
            parent = Path(root).expanduser()
            parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            directory = Path(tempfile.mkdtemp(prefix="voice-", dir=parent))
            recording = cls(directory)
        except OSError:
            logger.warning("Could not start voice recording", exc_info=True)
            return None
        recording.event(
            "server",
            {
                "type": "recording.started",
                "started_at": datetime.now(UTC).isoformat(),
                "chat_id": live.chat.id,
                "session_id": live.session_id,
                "generation": live.generation,
                "provider_id": live.config.provider_id,
                "model": live.config.realtime_model,
                "voice": live.config.voice,
                "media": live.media.model_dump(),
            },
        )
        logger.info("Voice recording directory: %s", directory)
        return recording

    def event(self, direction: str, event: dict) -> None:
        if self._closed:
            return
        try:
            self._events.write(
                json.dumps(
                    {
                        "elapsed_ms": round(
                            (time.monotonic() - self._started) * 1000,
                            3,
                        ),
                        "direction": direction,
                        "event": event,
                    },
                    ensure_ascii=False,
                )
                + "\n",
            )
            self._events.flush()
        except (OSError, ValueError, TypeError):
            self._fail()

    def audio(self, direction: str, frame: AudioFrame) -> None:
        if self._closed:
            return
        name = "input.wav" if direction == "client" else "output.wav"
        try:
            if name not in self._audio:
                stream = (self.directory / name).open("xb")
                writer = wave.open(stream, "wb")
                self._audio[name] = (stream, writer)
                writer.setparams(
                    (frame.channels, 2, frame.sample_rate, 0, "NONE", "NONE"),
                )
            stream, writer = self._audio[name]
            offset = writer.getnframes()
            writer.writeframes(frame.payload)
            stream.flush()
            self.event(
                direction,
                {
                    "type": "audio",
                    "file": name,
                    "sequence": frame.sequence,
                    "sample_offset": offset,
                    "sample_count": writer.getnframes() - offset,
                },
            )
        except (OSError, ValueError, wave.Error):
            self._fail()

    def _fail(self) -> None:
        logger.warning(
            "Voice recording stopped after a write error",
            exc_info=True,
        )
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for stream, writer in self._audio.values():
            try:
                writer.close()
            except (OSError, ValueError, wave.Error):
                logger.warning("Could not finalize voice WAV", exc_info=True)
            finally:
                try:
                    stream.close()
                except OSError:
                    logger.warning("Could not close voice WAV", exc_info=True)
        try:
            self._events.close()
        except OSError:
            logger.warning("Could not close voice events", exc_info=True)
