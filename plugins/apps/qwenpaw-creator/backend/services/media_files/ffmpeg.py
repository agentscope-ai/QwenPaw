# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""FFmpeg capability projection for the file-native media runtime."""

from __future__ import annotations

from typing import Any

from services.runtime_files.runtime_dependencies import resolve_ffmpeg


def ffmpeg_readiness() -> dict[str, Any]:
    path = resolve_ffmpeg()
    return {
        "status": "ok" if path else "missing",
        "binary": "ffmpeg",
        "path": path,
        "capabilities": [
            "concat_demuxer",
            "stream_copy",
            "remote_protocol_whitelist",
        ],
        "blockers": (
            []
            if path
            else [
                "ffmpeg binary is not available on PATH or bundled dependencies",
            ]
        ),
    }


__all__ = ["ffmpeg_readiness"]
