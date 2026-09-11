# -*- coding: utf-8 -*-
"""Browser-side engine source bundled with the CDP control link."""

from pathlib import Path

_ENGINE_SOURCE: str | None = None


def get_engine_source() -> str:
    """Return the cached self-contained browser injection source."""
    global _ENGINE_SOURCE
    if _ENGINE_SOURCE is None:
        _ENGINE_SOURCE = (Path(__file__).parent / "engine.js").read_text(
            encoding="utf-8",
        )
    return _ENGINE_SOURCE
