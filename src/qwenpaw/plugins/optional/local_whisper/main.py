# -*- coding: utf-8 -*-
"""Optional local recognizer. Importing/registering never imports Whisper."""

import shutil
import threading

from qwenpaw.plugins.transcription import (
    TranscriptionSpec,
    TranscriptionStatus,
    TranscriptionResult,
)


class Plugin:
    def __init__(self):
        self._model = None
        self._lock = threading.Lock()
        self._import_status = TranscriptionStatus(True)

    def register(self, context):
        context.on_activate(self.activate)
        context.register_transcription_backend(
            TranscriptionSpec(
                "local_whisper",
                "Local Whisper",
                self.transcribe,
                self.status,
            ),
        )

    def activate(self, context):
        context.resources.connection(self, "local-whisper-model")

    def close(self):
        self._model = None

    def status(self, _context):
        if shutil.which("ffmpeg") is None:
            return TranscriptionStatus(False, "ffmpeg is not installed")
        # Read the last import result; status queries never load dependencies.
        return self._import_status

    def transcribe(self, context, file_path):
        # The SDK runs synchronous callbacks in a tracked worker thread.
        # Serialise inference as well as model creation: Whisper mutates hooks.
        with self._lock:
            context.check_cancelled()
            if shutil.which("ffmpeg") is None:
                return TranscriptionResult(
                    error="unavailable",
                    message="ffmpeg is not installed",
                )
            try:
                import whisper
            except Exception as exc:
                self._import_status = TranscriptionStatus(
                    False,
                    str(exc) or type(exc).__name__,
                )
                return TranscriptionResult(
                    error="unavailable",
                    message=self._import_status.reason,
                )
            self._import_status = TranscriptionStatus(True)
            try:
                if self._model is None:
                    self._model = whisper.load_model("base")
                text = (
                    self._model.transcribe(file_path).get("text") or ""
                ).strip()
                return TranscriptionResult(
                    text=text,
                    error="" if text else "empty",
                )
            except Exception as exc:
                context.logger.exception("Local Whisper transcription failed")
                return TranscriptionResult(error="failed", message=str(exc))


plugin = Plugin()
