# -*- coding: utf-8 -*-
from __future__ import annotations

import builtins

from qwenpaw.agents.utils.audio_transcription import (
    check_local_whisper_available,
)


def test_local_whisper_status_handles_broken_import(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "whisper":
            raise RuntimeError("broken packaged dependency")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(
        "qwenpaw.agents.utils.audio_transcription.shutil.which",
        lambda name: "/usr/local/bin/ffmpeg" if name == "ffmpeg" else None,
    )

    status = check_local_whisper_available()

    assert status == {
        "available": False,
        "ffmpeg_installed": True,
        "whisper_installed": False,
    }
