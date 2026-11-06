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
        try:
            import whisper  # noqa: F401 pylint: disable=unused-import
        except ImportError as exc:
            return TranscriptionStatus(False, str(exc))
        return TranscriptionStatus(True)

    def transcribe(self, context, file_path):
        # The SDK runs synchronous callbacks in a tracked worker thread.
        # Serialise inference as well as model creation: Whisper mutates hooks.
        with self._lock:
            context.check_cancelled()
            status = self.status(context)
            if not status.available:
                return TranscriptionResult(
                    error="unavailable",
                    message=status.reason,
                )
            try:
                if self._model is None:
                    import whisper

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
